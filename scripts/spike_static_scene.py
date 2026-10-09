"""Gate F3 spike: run the local detection path on a live camera at rest (REAL HARDWARE).

    python scripts/spike_static_scene.py --uri 0 --minutes 20 --label webcam-rest
    python scripts/spike_static_scene.py --uri $env:RA_TEST_RTSP --minutes 20 --label rtsp-wall

Same path as `benchmarks.replay.replay` (probes -> windows -> baseline -> IncidentTracker), but
fed by `CaptureWorker` from a real source. Logs per window the freeze telemetry of ADR-005
(`visual.exact_repeat_ratio`, `visual.noise_ratio_p50`, `visual.temporal_sigma_p50`,
`visual.loop_period`) and the tracker state, and writes:

- spikes/static-scene-<label>.md   summary (commit it as evidence)
- spikes/static-scene-<label>.json per-window series + worker `health()` (never the URI)

Verdict (same criterion as `docs/evidence/f3/static-scene.md`): FAIL, exit 1, if any window
reports `freeze`; INCONCLUSIVE, exit 3, if the source did not deliver frames for almost the whole
run (valid windows < 95 % or `stream_down` / `low_fps` seen); PASS, exit 0, otherwise. The scene is
expected to be a *healthy* camera at rest. The label is a free tag for the report file name; a URL
or IP address in it is rejected. The reports never contain the URI, but FFmpeg may print
`tcp://<ip>:<port>` on stderr when a connection fails: review stderr before pasting it anywhere.
"""

from __future__ import annotations

import argparse
import json
import re
import time
from typing import Any

import _src_path  # noqa: F401  (adds src/ to sys.path)
import numpy as np

from reliability_agent.baselines.robust import RobustBaseline
from reliability_agent.capture import CaptureWorker, OpenCVSource, SyntheticSource
from reliability_agent.config import REPO_ROOT, load_config
from reliability_agent.incidents.fusion import IncidentTracker
from reliability_agent.probes.runner import ProbeRunner, WindowAggregator

VALID_MIN = 0.95  # share of windows with frames below which the run is INCONCLUSIVE
TRANSPORT_FAULTS = {"stream_down", "low_fps"}
METRICS = ("exact_repeat_ratio", "noise_ratio_p50", "temporal_sigma_p50", "temporal_mse_p50",
           "repeated_hash_ratio", "loop_period")


def _pct(values: list[float], q: float) -> float | None:
    return round(float(np.percentile(values, q)), 4) if values else None


def summarise(windows: list[dict[str, Any]], freeze_min: float) -> dict[str, Any]:
    """Aggregate the per-window series: freeze windows, confirmation and metric quantiles."""
    out: dict[str, Any] = {
        "windows": len(windows),
        "valid_windows": sum(w["frames"] > 0 for w in windows),
        "freeze_windows": sum("freeze" in w["faults"] for w in windows),
        "other_fault_windows": sum(bool(set(w["faults"]) - {"freeze"}) for w in windows),
        "confirmed": None,
        "confirmed_at_s": None,
        "exact_repeat_ge_min": sum(
            (w["exact_repeat_ratio"] or 0.0) >= freeze_min for w in windows),
        "loop_windows": sum((w["loop_period"] or 0) > 0 for w in windows),
        "transport_fault_windows": sum(
            bool(TRANSPORT_FAULTS & set(w["faults"])) for w in windows),
        "metrics": {},
    }
    for w in windows:
        if w["confirmed"]:
            out["confirmed"], out["confirmed_at_s"] = w["confirmed"], w["t_s"]
            break
    if out["freeze_windows"]:
        first = next(w["t_s"] for w in windows if "freeze" in w["faults"])
        out["verdict"] = (f"FAIL: `freeze` in {out['freeze_windows']} window(s), first at "
                          f"{first:.0f} s" + (f"; confirmed: {', '.join(out['confirmed'])} at "
                                              f"{out['confirmed_at_s']:.0f} s"
                                              if out["confirmed"] else ""))
        out["exit_code"] = 1
    elif (not windows or out["valid_windows"] < VALID_MIN * len(windows)
          or out["transport_fault_windows"]):
        out["verdict"] = (f"INCONCLUSIVE: {out['valid_windows']}/{len(windows)} windows with "
                          f"frames, {out['transport_fault_windows']} with stream_down/low_fps; "
                          "the source did not deliver a steady picture")
        out["exit_code"] = 3
    else:
        out["verdict"] = "PASS: no `freeze` window on a camera at rest"
        if out["confirmed"]:
            out["verdict"] += (f"; finding: {', '.join(out['confirmed'])} confirmed at "
                               f"{out['confirmed_at_s']:.0f} s (another detector)")
        out["exit_code"] = 0
    for m in METRICS:
        vals = [float(w[m]) for w in windows if w.get(m) is not None]
        out["metrics"][m] = {"p50": _pct(vals, 50), "p95": _pct(vals, 95),
                             "max": _pct(vals, 100), "n": len(vals)}
    return out


def render(label: str, kind: str, minutes: float, fps: float, shape: str,
           summ: dict[str, Any], health: dict[str, Any], stalled_polls: int, polls: int,
           freeze_min: float) -> str:
    tr = health.get("transport", {})
    m = summ["metrics"]
    lines = [
        f"# Static-scene spike `{label}` (Gate F3) — REAL HARDWARE" if kind != "synthetic"
        else f"# Static-scene spike `{label}` (Gate F3) — SIMULATION (dry run)",
        "",
        f"- source: {kind} | frame: {shape} | duration: {minutes:g} min | analytic {fps:g} FPS",
        f"- windows: {summ['windows']}, valid: {summ['valid_windows']}, "
        f"freeze windows: {summ['freeze_windows']}, other-fault windows: "
        f"{summ['other_fault_windows']}",
        f"- windows with exact_repeat_ratio >= {freeze_min:g}: {summ['exact_repeat_ge_min']}; "
        f"loop windows: {summ['loop_windows']}; stalled polls (same frame twice): "
        f"{stalled_polls}/{polls}",
        f"- capture fps: {tr.get('capture_fps')}, decode errors: {tr.get('decode_errors')}, "
        f"reconnects: {tr.get('reconnect_count')}, dropped: {tr.get('dropped_frames')}",
        f"- result: {summ['verdict']}",
        "",
        "| metric | p50 | p95 | max | n |",
        "|---|---|---|---|---|",
    ]
    lines += [f"| {k} | {v['p50']} | {v['p95']} | {v['max']} | {v['n']} |" for k, v in m.items()]
    lines += ["", f"generated: {time.strftime('%Y-%m-%d %H:%M:%S')}", ""]
    return "\n".join(lines)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--uri", default="0")
    ap.add_argument("--minutes", type=float, default=20)
    ap.add_argument("--label", default="webcam-rest",
                    help="tag for the report file name (no IP/URL)")
    ap.add_argument("--synthetic", action="store_true", help="dry run without hardware")
    args = ap.parse_args()
    if re.search(r"://|\d{1,3}([.-]\d{1,3}){3}", args.label):
        ap.error("--label must not contain a URL or an IP address (reports are committed)")
    label = re.sub(r"[^A-Za-z0-9_-]+", "-", args.label).strip("-") or "scene"
    cfg = load_config()
    fps = cfg["camera"]["analytic_fps"]
    win_s = cfg["window"]["seconds"]
    fu, b = cfg["fusion"], cfg["baseline"]
    freeze_min = cfg["faults"]["freeze"]["exact_repeat_ratio_min"]

    src = SyntheticSource() if args.synthetic else OpenCVSource(args.uri)
    worker = CaptureWorker(src, cfg["camera"]["ring_buffer_size"],
                           max_fps=30 if args.synthetic else None)
    runner = ProbeRunner(cfg)
    tracker = IncidentTracker(
        "spike", cfg["faults"], fu["enter_windows"], fu["exit_windows"], fu["cooldown_s"],
        RobustBaseline(b["window"], b["min_samples"], b["mad_epsilon"]))
    worker.start()
    windows: list[dict[str, Any]] = []
    shape = "?"
    stalled = polls = 0
    last_seq = -1
    calibrated = False
    t_start = time.monotonic()
    while time.monotonic() - t_start < args.minutes * 60:
        agg = WindowAggregator("spike", win_s)
        t0 = time.monotonic()
        while time.monotonic() - t0 < win_s:
            time.sleep(1 / fps)
            f = worker.buffer.latest()
            if f is None:
                continue
            polls += 1
            if f.seq == last_seq:
                stalled += 1  # no new frame since the last poll: do not judge the same pixels twice
                continue
            last_seq = f.seq
            if not calibrated:
                runner.calibrate_reference(f)
                shape = f"{f.image.shape[1]}x{f.image.shape[0]}"
                calibrated = True
            agg.add(runner.analyse(f))
        now = time.monotonic() - t_start
        tw = agg.emit(worker.meter.snapshot(), runner._geom_quality)  # frames_analyzed may be 0
        st = tracker.step(tw, now_s=now)
        row = {"t_s": round(now, 1), "frames": tw.frames_analyzed, "state": st.state.value,
               "faults": sorted(map(str, st.faults)),
               "confirmed": [str(f) for f in st.incident.candidate_faults] if st.incident else None,
               **{m: getattr(tw.visual, m) for m in METRICS}}
        windows.append(row)
        if len(windows) % 60 == 0 or row["confirmed"]:
            print(f"t={now:5.0f}s state={row['state']} faults={row['faults']} "
                  f"exact={row['exact_repeat_ratio']} noise_ratio={row['noise_ratio_p50']} "
                  f"sigma_t={row['temporal_sigma_p50']} loop={row['loop_period']}", flush=True)
    health = worker.health()
    worker.stop()
    summ = summarise(windows, freeze_min)
    kind = "synthetic" if args.synthetic else src.kind
    report = render(label, kind, args.minutes, fps, shape, summ, health, stalled, polls,
                    freeze_min)
    out_dir = REPO_ROOT / "spikes"
    out_dir.mkdir(exist_ok=True)
    (out_dir / f"static-scene-{label}.md").write_text(report, encoding="utf-8")
    (out_dir / f"static-scene-{label}.json").write_text(
        json.dumps({"label": label, "source_kind": kind, "frame": shape, "summary": summ,
                    "health": health, "stalled_polls": stalled, "polls": polls,
                    "windows": windows},
                   indent=2) + "\n", encoding="utf-8")
    print(report)
    return int(summ["exit_code"])


if __name__ == "__main__":
    raise SystemExit(main())
