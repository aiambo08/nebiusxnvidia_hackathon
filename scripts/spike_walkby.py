"""Gate F3 spike: person walk-by trials for `fov_shift` false positives (REAL HARDWARE).

    python scripts/spike_walkby.py --uri 0 --label webcam-walkby
    python scripts/spike_walkby.py --uri $env:RA_TEST_RTSP --label rtsp-walkby

Gate box: 0 "camera moved" false positives across >= 20 person-walk-by trials. Same detection
path as `spike_static_scene.py` (probes -> windows -> baseline -> IncidentTracker) on a camera
that stays fixed until the final BUMP. Phases, each announced on the console with a beep:

0. START (`--start-delay`, 10 s): step out of the frame before the capture opens.
1. CALIBRATE (`--calibrate-s`, 30 s, timed from the first frame, so an RTSP handshake does not
   eat it): nobody in frame. The geometry reference is re-taken at its end from a still scene
   (the last STILL_WINDOWS windows below MOTION_MSE_MIN), so a person in the first frame is not
   the reference; if the scene is not still, the run stops INCONCLUSIVE.
2. Per trial (`--trials`, 22): WALK (`--walk-s`, 8 s) cross the whole frame once at a normal
   pace, then REST (`--rest-s`, 12 s) out of the frame.
3. BUMP (`--bump-s`, 10 s; 0 skips it): tilt or turn the camera a little and leave it. Positive
   control: it must raise `fov_shift`, otherwise the run could not have seen a real move.

A window is *armed* when the `fov_shift` rule could fire on it: geometry quality `ok` and
`homography_inlier_ratio` >= the rule's `inlier_ratio_min` (on a plain wall `equalizeHist`
turns noise into keypoints, so quality alone says `ok` while no shift can ever be detected).
Every window is logged with phase, trial, faults, `armed`, the geometry probe and
`temporal_mse_p50` / `occluded_cell_ratio`. Reports (never the URI, `commit` stamped, never
overwritten without `--overwrite`; labels as in `spike_static_scene.py`):

- spikes/walkby-<label>.md   summary with one row per trial (commit it as evidence)
- spikes/walkby-<label>.json per-window series + worker `health()`

Verdict: FAIL, exit 1, on any `fov_shift` window in a WALK or REST phase, confirmed or not, on a
valid run (still reference, armed REST, BUMP detected; otherwise those windows are findings).
INCONCLUSIVE, exit 3, if fewer than `--min-observed` (20) trials were observed (WALK reaches
`temporal_mse_p50` >= MOTION_MSE_MIN and >= 80 % of its windows are armed), if < 80 % of the
REST windows with frames are armed, if the BUMP raised no `fov_shift`, or if CALIBRATE never got
a still reference. PASS, exit 0, otherwise. Other faults (e.g. `lens_occlusion` while a person is
close) are findings. Limit: "observed" means a large change during WALK; a flickering light with
nobody walking would also count. FFmpeg may print `tcp://<ip>:<port>` on stderr.
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
STILL_WINDOWS = 5  # end of CALIBRATE that must be still before the reference is re-taken
WALK_ARMED_MIN = 0.8  # share of a WALK's windows that must be armed
REST_ARMED_MIN = 0.8  # share of REST windows with frames that must be armed
HANDSHAKE_MAX_S = 30.0
VISUAL = ("temporal_mse_p50", "occluded_cell_ratio", "brightness_p50")
GEOMETRY = ("translation_px", "rotation_deg", "homography_inlier_ratio", "match_count",
            "quality")
REFERENCE = {"ok": "re-taken at the end of CALIBRATE on a still scene",
             "no_frame": f"no frame within {HANDSHAKE_MAX_S:g} s",
             "not_still": "the scene was not still at the end of CALIBRATE",
             "no_features": "too few features in the empty scene for a geometry reference"}


class WalkBySource(SyntheticSource):
    """Dry-run source: a still scene (the base class's moving ball is held in place) that a
    dark person-sized box crosses while `walking` is set, or while fewer than `walk_until_seq`
    frames were produced (someone in front at start-up)."""

    walking = False
    walk_until_seq = 0

    def _render(self) -> np.ndarray:
        seq, self._seq = self._seq, 0
        try:
            img = super()._render()
        finally:
            self._seq = seq
        if self.walking or self._seq < self.walk_until_seq:
            x = int((self._seq % 40) / 40 * (self.w + 160)) - 80
            cv2.rectangle(img, (x, 40), (x + 120, self.h - 10), (25, 25, 25), -1)
        return img


def schedule(trials: int, calibrate_s: float, walk_s: float, rest_s: float,
             bump_s: float = 0.0) -> list[tuple[str, int, float]]:
    out = [("calibrate", 0, calibrate_s)]
    for k in range(1, trials + 1):
        out += [("walk", k, walk_s), ("rest", k, rest_s)]
    return out + ([("bump", 0, bump_s)] if bump_s > 0 else [])


def is_armed(geometry: dict[str, Any], inlier_min: float) -> bool:
    r = geometry.get("homography_inlier_ratio")
    return geometry.get("quality") == "ok" and r is not None and r >= inlier_min


def _r(v: float | None) -> float | None:
    return None if v is None else round(float(v), 3)


def _max(rows: list[dict[str, Any]], key: str) -> float | None:
    return _r(max((w[key] for w in rows if w[key] is not None), default=None))


def summarise(windows: list[dict[str, Any]], trials: int, *, min_observed: int | None = None,
              bump: bool = False, reference: str = "ok") -> dict[str, Any]:
    need = trials if min_observed is None else min_observed
    per_trial = []
    for k in range(1, trials + 1):
        walk = [w for w in windows if w["trial"] == k and w["phase"] == "walk"]
        mine = [w for w in windows if w["trial"] == k]
        mse = [w["temporal_mse_p50"] for w in walk if w["temporal_mse_p50"] is not None]
        armed = sum(w["armed"] for w in walk)
        per_trial.append({
            "trial": k, "walk_windows": len(walk), "walk_armed": armed,
            "walk_mse_max": _r(max(mse)) if mse else None,
            "observed": bool(walk) and bool(mse) and max(mse) >= MOTION_MSE_MIN
            and armed >= WALK_ARMED_MIN * len(walk),
            "fov_shift_windows": sum("fov_shift" in w["faults"] for w in mine),
            "inlier_max": _max(mine, "homography_inlier_ratio"),
            "translation_px_max_armed": _max([w for w in mine if w["armed"]], "translation_px"),
        })
    judged = [w for w in windows if w["phase"] in ("walk", "rest")]
    rest = [w for w in windows if w["phase"] == "rest" and w["frames"] > 0]
    rest_armed = sum(w["armed"] for w in rest)
    fov = [w for w in judged if "fov_shift" in w["faults"]]
    bump_rows = [w for w in windows if w["phase"] == "bump"]
    bump_hit = any("fov_shift" in w["faults"] for w in bump_rows)
    findings: dict[str, int] = {}
    for w in judged:
        for f in w["faults"]:
            if f != "fov_shift":
                findings[f] = findings.get(f, 0) + 1
    observed = sum(t["observed"] for t in per_trial)
    out: dict[str, Any] = {
        "trials": trials, "min_observed": need, "observed_trials": observed,
        "reference": reference, "windows": len(windows),
        "valid_windows": sum(w["frames"] > 0 for w in windows),
        "fov_shift_windows": len(fov),
        "fov_shift_confirmed": sum("fov_shift" in (w["confirmed"] or []) for w in judged),
        "calibrate_fov_shift_windows": sum("fov_shift" in w["faults"] for w in windows
                                           if w["phase"] == "calibrate"),
        "rest_armed_windows": rest_armed, "rest_windows": len(rest),
        "bump": ({"windows": len(bump_rows), "fov_shift_detected": bump_hit} if bump else None),
        "other_fault_windows": findings, "per_trial": per_trial,
    }
    invalid = []  # the run itself shows its reference or geometry cannot be trusted
    if reference != "ok":
        invalid.append(f"no geometry reference: {REFERENCE.get(reference, reference)}")
    if not rest or rest_armed < REST_ARMED_MIN * len(rest):
        invalid.append(f"armed in {rest_armed}/{len(rest)} REST windows (needs >= "
                       f"{REST_ARMED_MIN:.0%}: point the camera at a textured scene and keep "
                       "out of the frame during CALIBRATE)")
    if bump and not bump_hit:
        invalid.append("the BUMP raised no `fov_shift`: the run could not see a real camera "
                       "move")
    why = list(invalid)
    if observed < need:
        why.append(f"{observed}/{need} trials observed (WALK temporal_mse_p50 >= "
                   f"{MOTION_MSE_MIN:g} and >= {WALK_ARMED_MIN:.0%} of its windows armed)")
    if fov:
        w = fov[0]
        where = (f"`fov_shift` in {len(fov)} window(s), first at {w['t_s']:.0f} s (trial "
                 f"{w['trial']} {w['phase']}, translation {_r(w['translation_px'])} px)")
        if invalid:
            why.append(where + " — finding only, the run is not valid")
    if fov and not invalid:
        out["verdict"] = f"FAIL: {where}; the camera was fixed"
        out["exit_code"] = 1
    elif why:
        out["verdict"] = "INCONCLUSIVE: " + "; ".join(why)
        out["exit_code"] = 3
    else:
        out["verdict"] = (f"PASS: 0 `fov_shift` windows across {observed} walk-by trials"
                          + (", BUMP detected" if bump else ""))
        out["exit_code"] = 0
    return out


def render(label: str, kind: str, shape: str, sched: dict[str, float],
           summ: dict[str, Any], health: dict[str, Any], commit: str) -> str:
    tr = health.get("transport", {})
    title = "REAL HARDWARE" if kind != "synthetic" else "SIMULATION (dry run)"
    bump = summ["bump"]
    lines = [
        f"# Walk-by spike `{label}` (Gate F3, `fov_shift`) — {title}", "",
        f"- source: {kind} | frame: {shape} | schedule (s): " + ", ".join(
            f"{k} {v:g}" for k, v in sched.items()),
        f"- geometry reference: {REFERENCE.get(summ['reference'], summ['reference'])}",
        f"- trials observed: {summ['observed_trials']}/{summ['trials']} (needed "
        f"{summ['min_observed']}) | windows: {summ['windows']}, valid: {summ['valid_windows']}",
        f"- fov_shift windows in WALK/REST: {summ['fov_shift_windows']} (confirmed: "
        f"{summ['fov_shift_confirmed']}) | in CALIBRATE (not judged): "
        f"{summ['calibrate_fov_shift_windows']} | armed REST windows: "
        f"{summ['rest_armed_windows']}/{summ['rest_windows']}",
        "- BUMP (positive control): " + (
            "skipped" if bump is None else
            f"fov_shift {'detected' if bump['fov_shift_detected'] else 'NOT detected'} "
            f"in {bump['windows']} windows"),
        f"- other faults in WALK/REST (windows, findings only): "
        f"{summ['other_fault_windows'] or 'none'}",
        f"- capture fps: {tr.get('capture_fps')}, decode errors: {tr.get('decode_errors')}, "
        f"reconnects: {tr.get('reconnect_count')}, dropped: {tr.get('dropped_frames')}",
        f"- result: {summ['verdict']}", "",
        "| trial | walk temporal_mse_p50 max | walk windows armed | observed | "
        "fov_shift windows | inlier max | translation_px max (armed) |",
        "|---|---|---|---|---|---|---|",
    ]
    lines += [f"| {t['trial']} | {t['walk_mse_max']} | {t['walk_armed']}/{t['walk_windows']} | "
              f"{'yes' if t['observed'] else 'no'} | {t['fov_shift_windows']} | "
              f"{t['inlier_max']} | {t['translation_px_max_armed']} |"
              for t in summ["per_trial"]]
    lines += ["", f"commit: {commit} | generated: {time.strftime('%Y-%m-%d %H:%M:%S')}", ""]
    return "\n".join(lines)


CUES = {"calibrate": ("CALIBRATE {d:g} s: leave the frame (do not sit in front reading this), "
                      "do not touch the camera", 1),
        "walk": ("[trial {k}/{n}] WALK now: cross the whole frame once ({d:g} s)", 2),
        "rest": ("[trial {k}/{n}] REST: stay out of the frame ({d:g} s)", 1),
        "bump": ("BUMP now: tilt or turn the camera a little and leave it ({d:g} s)", 3)}


def beep(n: int) -> None:
    try:
        import winsound  # Windows: audible even where the terminal bell is muted

        for _ in range(n):
            winsound.Beep(1000, 150)
    except (ImportError, RuntimeError):
        print("\a" * n, end="", flush=True)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--uri", default="0")
    ap.add_argument("--trials", type=int, default=22)
    ap.add_argument("--min-observed", type=int, default=20,
                    help="trials that must be observed (spare trials absorb a missed cue)")
    ap.add_argument("--label", default="walkby", help="tag for the report file name (no IP/URL)")
    ap.add_argument("--start-delay", type=float, default=10.0,
                    help="seconds to step out of the frame before the capture opens")
    ap.add_argument("--calibrate-s", type=float, default=30.0)
    ap.add_argument("--walk-s", type=float, default=8.0)
    ap.add_argument("--rest-s", type=float, default=12.0)
    ap.add_argument("--bump-s", type=float, default=10.0, help="final camera move; 0 skips it")
    ap.add_argument("--synthetic", action="store_true", help="dry run without hardware")
    ap.add_argument("--synthetic-bump", action="store_true",
                    help="dry run: shift the view during trial 1 (the run must FAIL)")
    ap.add_argument("--overwrite", action="store_true",
                    help="replace an existing report with the same label")
    args = ap.parse_args()
    if not 1 <= args.min_observed <= args.trials:
        ap.error("need 1 <= --min-observed <= --trials")
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
    inlier_min = cfg["faults"]["fov_shift"]["inlier_ratio_min"]
    fu, b = cfg["fusion"], cfg["baseline"]

    if args.start_delay > 0:
        print(f"START in {args.start_delay:g} s: step out of the frame now", flush=True)
        beep(1)
        time.sleep(args.start_delay)
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
    state: dict[str, Any] = {"shape": "?", "last_seq": -1, "frame": None}
    t_start = time.monotonic()

    def window(phase: str, trial: int) -> dict[str, Any]:
        agg = WindowAggregator("spike", win_s)
        t0 = time.monotonic()
        while time.monotonic() - t0 < win_s:
            time.sleep(1 / fps)
            f = worker.buffer.latest()
            if f is None or f.seq == state["last_seq"]:
                continue  # nothing new: never judge the same pixels twice
            state["last_seq"] = f.seq
            if state["frame"] is None:
                runner.calibrate_reference(f)
                state["shape"] = f"{f.image.shape[1]}x{f.image.shape[0]}"
            state["frame"] = f
            agg.add(runner.analyse(f))
        now = round(time.monotonic() - t_start, 1)
        tw = agg.emit(worker.meter.snapshot(), runner._geom_quality)
        base = {"t_s": now, "phase": phase, "trial": trial}
        if state["frame"] is None:  # handshake: no frame yet, keep the tracker out of it
            row = {**base, "frames": 0, "state": "handshake", "faults": [], "confirmed": None,
                   "armed": False, **{m: None for m in VISUAL + GEOMETRY}}
        else:
            st = tracker.step(tw, now_s=now)
            geo = {g: getattr(tw.geometry, g) for g in GEOMETRY}
            row = {**base, "frames": tw.frames_analyzed, "state": st.state.value,
                   "faults": sorted(map(str, st.faults)),
                   "confirmed": ([str(x) for x in st.incident.candidate_faults]
                                 if st.incident else None),
                   "armed": tw.frames_analyzed > 0 and is_armed(geo, inlier_min),
                   **{m: getattr(tw.visual, m) for m in VISUAL}, **geo}
        windows.append(row)
        if "fov_shift" in row["faults"] or row["confirmed"]:
            print(f"t={now:5.0f}s {phase} {trial} faults={row['faults']} "
                  f"confirmed={row['confirmed']} translation_px={row['translation_px']}",
                  flush=True)
        return row

    while state["frame"] is None and time.monotonic() - t_start < HANDSHAKE_MAX_S:
        window("handshake", 0)
    reference = "no_frame" if state["frame"] is None else "ok"
    plan = schedule(args.trials, args.calibrate_s, args.walk_s, args.rest_s, args.bump_s)
    for phase, trial, dur in plan if reference == "ok" else []:
        text, beeps = CUES[phase]
        print(text.format(k=trial, n=args.trials, d=dur), flush=True)
        beep(beeps)
        if isinstance(src, WalkBySource):
            src.walking = phase == "walk"
            bumped = phase == "bump" or (args.synthetic_bump and trial == 1)
            src.set_fault("shift" if bumped else None)
        rows = [window(phase, trial) for _ in range(max(1, round(dur / win_s)))]
        if phase == "calibrate":
            tail = rows[-STILL_WINDOWS:]
            still = len(tail) == STILL_WINDOWS and all(
                w["frames"] > 0 and w["temporal_mse_p50"] is not None
                and w["temporal_mse_p50"] < MOTION_MSE_MIN for w in tail)
            if not still:
                reference = "not_still"
            elif not runner.set_geometry_reference(state["frame"]):
                reference = "no_features"
            if reference != "ok":
                print(f"stopping: {REFERENCE[reference]}", flush=True)
                break
    health = worker.health()
    worker.stop()
    summ = summarise(windows, args.trials, min_observed=args.min_observed,
                     bump=args.bump_s > 0, reference=reference)
    kind = "synthetic" if synthetic else src.kind
    sched = {"start_delay": args.start_delay, "calibrate": args.calibrate_s,
             "walk": args.walk_s, "rest": args.rest_s, "bump": args.bump_s}
    report = render(label, kind, state["shape"], sched, summ, health, commit)
    out_dir.mkdir(exist_ok=True)
    (out_dir / f"walkby-{label}.md").write_text(report, encoding="utf-8")
    (out_dir / f"walkby-{label}.json").write_text(
        json.dumps({"label": label, "source_kind": kind, "frame": state["shape"],
                    "commit": commit, "schedule_s": sched, "summary": summ, "health": health,
                    "windows": windows}, indent=2) + "\n", encoding="utf-8")
    print(report)
    return int(summ["exit_code"])


if __name__ == "__main__":
    raise SystemExit(main())
