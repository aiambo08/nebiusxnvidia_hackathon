"""Rebuild degraded clips from manifests (one command, F4):

    python -m benchmarks.make_degraded benchmarks/manifests/example-dark-001.yaml out.avi
    python -m benchmarks.make_degraded --all   # every F4 manifest -> benchmarks/data/degraded/

Same manifest and same source clip (checked by sha256) -> same frames. A manifest may cut a
`segment` [start_frame, end_frame) of the source; fault frames are absolute source indices.
"""

from __future__ import annotations

import argparse
import hashlib
import sys
from collections.abc import Iterator
from pathlib import Path

import cv2
import numpy as np
import yaml

from benchmarks.injectors.faults import apply_stream

ROOT = Path(__file__).resolve().parents[1]
F4_DIR = ROOT / "benchmarks" / "manifests" / "f4"
OUT_DIR = ROOT / "benchmarks" / "data" / "degraded"
_DIGESTS: dict[Path, str] = {}


def source_path(m: dict) -> Path:
    p = Path(m["source"]["path"])
    return p if p.is_absolute() else ROOT / p


def digest_of(path: Path) -> str:
    if path not in _DIGESTS:
        h = hashlib.sha256()
        with path.open("rb") as fh:
            for chunk in iter(lambda: fh.read(1 << 20), b""):
                h.update(chunk)
        _DIGESTS[path] = h.hexdigest()
    return _DIGESTS[path]


def check_source(m: dict) -> str | None:
    """Problem with the manifest's source clip, or None when it matches the recorded hash."""
    src = source_path(m)
    if not src.exists():
        return f"{m['id']}: source clip missing"
    if m["source"].get("sha256") not in (None, "TBD", digest_of(src)):
        return f"{m['id']}: source hash mismatch (dataset changed)"
    return None


def clip_info(path: Path) -> tuple[float, int, int]:
    cap = cv2.VideoCapture(str(path))
    fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
    w, h = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH)), int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    cap.release()
    return fps, w, h


def frames_of(path: str | Path, start: int = 0, end: int | None = None) -> Iterator[np.ndarray]:
    """Decoded frames [start, end) read in order (no seeking: exact on every container)."""
    cap = cv2.VideoCapture(str(path))
    try:
        i = 0
        while end is None or i < end:
            if i < start:
                if not cap.grab():
                    return
            else:
                ok, f = cap.read()
                if not ok:
                    return
                yield f
            i += 1
    finally:
        cap.release()


def degraded_frames(m: dict) -> Iterator[np.ndarray]:
    seg = m.get("segment") or {"start_frame": 0, "end_frame": None}
    s0 = seg["start_frame"]
    fz = m["fault"]
    frames = frames_of(source_path(m), s0, seg["end_frame"])
    return apply_stream(frames, fz["kind"], fz["start_frame"] - s0, fz["end_frame"] - s0,
                        fz.get("strength", 1.0), fz.get("seed", 0))


def load_manifest(path: str | Path) -> dict:
    return yaml.safe_load(Path(path).read_text(encoding="utf-8"))


def write(m: dict, out: Path) -> int:
    fps, w, h = clip_info(source_path(m))
    out.parent.mkdir(parents=True, exist_ok=True)
    vw = cv2.VideoWriter(str(out), cv2.VideoWriter_fourcc(*"MJPG"), fps, (w, h))
    n = 0
    for f in degraded_frames(m):
        vw.write(f)
        n += 1
    vw.release()
    return n


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("manifest", nargs="?")
    ap.add_argument("out", nargs="?")
    ap.add_argument("--all", action="store_true", help="rebuild every F4 manifest")
    ap.add_argument("--out-dir", default=None, help="default benchmarks/data/degraded/")
    args = ap.parse_args(argv)
    if args.all:
        out_dir = Path(args.out_dir) if args.out_dir else OUT_DIR
        jobs = [(p, out_dir / f"{p.stem}.avi") for p in sorted(F4_DIR.glob("*.yaml"))]
        if not jobs:
            print("no F4 manifests: run python -m benchmarks.build_manifests", file=sys.stderr)
            return 1
    elif args.manifest and args.out:
        jobs = [(Path(args.manifest), Path(args.out))]
    else:
        ap.error("give <manifest> <out.avi> or --all")
    for path, out in jobs:
        m = load_manifest(path)
        if problem := check_source(m):
            print(problem, file=sys.stderr)
            return 1
        n = write(m, out)
        print(f"wrote {n} frames to {out.name} (source sha256 {digest_of(source_path(m))[:12]})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
