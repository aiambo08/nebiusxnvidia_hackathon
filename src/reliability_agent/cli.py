"""Command line entry point: `ra-demo scenario|live|all`."""

from __future__ import annotations

import argparse
import logging
import sys
import threading
from pathlib import Path

from reliability_agent.config import api_key, load_config

TOUR_SCENARIOS = (
    "dark", "defocus", "occlusion", "bad_action", "frozen_black", "overexposure", "freeze",
)


def _print_window(tw, agent) -> None:
    v, t = tw.visual, tw.task
    task = t.success_rate if t.success_rate is not None else float("nan")
    print(f"[{agent.state:<12}] fps={tw.transport.capture_fps:5.1f} "
          f"bright={v.brightness_p50 or 0:6.1f} blur={v.blur_effect_p50 or 0:4.2f} "
          f"occ={v.occluded_cell_ratio or 0:4.2f} task={task:4.2f}")


def _planner(kind: str, cfg: dict):
    from reliability_agent.nemotron import BudgetGuard, RuleBasedPlanner, make_planner

    if kind == "rules":
        return RuleBasedPlanner()
    key = api_key()
    if key is None:
        print("NEBIUS_API_KEY not set -> local rule-based fallback", file=sys.stderr)
    return make_planner(cfg, key, BudgetGuard.from_config(cfg))


def mode_label(args_or_uri) -> str:
    if hasattr(args_or_uri, "live"):
        if not args_or_uri.live:
            return "SIMULATION"
        uri = getattr(args_or_uri, "uri", None)
    else:
        uri = args_or_uri
    if uri is None or isinstance(uri, int):
        return "REAL HARDWARE"
    value = str(uri).strip().lower()
    if value.isdecimal() or value.startswith(("rtsp://", "rtsps://", "http://", "https://")):
        return "REAL HARDWARE"
    return "REPLAY"


def _run_dashboard_scenarios(args, cfg, feed, store, planner_kind, stop_event) -> None:
    from reliability_agent.demo import run_scenario

    scenarios = args.scenarios or list(TOUR_SCENARIOS)
    while not stop_event.is_set():
        for index, name in enumerate(scenarios):
            if stop_event.is_set():
                return
            feed.set_scenario(name)
            run_scenario(
                name,
                _planner(planner_kind, cfg),
                cfg=cfg,
                store=store,
                seed=0,
                on_window=feed.on_window,
                on_frame=feed.on_frame,
                pace_s=args.pace,
                stop_event=stop_event,
            )
            if stop_event.is_set():
                return
            if index + 1 < len(scenarios) or args.loop:
                if stop_event.wait(args.gap):
                    return
        if not args.loop:
            return


def _dashboard(args) -> int:
    try:
        import uvicorn

        from apps.api.main import create_app
        from reliability_agent.demo import demo_config
        from reliability_agent.feed import LiveFeed
        from reliability_agent.runtime import run_live
        from reliability_agent.storage.event_store import EventStore
    except ImportError as exc:
        if exc.name not in {"fastapi", "uvicorn"}:
            raise
        raise SystemExit('Install the dashboard extra with: pip install -e ".[api]"') from exc

    if not args.live and args.uri is not None:
        raise SystemExit("--uri requires --live")
    cfg = load_config() if args.live else demo_config()
    if args.live and args.uri is not None:
        cfg["camera"]["uri"] = args.uri
    if args.live:
        args.uri = cfg["camera"]["uri"]
    mode = mode_label(args)
    has_key = api_key() is not None
    planner_kind = args.planner or ("nemotron" if has_key else "rules")
    cfg["planner"]["kind"] = planner_kind
    if not args.live:
        cfg["storage"]["restore_on_start"] = False

    if args.db == ":memory:":
        db_path = ":memory:"
    else:
        db_path = Path(args.db).expanduser()
        if db_path.exists() and not args.append:
            raise SystemExit(f"{db_path} already exists; use --append or choose a new --db path")
        db_path.parent.mkdir(parents=True, exist_ok=True)
        db_path = str(db_path)
    store = EventStore(db_path)
    source_label = {
        "SIMULATION": "SyntheticSource",
        "REAL HARDWARE": "Live camera",
        "REPLAY": "Video replay",
    }[mode]
    feed = LiveFeed(mode, source_label)
    stop_event = threading.Event()

    try:
        app = create_app(store=store, feed=feed, cfg=cfg)

        def agent_loop() -> None:
            try:
                if args.live:
                    run_live(
                        cfg,
                        on_window=feed.on_window,
                        on_frame=feed.on_frame,
                        store=store,
                        stop_event=stop_event,
                    )
                else:
                    _run_dashboard_scenarios(
                        args, cfg, feed, store, planner_kind, stop_event
                    )
            except Exception:
                logging.exception("Dashboard agent loop stopped")

        agent_thread = threading.Thread(
            target=agent_loop, daemon=True, name="ra-dashboard-agent"
        )
        print(f"Mode: {mode}")
        print(f"Planner: {planner_kind}")
        print(f"Database: {db_path}")
        print(f"Dashboard: http://{args.host}:{args.port}")
        agent_thread.start()
        try:
            uvicorn.run(app, host=args.host, port=args.port)
        except KeyboardInterrupt:
            pass
        finally:
            stop_event.set()
            agent_thread.join()
    finally:
        stop_event.set()
        store.close()
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="ra-demo")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sc = sub.add_parser("scenario", help="deterministic SIMULATION scenario (no hardware)")
    sc.add_argument("name")
    sc.add_argument("--planner", choices=["rules", "nemotron"], default="rules")
    sc.add_argument("--seed", type=int, default=0)
    sub.add_parser("all", help="run every simulation scenario with the rule planner")
    lv = sub.add_parser("live", help="REAL camera loop")
    lv.add_argument("--uri", default=None, help="webcam index, file or rtsp:// URL")
    lv.add_argument("--seconds", type=float, default=None)
    from reliability_agent.demo import SCENARIOS

    dashboard = sub.add_parser("dashboard", help="read-only dashboard and agent demo")
    mode = dashboard.add_mutually_exclusive_group()
    mode.add_argument("--live", action="store_true", help="run the configured live source")
    mode.add_argument("--scenario", dest="scenarios", action="append",
                      choices=tuple(SCENARIOS), help="simulation scenario (repeatable)")
    dashboard.add_argument("--uri", default=None, help="webcam index, file or camera URL")
    dashboard.add_argument("--planner", choices=["rules", "nemotron"], default=None)
    dashboard.add_argument("--pace", type=float, default=1.0, help="seconds per simulation window")
    dashboard.add_argument("--loop", action="store_true", help="repeat the selected scenario tour")
    dashboard.add_argument("--gap", type=float, default=6.0, help="seconds between scenarios")
    dashboard.add_argument("--host", default="127.0.0.1")
    dashboard.add_argument("--port", type=int, default=8000)
    dashboard.add_argument("--db", default="runs/dashboard.sqlite")
    dashboard.add_argument("--append", action="store_true", help="reuse an existing database")
    ap.add_argument("-v", "--verbose", action="store_true")
    args = ap.parse_args(argv)
    logging.basicConfig(level=logging.INFO if args.verbose else logging.WARNING)

    if args.cmd == "dashboard":
        if args.pace < 0 or args.gap < 0:
            raise SystemExit("--pace and --gap must be >= 0")
        return _dashboard(args)
    if args.cmd in ("scenario", "all"):
        from reliability_agent.demo import SCENARIOS, demo_config, run_scenario

        cfg = demo_config()
        names = list(SCENARIOS) if args.cmd == "all" else [args.name]
        for n in names:
            planner = _planner(getattr(args, "planner", "rules"), cfg)
            res = run_scenario(n, planner, cfg=cfg, seed=getattr(args, "seed", 0))
            ver = [e["payload"]["status"] for e in res.events if e["kind"] == "verification"]
            plans = [e["payload"] for e in res.events if e["kind"] == "plan"]
            print(f"\n=== SIMULATION scenario: {n} ===")
            for p in plans:
                pl, u = p["plan"], p["usage"]
                print(f"plan[{p['source']}]: {pl['diagnosis']} -> {pl['action']['name']} "
                      f"{pl['action']['arguments']} | model={u['model']} "
                      f"tokens={u['input_tokens']}/{u['output_tokens']} "
                      f"cost=${u['estimated_cost_usd']:.5f}")
            print("verification:", ver or "n/a")
            print("transitions:", " | ".join(res.transitions))
            print("final:", res.final_state)
        return 0
    if args.cmd == "live":
        from reliability_agent.runtime import run_live

        cfg = load_config()
        if args.uri is not None:
            cfg["camera"]["uri"] = args.uri
        print("REAL HARDWARE mode. Ctrl+C to stop.")
        try:
            run_live(cfg, duration_s=args.seconds, on_window=_print_window)
        except KeyboardInterrupt:
            pass
        return 0
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
