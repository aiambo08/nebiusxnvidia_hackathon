"""Record a clean clip from a camera (webcam index or rtsp:// URL) for the F1/F4 benchmark.

Raw recordings stay local in `benchmarks/data/` (git-ignored). Only the SHA-256 is published.
With `--split dev|test` the session is also added to the committed F4 index
(`benchmarks/manifests/sessions.yaml`, no URI, no path); an existing clip is never overwritten.

    python scripts/record_clip.py --uri 0 --seconds 300 --session s010 --split test \
        --conditions "textured desk, daylight, nobody in frame"
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import time
from pathlib import Path

import _src_path  # noqa: F401  (adds src/ to sys.path)
import cv2

from benchmarks import build_manifests, dataset
from reliability_agent.capture import OpenCVSource
from reliability_agent.capture.sources import parse_uri

REPO_ROOT = Path(__file__).resolve().parents[1]
SPLIT_SECONDS = 330.0  # 6 test sessions give 33 normal minutes, margin over the 30-min box


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--uri", default="0", help="webcam index, file path or rtsp:// URL")
    ap.add_argument("--seconds", type=float, default=None,
                    help=f"default {SPLIT_SECONDS:g} with --split, else 90")
    ap.add_argument("--session", default="s001")
    ap.add_argument("--warmup", type=float, default=2.0, help="seconds used to measure FPS")
    ap.add_argument("--split", choices=dataset.SPLITS, default=None,
                    help="add the session to the F4 index as dev or test")
    ap.add_argument("--conditions", default="", help="scene/lighting/people, no names or places")
    ap.add_argument("--overwrite", action="store_true", help="replace an existing clip")
    args = ap.parse_args()
    if args.seconds is None:
        args.seconds = SPLIT_SECONDS if args.split else 90.0

    out = REPO_ROOT / "benchmarks" / "data" / f"{args.session}_clean.avi"
    if args.split:
        try:
            dataset.check_session_id(args.session)
        except ValueError as e:
            ap.error(str(e))
        if any(s.id == args.session for s in dataset.load()):
            ap.error(f"session {args.session} is already in the F4 index; pick a new id")
        if args.session in dataset.development()[0]:
            ap.error(f"session {args.session} was used while building the detectors; pick a new id")
        try:
            dataset.check_public(args.conditions, "--conditions")
        except ValueError as e:
            ap.error(str(e))
        need = build_manifests.SLOTS * (build_manifests.LEAD_S + build_manifests.FAULT_S)
        if args.seconds < need:
            ap.error(f"--seconds must be >= {need:g} for {build_manifests.SLOTS} runs per fault")
    if out.exists() and not args.overwrite:
        ap.error(f"{out.name} exists; use a new --session or --overwrite")
    out.parent.mkdir(parents=True, exist_ok=True)
    src = OpenCVSource(parse_uri(args.uri))
    src.open()
    try:
        t0, n, first = time.monotonic(), 0, None
        while time.monotonic() - t0 < args.warmup:  # measure the real delivery rate
            f = src.read()
            if f is not None:
                first = first or f
                n += 1
        if first is None:
            print("no frames from source", file=sys.stderr)
            return 1
        fps = round(n / (time.monotonic() - t0), 2)
        h, w = first.image.shape[:2]
        vw = cv2.VideoWriter(str(out), cv2.VideoWriter_fourcc(*"MJPG"), fps, (w, h))
        written, misses = 0, 0
        t0 = time.monotonic()
        while time.monotonic() - t0 < args.seconds:
            f = src.read()
            if f is None:
                misses += 1
                continue
            vw.write(f.image)
            written += 1
        elapsed = time.monotonic() - t0
        vw.release()
    finally:
        src.close()
    info = {"session": args.session, "path": out.relative_to(REPO_ROOT).as_posix(),
            "sha256": sha256(out), "frames": written, "fps": round(written / elapsed, 2),
            "header_fps": fps, "resolution": [w, h], "seconds": round(elapsed, 1),
            "read_misses": misses, "uri_kind": src.kind}
    print(json.dumps(info, indent=2))
    if written == 0:
        return 1
    if abs(info["fps"] - fps) > 0.1 * fps:
        print(f"warning: recorded at {info['fps']} FPS, warm-up measured {fps} FPS",
              file=sys.stderr)
    if args.split:
        dataset.add(dataset.Session(
            id=args.session, split=args.split, sha256=info["sha256"], frames=written,
            fps=info["fps"], resolution=[w, h], seconds=info["seconds"],
            conditions=args.conditions))
        print(f"added {args.session} ({args.split}) to {dataset.INDEX.relative_to(REPO_ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
