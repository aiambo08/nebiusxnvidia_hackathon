"""Command line entry point: `ra-demo scenario|live|all`."""

from __future__ import annotations

import argparse
import logging
import sys

from reliability_agent.config import api_key, load_config


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
    ap.add_argument("-v", "--verbose", action="store_true")
    args = ap.parse_args(argv)
    logging.basicConfig(level=logging.INFO if args.verbose else logging.WARNING)

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
