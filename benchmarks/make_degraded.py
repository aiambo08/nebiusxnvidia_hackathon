"""Rebuild a degraded clip from a manifest (one command, F4):

    python -m benchmarks.make_degraded benchmarks/manifests/example-dark-001.yaml out.avi
"""

import hashlib
import sys
from pathlib import Path

import cv2
import yaml

from benchmarks.injectors.faults import apply_stream


def frames_of(path: str):
    cap = cv2.VideoCapture(path)
    while True:
        ok, f = cap.read()
        if not ok:
            break
        yield f
    cap.release()


def main(manifest: str, out: str) -> int:
    m = yaml.safe_load(Path(manifest).read_text(encoding="utf-8"))
    src = m["source"]["path"]
    digest = hashlib.sha256(Path(src).read_bytes()).hexdigest()
    if m["source"].get("sha256") not in (None, "TBD", digest):
        print("source hash mismatch: dataset changed", file=sys.stderr)
        return 1
    fz = m["fault"]
    cap = cv2.VideoCapture(src)
    fps = cap.get(cv2.CAP_PROP_FPS) or 30
    w, h = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH)), int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    cap.release()
    vw = cv2.VideoWriter(out, cv2.VideoWriter_fourcc(*"MJPG"), fps, (w, h))
    n = 0
    for f in apply_stream(frames_of(src), fz["kind"], fz["start_frame"], fz["end_frame"],
                          fz.get("strength", 1.0), fz.get("seed", 0)):
        vw.write(f)
        n += 1
    vw.release()
    print(f"wrote {n} frames to {out} (source sha256 {digest[:12]})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1], sys.argv[2]))
