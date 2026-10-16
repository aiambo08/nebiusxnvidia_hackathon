"""Write the F4 run manifests from the session index (deterministic, one command):

    python -m benchmarks.build_manifests

One manifest per (test session x MVP fault x intensity) plus legitimate-lighting negatives.
Each run is a `LEAD_S` healthy lead-in followed by `FAULT_S` of the fault, cut from one of three
non-overlapping slots of the session (intensity i -> slot i). The strengths were fixed before
any F4 recording was seen (the "strong" grades of the F3 benchmark plus one midpoint), so they
are not tuned on test data. Faults are SIMULATION on REAL HARDWARE clips.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

import yaml

from benchmarks import dataset
from benchmarks.replay import EXPECTED

OUT = dataset.ROOT / "benchmarks" / "manifests" / "f4"
LEAD_S, FAULT_S = 30.0, 30.0
SLOTS = 3
# MVP faults (docs/evaluation.md): injector -> pre-registered strengths, one per slot
FAULTS: dict[str, list[float]] = {
    "dark": [0.9, 0.95, 1.0],
    "gaussian_blur": [0.7, 0.85, 1.0],
    "freeze": [1.0, 1.0, 1.0],
    "occlude_opaque": [0.7, 0.85, 1.0],
    "overexpose": [0.8, 0.9, 1.0],
}
NEGATIVES: dict[str, list[float]] = {"lighting_change": [1.0, 1.0, 1.0]}


def seed_of(*parts: object) -> int:
    return int(hashlib.sha256("/".join(map(str, parts)).encode()).hexdigest()[:8], 16)


def slot_starts(frames: int, run_frames: int) -> list[int]:
    if frames < SLOTS * run_frames:
        raise ValueError(f"session has {frames} frames, {SLOTS} non-overlapping runs need "
                         f"{SLOTS * run_frames}")
    span = frames - run_frames
    return [round(k * span / (SLOTS - 1)) for k in range(SLOTS)]


def manifests_for(s: dataset.Session) -> list[dict]:
    lead, fault = round(LEAD_S * s.fps), round(FAULT_S * s.fps)
    starts = slot_starts(s.frames, lead + fault)
    out = []
    for kind, strengths in {**FAULTS, **NEGATIVES}.items():
        for i, (strength, seg0) in enumerate(zip(strengths, starts, strict=True)):
            expected = EXPECTED.get(kind)
            out.append({
                "id": f"f4-{s.id}-{kind}-{i}",
                "session": s.id,
                "split": s.split,
                "label": f"SIMULATION fault on a {s.label} clip",
                "source": {"path": f"benchmarks/data/{s.id}_clean.avi", "sha256": s.sha256},
                "camera": {"id": "cam_01", "resolution": s.resolution, "fps": s.fps},
                "segment": {"start_frame": seg0, "end_frame": seg0 + lead + fault},
                "fault": {"kind": kind, "strength": strength, "start_frame": seg0 + lead,
                          "end_frame": seg0 + lead + fault, "seed": seed_of(s.id, kind, i)},
                "expected": {"faults": [str(expected)] if expected else []},
            })
    return out


def build(sessions: list[dataset.Session], out: Path | None = None) -> list[dict]:
    """Manifests for every test session; stale `f4-*.yaml` files in `out` are removed."""
    out = out or OUT
    runs = [m for s in sessions if s.split == "test" for m in manifests_for(s)]
    out.mkdir(parents=True, exist_ok=True)
    for old in out.glob("f4-*.yaml"):
        old.unlink()
    for m in runs:
        (out / f"{m['id']}.yaml").write_text(yaml.safe_dump(m, sort_keys=False),
                                             encoding="utf-8", newline="\n")
    return runs


def main() -> int:
    runs = build(dataset.load())
    print(f"wrote {len(runs)} manifests to {OUT.relative_to(dataset.ROOT).as_posix()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
