"""Render the README fault gallery from the deterministic SIMULATION source.

Every tile is a real ``SyntheticSource`` frame with one fault injected through ``set_fault``,
the same path the benchmarks and the dashboard use. No recordings are involved.

    python scripts/render_fault_gallery.py --out docs/media/fault-gallery.png
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from reliability_agent.capture.sources import SyntheticSource  # noqa: E402

TILE_W = 320
GALLERY_COLS = 3
TILE_PAD = 6

TILES: tuple[tuple[str, str | None, float], ...] = (
    ("healthy", None, 1.0),
    ("dark (blackout)", "dark", 0.99),
    ("defocus (blur)", "defocus", 1.0),
    ("lens occlusion", "occlude", 1.0),
    ("overexposure", "overexpose", 1.0),
    ("fov shift", "shift", 1.0),
)


def render_tile(label: str, fault: str | None, strength: float, seed: int = 0) -> np.ndarray:
    src = SyntheticSource(seed=seed)
    src.open()
    src.set_fault(fault, strength)
    frame = src.read()
    src.close()
    img = cv2.resize(frame.image, (TILE_W, TILE_W * 3 // 4), interpolation=cv2.INTER_AREA)
    cv2.rectangle(img, (0, img.shape[0] - 28), (img.shape[1], img.shape[0]), (20, 20, 20), -1)
    cv2.putText(img, f"SIMULATION - {label}", (8, img.shape[0] - 9),
                cv2.FONT_HERSHEY_SIMPLEX, 0.55, (255, 255, 255), 1, cv2.LINE_AA)
    return img


def render_gallery(cols: int = GALLERY_COLS) -> np.ndarray:
    tiles = [render_tile(*t) for t in TILES]
    rows = [
        np.hstack(
            [
                np.pad(
                    tile,
                    ((TILE_PAD, TILE_PAD), (TILE_PAD, TILE_PAD), (0, 0)),
                    constant_values=255,
                )
                for tile in tiles[index : index + cols]
            ]
        )
        for index in range(0, len(tiles), cols)
    ]
    return np.vstack(rows)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--out", required=True, type=Path)
    args = ap.parse_args(argv)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    if not cv2.imwrite(str(args.out), render_gallery()):
        raise SystemExit(f"could not write {args.out}")
    print(f"wrote {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
