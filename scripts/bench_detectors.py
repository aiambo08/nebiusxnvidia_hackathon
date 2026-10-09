"""Gate F3 recall / precision per detector (SIMULATION): >= 10 seeded runs per fault.

Each run is a clean synthetic scene (`SyntheticSource`: textured desk with an ArUco marker and
Gaussian sensor noise) replayed through the full local detection path
(`benchmarks.replay.replay`: probes -> windows -> baseline -> IncidentTracker) with one fault
from `benchmarks.injectors.faults` injected after a healthy lead-in. Negative controls (clean
scene, legitimate lighting change) are replayed the same way. A run counts as a true positive of
detector D when D is the fault `benchmarks.replay.EXPECTED` maps the injector to and D is
confirmed after onset; any detector confirmed on a run that does not expect it (including every
negative control and any confirmation before onset) is a false positive of that detector.
Only the first confirmation of a run is recorded (the tracker stays CONFIRMED afterwards), so a
wrong detector that appears after a correct confirmation is not counted: precision is optimistic
by construction. Writes a Markdown report; exits 1 if any detector misses the gate.
"""

from __future__ import annotations

import argparse
import subprocess
import time
from collections import defaultdict
from pathlib import Path

import _src_path  # noqa: F401  (adds src/ to sys.path)
import numpy as np

from benchmarks.replay import inject, replay, score
from reliability_agent.capture.sources import SyntheticSource
from reliability_agent.config import load_config

# injector kind -> strengths graded as "strong" (gate wording: strong blur, strong occlusion)
FAULTS: dict[str, list[float]] = {
    "dark": [0.9, 1.0],
    "gaussian_blur": [0.7, 1.0],
    "freeze": [1.0],
    "loop4": [1.0],
    "loop8": [1.0],
    "occlude_opaque": [0.7, 1.0],
    "overexpose": [0.8, 1.0],
}
NEGATIVES: dict[str, list[float]] = {"none": [0.0], "lighting_change": [1.0]}
SIGMAS = (1.0, 2.0, 3.0)
RECALL_MIN, PRECISION_MIN = 0.90, 0.85
GATED = ("blackout", "freeze", "focus_drift", "lens_occlusion")
ROOT = Path(__file__).resolve().parents[1]


def clean_frames(seed: int, sigma: float, n: int) -> list[np.ndarray]:
    src = SyntheticSource(seed=seed, noise_sigma=sigma)
    src.open()
    try:
        return [src.read().image for _ in range(n)]
    finally:
        src.close()


def run(kind: str | None, strength: float, seed: int, sigma: float, cfg: dict, *,
        lead_s: float, fault_s: float) -> dict:
    fps = cfg["camera"]["analytic_fps"]
    n = int((lead_s + fault_s) * fps)
    start = int(lead_s * fps)
    frames = inject(clean_frames(seed, sigma, n), kind, start, n, strength, seed)
    res = replay(frames, fps, cfg)
    out = score(res, kind, start / fps, fps, cfg)
    out.update(seed=seed, sigma=sigma, strength=strength)
    # every detector confirmed on this run, and whether that confirmation is legitimate
    expected = out["expected"]
    pre = res.confirmed_window is not None and out["confirmed_at_s"] < start / fps
    out["false_positives"] = sorted(f for f in res.confirmed_faults
                                    if f != expected or pre or expected is None)
    return out


def aggregate(results: list[dict]) -> dict[str, dict]:
    stats: dict[str, dict] = defaultdict(lambda: {"expected": 0, "tp": 0, "fp": 0, "delays": []})
    for r in results:
        if r["expected"]:
            d = stats[r["expected"]]
            d["expected"] += 1
            if r["passed"]:
                d["tp"] += 1
                d["delays"].append(r["detection_delay_s"])
        for f in r["false_positives"]:
            stats[f]["fp"] += 1
    for d in stats.values():
        d["recall"] = d["tp"] / d["expected"] if d["expected"] else None
        d["precision"] = d["tp"] / (d["tp"] + d["fp"]) if d["tp"] + d["fp"] else None
        d["delay_p50"] = float(np.median(d["delays"])) if d["delays"] else None
    return dict(stats)


def gate_ok(stats: dict[str, dict]) -> bool:
    for name in GATED:
        d = stats.get(name)
        if d is None or d["recall"] is None or d["recall"] < RECALL_MIN:
            return False
    return all(d["precision"] is None or d["precision"] >= PRECISION_MIN for d in stats.values())


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--seeds", type=int, default=4, help="seeds per (fault, strength, sigma)")
    ap.add_argument("--lead-seconds", type=float, default=30.0)
    ap.add_argument("--fault-seconds", type=float, default=30.0)
    ap.add_argument("--out", default="docs/evidence/f3/detectors.md")
    args = ap.parse_args()
    cfg = load_config(env=False)
    results: list[dict] = []
    t_all = time.perf_counter()
    for kind, strengths in {**FAULTS, **NEGATIVES}.items():
        for strength in strengths:
            for sigma in SIGMAS:
                for seed in range(args.seeds):
                    t0 = time.perf_counter()
                    r = run(None if kind == "none" else kind, strength, seed, sigma, cfg,
                            lead_s=args.lead_seconds, fault_s=args.fault_seconds)
                    results.append(r)
                    print(f"{kind} s={strength:g} sigma={sigma:g} seed={seed}: "
                          f"confirmed={r['confirmed_faults']} delay={r['detection_delay_s']} "
                          f"fp={r['false_positives']} {'PASS' if r['passed'] else 'FAIL'} "
                          f"({time.perf_counter() - t0:.1f}s)")
    stats = aggregate(results)
    ok = gate_ok(stats)
    rev = subprocess.run(["git", "rev-parse", "--short", "HEAD"], capture_output=True,
                         text=True, check=False).stdout.strip() or "unknown"
    fps = cfg["camera"]["analytic_fps"]
    lines = [
        "# Detector recall / precision (Gate F3) — SIMULATION",
        "",
        f"`SyntheticSource` 640x480 textured scene with ArUco marker, sensor noise sigma "
        f"{', '.join(f'{s:g}' for s in SIGMAS)}, {fps} analytic FPS, {args.lead_seconds:g} s "
        f"healthy lead-in then {args.fault_seconds:g} s of one injected fault "
        "(`benchmarks.injectors.faults`), full local path (`benchmarks.replay.replay`). "
        f"{args.seeds} seeds per (fault, strength, sigma). Negative controls: clean scene and "
        "legitimate lighting change. TP = expected detector confirmed after onset; FP = any "
        "detector confirmed where not expected (negatives, other faults, or before onset). "
        f"Gate: recall >= {RECALL_MIN:g} for blackout, freeze, strong blur (focus_drift) and "
        f"strong occlusion (lens_occlusion); precision >= {PRECISION_MIN:g} per detector.",
        "",
        "| detector | expected runs | TP | FN | FP | recall | precision | delay p50 s | gate |",
        "|---|---|---|---|---|---|---|---|---|",
    ]
    for name in sorted(stats):
        d = stats[name]
        fmt = lambda v: "-" if v is None else f"{v:.2f}"  # noqa: E731
        gated = name in GATED
        rec_ok = d["recall"] is not None and d["recall"] >= RECALL_MIN
        prec_ok = d["precision"] is None or d["precision"] >= PRECISION_MIN
        verdict = "PASS" if (rec_ok or not gated) and prec_ok else "FAIL"
        verdict += "" if gated else " (not gated)"
        lines.append(f"| {name} | {d['expected']} | {d['tp']} | {d['expected'] - d['tp']} | "
                     f"{d['fp']} | {fmt(d['recall'])} | {fmt(d['precision'])} | "
                     f"{fmt(d['delay_p50'])} | {verdict} |")
    lines += ["", "## Runs", "",
              "| injector | strength | sigma | seed | confirmed | delay s | false positives "
              "| result |", "|---|---|---|---|---|---|---|---|"]
    for r in results:
        lines.append(f"| {r['kind']} | {r['strength']:g} | {r['sigma']:g} | {r['seed']} | "
                     f"{', '.join(r['confirmed_faults']) or '-'} | "
                     f"{'-' if r['detection_delay_s'] is None else r['detection_delay_s']} | "
                     f"{', '.join(r['false_positives']) or '-'} | "
                     f"{'PASS' if r['passed'] else 'FAIL'} |")
    lines += ["", f"commit: {rev} | runs: {len(results)} | wall time: "
              f"{time.perf_counter() - t_all:.0f} s | generated: "
              f"{time.strftime('%Y-%m-%d %H:%M:%S')} | overall: {'PASS' if ok else 'FAIL'}", ""]
    out = Path(args.out)
    if not out.is_absolute():
        out = ROOT / out
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("\n".join(lines))
    print(f"wrote {out} overall={'PASS' if ok else 'FAIL'}")
    if not ok:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
