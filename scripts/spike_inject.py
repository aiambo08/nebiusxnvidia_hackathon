"""F1 spike: inject blur / darkness / freeze into a REAL clip and check local detection.

The clip is read through the same `CameraSource` (`OpenCVSource`) used for webcam and RTSP.
Faults are SIMULATION (seeded software transforms) on top of a REAL HARDWARE recording.
No network, no Nemotron calls. Writes one manifest per run so `benchmarks.make_degraded` can
regenerate each degraded clip byte-for-byte from the same source.

    python scripts/spike_inject.py --clip benchmarks/data/s001_clean.avi --session s001
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

import _src_path  # noqa: F401  (adds src/ to sys.path)
import cv2
import yaml
from record_clip import sha256

from benchmarks.replay import EXPECTED, inject, replay, score
from reliability_agent.capture import OpenCVSource
from reliability_agent.config import load_config

REPO_ROOT = Path(__file__).resolve().parents[1]

STRENGTH = {"dark": 0.95, "gaussian_blur": 0.8, "freeze": 1.0}


def clip_frames(path: str):
    src = OpenCVSource(path)
    src.open()
    try:
        while (f := src.read()) is not None:
            yield f.image
    finally:
        src.close()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--clip", required=True)
    ap.add_argument("--session", default="s001")
    ap.add_argument("--start-s", type=float, default=40.0)
    ap.add_argument("--end-s", type=float, default=70.0)
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--source-label", default="REAL HARDWARE")
    args = ap.parse_args()

    clip = Path(args.clip)
    cap = cv2.VideoCapture(str(clip))
    fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
    nframes = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    size = [int(cap.get(cv2.CAP_PROP_FRAME_WIDTH)), int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))]
    cap.release()
    if nframes <= 0:
        print(f"cannot read {clip}", file=sys.stderr)
        return 1
    if args.end_s * fps > nframes:
        print(f"clip too short: {nframes / fps:.1f}s < --end-s {args.end_s}", file=sys.stderr)
        return 1
    digest = sha256(clip)
    start, end = int(args.start_s * fps), int(args.end_s * fps)
    cfg = load_config(env=False)
    rel = clip.resolve().relative_to(REPO_ROOT).as_posix() if clip.resolve().is_relative_to(
        REPO_ROOT) else clip.as_posix()

    rows = []
    for kind in [None, *STRENGTH]:
        t0 = time.perf_counter()
        frames = inject(clip_frames(str(clip)), kind, start, end, STRENGTH.get(kind, 0), args.seed)
        res = replay(frames, fps, cfg)
        row = score(res, kind, args.start_s, fps, cfg)
        row["replay_s"] = round(time.perf_counter() - t0, 1)
        rows.append(row)
        print(json.dumps(row))
        if kind is None:
            continue
        man = {
            "id": f"f1-{args.session}-{kind}", "session": args.session,
            "source": {"path": rel, "sha256": digest},
            "camera": {"id": "cam_01", "resolution": size, "device": "laptop webcam"},
            "fault": {"kind": kind, "strength": STRENGTH[kind], "start_frame": start,
                      "end_frame": end, "seed": args.seed},
            "expected": {"faults": [str(EXPECTED[kind])]},
            "notes": "F1 spike: SIMULATION fault on a REAL HARDWARE clip",
        }
        path = REPO_ROOT / "benchmarks" / "manifests" / f"{man['id']}.yaml"
        path.write_text(yaml.safe_dump(man, sort_keys=False))

    ok = all(r["passed"] for r in rows)
    lines = [
        "# Fault-injection spike report (Gate F1)", "",
        f"- source: {args.source_label} clip `{rel}` sha256 `{digest[:16]}…`",
        f"- clip: {nframes} frames, {fps:.2f} FPS, {size[0]}x{size[1]}",
        f"- faults: SIMULATION, frames [{start}, {end}) = [{args.start_s}s, {args.end_s}s), "
        f"seed {args.seed}", "",
        "| injected | expected | confirmed | delay s | pre-fault suspect windows | passed |",
        "|---|---|---|---|---|---|",
    ]
    for r in rows:
        lines.append(f"| {r['kind']} | {r['expected'] or '-'} | "
                     f"{','.join(r['confirmed_faults']) or '-'} | {r['detection_delay_s']} | "
                     f"{r['pre_fault_suspect_windows']}/{r['windows']} | {r['passed']} |")
    lines += ["", f"- overall: {'PASS' if ok else 'FAIL'}",
              f"- generated: {time.strftime('%Y-%m-%d %H:%M:%S')}"]
    out = REPO_ROOT / "spikes" / "inject-report.md"
    out.parent.mkdir(exist_ok=True)
    out.write_text("\n".join(lines) + "\n")
    (out.with_suffix(".json")).write_text(json.dumps(rows, indent=2))
    print("\n".join(lines))
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
