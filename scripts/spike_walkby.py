"""Gate F3 spike: person walk-by trials for `fov_shift` false positives (REAL HARDWARE).

    python scripts/spike_walkby.py --uri 0 --trials 20 --label webcam-walkby
    python scripts/spike_walkby.py --uri $env:RA_TEST_RTSP --trials 20 --label rtsp-walkby

Gate box: 0 "camera moved" false positives across >= 20 person-walk-by trials. Same detection
path as `spike_static_scene.py` (probes -> windows -> baseline -> IncidentTracker) on a camera
that is fixed for the whole run. The console prints a cue (with a terminal bell) per phase:

1. CALIBRATE (`--calibrate-s`, 30 s): nobody in frame. The geometry reference is the first
   frame and occlusion calibrates at rest (ADR-008), so the scene must be empty and still.
2. Per trial: WALK (`--walk-s`, 8 s): cross the whole frame once at a normal pace; then REST
   (`--rest-s`, 12 s): stay out of the frame.

Every analytic window is logged with its phase and trial, the tracker faults, the geometry
probe (`translation_px`, `rotation_deg`, `homography_inlier_ratio`, `match_count`, `quality`)
and `temporal_mse_p50` / `occluded_cell_ratio` as evidence that someone crossed. Reports:

- spikes/walkby-<label>.md   summary with one row per trial (commit it as evidence)
- spikes/walkby-<label>.json per-window series + worker `health()` (never the URI)

Verdict: FAIL, exit 1, if any window of the run reports `fov_shift`, confirmed or not (the
camera never moves, so every such window is a false positive). INCONCLUSIVE, exit 3, if fewer
than `--trials` trials were observed (a trial counts when its WALK phase reaches
`temporal_mse_p50` >= MOTION_MSE_MIN and >= 50 % of its windows carry frames), or if the
geometry probe was not `ok` in >= 80 % of the empty-scene windows (a low-texture scene cannot
produce `fov_shift` at all, so a PASS there would prove nothing). PASS, exit 0, otherwise.
Other faults (e.g. `lens_occlusion` while a person is close) are reported as findings only.
Labels follow `spike_static_scene.py`: no URL, IPv4 address or path; an existing report is
never overwritten without `--overwrite`. FFmpeg may print `tcp://<ip>:<port>` on stderr.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from typing import Any

import _src_path  # noqa: F401  (adds src/ to sys.path)
import cv2
import numpy as np
from spike_static_scene import code_revision, safe_label

from reliability_agent.baselines.robust import RobustBaseline
from reliability_agent.capture import CaptureWorker, OpenCVSource, SyntheticSource
from reliability_agent.config import REPO_ROOT, load_config
from reliability_agent.incidents.fusion import IncidentTracker
from reliability_agent.probes.runner import ProbeRunner, WindowAggregator

MOTION_MSE_MIN = 10.0  # walk evidence; the owner's cameras at rest stay below 0.4 (p95)
TRIAL_VALID_MIN = 0.5  # share of a trial's windows that must carry frames
GEOMETRY_OK_MIN = 0.8  # share of empty-scene windows with a usable geometry probe
VISUAL = ("temporal_mse_p50", "occluded_cell_ratio", "brightness_p50")
GEOMETRY = ("translation_px", "rotation_deg", "homography_inlier_ratio", "match_count",
            "quality")


class WalkBySource(SyntheticSource):
    """Dry-run source: a dark person-sized box crosses the frame while `walking` is set."""

    walking = False

    def _render(self) -> np.ndarray:
        img = super()._render()
        if self.walking:
            x = int((self._seq % 40) / 40 * (self.w + 160)) - 80
            cv2.rectangle(img, (x, 40), (x + 120, self.h - 10), (25, 25, 25), -1)
        return img


def schedule(trials: int, calibrate_s: float, walk_s: float,
             rest_s: float) -> list[tuple[str, int, float]]:
    out = [("calibrate", 0, calibrate_s)]
    for k in range(1, trials + 1):
        out += [("walk", k, walk_s), ("rest", k, rest_s)]
    return out


def _r(v: float | None) -> float | None:
    return None if v is None else round(float(v), 3)


def summarise(windows: list[dict[str, Any]], trials: int) -> dict[str, Any]:
    per_trial = []
    for k in range(1, trials + 1):
        mine = [w for w in windows if w["trial"] == k]
        mse = [w["temporal_mse_p50"] for w in mine
               if w["phase"] == "walk" and w["temporal_mse_p50"] is not None]
        valid = sum(w["frames"] > 0 for w in mine)
        per_trial.append({
            "trial": k, "windows": len(mine), "valid_windows": valid,
            "walk_mse_max": _r(max(mse)) if mse else None,
            "observed": bool(mine) and bool(mse) and max(mse) >= MOTION_MSE_MIN
            and valid >= TRIAL_VALID_MIN * len(mine),
            "fov_shift_windows": sum("fov_shift" in w["faults"] for w in mine),
            "translation_px_max": _r(max((w["translation_px"] for w in mine
                                          if w["translation_px"] is not None), default=None)),
        })
    empty = [w for w in windows if w["phase"] != "walk" and w["frames"] > 0]
    geom_ok = sum(w["quality"] == "ok" for w in empty)
    fov = [w for w in windows if "fov_shift" in w["faults"]]
    findings: dict[str, int] = {}
    for w in windows:
        for f in w["faults"]:
            if f != "fov_shift":
                findings[f] = findings.get(f, 0) + 1
    observed = sum(t["observed"] for t in per_trial)
    out: dict[str, Any] = {
        "trials": trials, "observed_trials": observed, "windows": len(windows),
        "valid_windows": sum(w["frames"] > 0 for w in windows),
        "fov_shift_windows": len(fov),
        "fov_shift_confirmed": sum("fov_shift" in (w["confirmed"] or []) for w in windows),
        "geometry_ok_empty_windows": geom_ok, "empty_windows": len(empty),
        "other_fault_windows": findings, "per_trial": per_trial,
    }
    if fov:
        w = fov[0]
        where = f"trial {w['trial']} {w['phase']}" if w["trial"] else w["phase"]
        out["verdict"] = (f"FAIL: `fov_shift` in {len(fov)} window(s), first at "
                          f"{w['t_s']:.0f} s ({where}, translation "
                          f"{_r(w['translation_px'])} px); the camera was fixed")
        out["exit_code"] = 1
    elif observed < trials or not empty or geom_ok < GEOMETRY_OK_MIN * len(empty):
        out["verdict"] = (f"INCONCLUSIVE: {observed}/{trials} trials observed (walk "
                          f"temporal_mse_p50 >= {MOTION_MSE_MIN:g} and >= "
                          f"{TRIAL_VALID_MIN:.0%} windows with frames); geometry `ok` in "
                          f"{geom_ok}/{len(empty)} empty-scene windows (needs "
                          f">= {GEOMETRY_OK_MIN:.0%}: point the camera at a textured scene)")
        out["exit_code"] = 3
    else:
        out["verdict"] = f"PASS: 0 `fov_shift` windows across {observed} walk-by trials"
        out["exit_code"] = 0
    return out


def render(label: str, kind: str, shape: str, sched: tuple[float, float, float],
           summ: dict[str, Any], health: dict[str, Any], commit: str) -> str:
    tr = health.get("transport", {})
    title = "REAL HARDWARE" if kind != "synthetic" else "SIMULATION (dry run)"
    lines = [
        f"# Walk-by spike `{label}` (Gate F3, `fov_shift`) — {title}", "",
        f"- source: {kind} | frame: {shape} | calibrate {sched[0]:g} s, then per trial "
        f"walk {sched[1]:g} s + rest {sched[2]:g} s",
        f"- trials observed: {summ['observed_trials']}/{summ['trials']} | windows: "
        f"{summ['windows']}, valid: {summ['valid_windows']}",
        f"- fov_shift windows: {summ['fov_shift_windows']} (confirmed: "
        f"{summ['fov_shift_confirmed']}) | geometry ok in empty scene: "
        f"{summ['geometry_ok_empty_windows']}/{summ['empty_windows']}",
        f"- other faults (windows, findings only): {summ['other_fault_windows'] or 'none'}",
        f"- capture fps: {tr.get('capture_fps')}, decode errors: {tr.get('decode_errors')}, "
        f"reconnects: {tr.get('reconnect_count')}, dropped: {tr.get('dropped_frames')}",
        f"- result: {summ['verdict']}", "",
        "| trial | walk temporal_mse_p50 max | windows with frames | observed | "
        "fov_shift windows | translation_px max |",
        "|---|---|---|---|---|---|",
    ]
    lines += [f"| {t['trial']} | {t['walk_mse_max']} | {t['valid_windows']}/{t['windows']} | "
              f"{'yes' if t['observed'] else 'no'} | {t['fov_shift_windows']} | "
              f"{t['translation_px_max']} |" for t in summ["per_trial"]]
    lines += ["", f"commit: {commit} | generated: {time.strftime('%Y-%m-%d %H:%M:%S')}", ""]
    return "\n".join(lines)


CUES = {"calibrate": "CALIBRATE {d:g} s: stay out of the frame, do not touch the camera",
        "walk": "[trial {k}/{n}] WALK now: cross the whole frame once ({d:g} s)",
        "rest": "[trial {k}/{n}] REST: stay out of the frame ({d:g} s)"}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--uri", default="0")
    ap.add_argument("--trials", type=int, default=20)
    ap.add_argument("--label", default="walkby", help="tag for the report file name (no IP/URL)")
    ap.add_argument("--calibrate-s", type=float, default=30.0)
    ap.add_argument("--walk-s", type=float, default=8.0)
    ap.add_argument("--rest-s", type=float, default=12.0)
    ap.add_argument("--synthetic", action="store_true", help="dry run without hardware")
    ap.add_argument("--synthetic-bump", action="store_true",
                    help="dry run: shift the view during trial 1 (the run must FAIL)")
    ap.add_argument("--overwrite", action="store_true",
                    help="replace an existing report with the same label")
    args = ap.parse_args()
    if args.trials < 1:
        ap.error("--trials must be >= 1")
    label = safe_label(ap, args.label, "walkby")
    out_dir = REPO_ROOT / "spikes"
    existing = [p for p in (out_dir / f"walkby-{label}.md", out_dir / f"walkby-{label}.json")
                if p.exists()]
    if existing and not args.overwrite:
        ap.error(f"spikes/{existing[0].name} already exists: pick a new --label for this run "
                 "(or pass --overwrite to replace it)")
    commit = code_revision()
    if commit == "unknown" or commit.endswith("+dirty"):
        print(f"warning: code revision is {commit!r}: run from a clean git checkout of the repo "
              "so the report is traceable", file=sys.stderr, flush=True)
    cfg = load_config()
    fps = cfg["camera"]["analytic_fps"]
    win_s = cfg["window"]["seconds"]
    fu, b = cfg["fusion"], cfg["baseline"]

    synthetic = args.synthetic or args.synthetic_bump
    src = WalkBySource() if synthetic else OpenCVSource(args.uri)
    worker = CaptureWorker(src, cfg["camera"]["ring_buffer_size"],
                           max_fps=30 if synthetic else None)
    runner = ProbeRunner(cfg)
    tracker = IncidentTracker(
        "spike", cfg["faults"], fu["enter_windows"], fu["exit_windows"], fu["cooldown_s"],
        RobustBaseline(b["window"], b["min_samples"], b["mad_epsilon"]))
    worker.start()
    windows: list[dict[str, Any]] = []
    shape = "?"
    last_seq = -1
    calibrated = False
    t_start = time.monotonic()
    for phase, trial, dur in schedule(args.trials, args.calibrate_s, args.walk_s, args.rest_s):
        print("\a" + CUES[phase].format(k=trial, n=args.trials, d=dur), flush=True)
        if isinstance(src, WalkBySource):
            src.walking = phase == "walk"
            src.set_fault("shift" if args.synthetic_bump and trial == 1 else None)
        for _ in range(max(1, round(dur / win_s))):
            agg = WindowAggregator("spike", win_s)
            t0 = time.monotonic()
            while time.monotonic() - t0 < win_s:
                time.sleep(1 / fps)
                f = worker.buffer.latest()
                if f is None or f.seq == last_seq:
                    continue  # nothing new: never judge the same pixels twice
                last_seq = f.seq
                if not calibrated:
                    runner.calibrate_reference(f)
                    shape = f"{f.image.shape[1]}x{f.image.shape[0]}"
                    calibrated = True
                agg.add(runner.analyse(f))
            now = round(time.monotonic() - t_start, 1)
            tw = agg.emit(worker.meter.snapshot(), runner._geom_quality)
            base = {"t_s": now, "phase": phase, "trial": trial}
            if not calibrated:  # handshake: no frame yet, keep the tracker out of it
                windows.append({**base, "frames": 0, "state": "handshake", "faults": [],
                                "confirmed": None, **{m: None for m in VISUAL + GEOMETRY}})
                continue
            st = tracker.step(tw, now_s=now)
            row = {**base, "frames": tw.frames_analyzed, "state": st.state.value,
                   "faults": sorted(map(str, st.faults)),
                   "confirmed": ([str(x) for x in st.incident.candidate_faults]
                                 if st.incident else None),
                   **{m: getattr(tw.visual, m) for m in VISUAL},
                   **{g: getattr(tw.geometry, g) for g in GEOMETRY}}
            windows.append(row)
            if "fov_shift" in row["faults"] or row["confirmed"]:
                print(f"t={now:5.0f}s {phase} {trial} faults={row['faults']} "
                      f"confirmed={row['confirmed']} translation_px={row['translation_px']}",
                      flush=True)
    health = worker.health()
    worker.stop()
    summ = summarise(windows, args.trials)
    kind = "synthetic" if synthetic else src.kind
    report = render(label, kind, shape, (args.calibrate_s, args.walk_s, args.rest_s), summ,
                    health, commit)
    out_dir.mkdir(exist_ok=True)
    (out_dir / f"walkby-{label}.md").write_text(report, encoding="utf-8")
    (out_dir / f"walkby-{label}.json").write_text(
        json.dumps({"label": label, "source_kind": kind, "frame": shape, "commit": commit,
                    "schedule_s": {"calibrate": args.calibrate_s, "walk": args.walk_s,
                                   "rest": args.rest_s},
                    "summary": summ, "health": health, "windows": windows},
                   indent=2) + "\n", encoding="utf-8")
    print(report)
    return int(summ["exit_code"])


if __name__ == "__main__":
    raise SystemExit(main())
