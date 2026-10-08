"""Gate F3 freeze false-positive check (SIMULATION): healthy static scenes vs frozen pipelines.

Runs the full local detection path (probes -> window aggregation -> baseline -> IncidentTracker)
on synthetic static scenes that differ only in sensor noise and lighting, for `--minutes` of
analytic frames each. A healthy static scene must never confirm an incident; frozen variants
of the same scene must be confirmed as `freeze`. Writes a Markdown table.
"""

from __future__ import annotations

import argparse
import time
from collections.abc import Iterator
from pathlib import Path

import _src_path  # noqa: F401  (adds src/ to sys.path)
import cv2
import numpy as np

from benchmarks.replay import replay
from reliability_agent.config import load_config

W, H = 640, 480


def _scene(kind: str, rng: np.random.Generator) -> np.ndarray:
    if kind == "wall":  # smooth indoor scene, little texture
        base = np.full((H, W, 3), 120, np.uint8)
        cv2.rectangle(base, (100, 100), (300, 300), (200, 180, 160), -1)
        cv2.putText(base, "wall", (350, 250), cv2.FONT_HERSHEY_SIMPLEX, 3, (40, 40, 40), 6)
        return base
    tex = rng.integers(60, 200, (H, W, 3)).astype(np.uint8)  # lit textured desk / shelf
    return cv2.GaussianBlur(tex, (0, 0), 3)


def frames(kind: str, sigma: float, n: int, *, gain: float = 1.0, freeze_at: int | None = None,
           jitter: float = 0.0, loop: int = 0, drift: float = 0.0,
           motion: tuple[int, int] = (0, 0), seed: int = 0) -> Iterator[np.ndarray]:
    """Static scene with Gaussian sensor noise `sigma` (counts at full resolution).

    freeze_at: from that frame on the pipeline repeats one frame (bit-exact, or with codec
    `jitter` noise added per frame); loop: repeat the last `loop` frames forever instead.
    drift: slow sinusoidal lighting change (fraction of brightness) over the run.
    motion: (on_frames, off_frames) — a person-sized dark blob crosses the scene for `on_frames`,
    then the scene rests for `off_frames` (0 = forever); the cycle repeats. Models a baseline
    learned while someone is in front of the camera (reviewer case for ADR-004).
    """
    rng = np.random.default_rng(seed)
    base = _scene(kind, rng).astype(np.float32) * gain
    frozen: np.ndarray | None = None
    tail: list[np.ndarray] = []
    for i in range(n):
        if frozen is not None:
            img = frozen if not jitter else np.clip(np.rint(
                frozen.astype(np.float32) + rng.normal(0, jitter, frozen.shape)), 0, 255
            ).astype(np.uint8)
            yield img
            continue
        if loop and freeze_at is not None and i >= freeze_at:
            yield tail[(i - freeze_at) % loop]
            continue
        g = 1.0 + drift * np.sin(2 * np.pi * i / n) if drift else 1.0
        scene = base * g
        on, off = motion
        if on and (not off or (i % (on + off)) < on):
            scene = scene.copy()
            x = int((i % on) / on * (W + 160)) - 80
            cv2.rectangle(scene, (x, 60), (x + 80, H - 20), (30, 30, 30), -1)
        img = np.clip(np.rint(scene + rng.normal(0, sigma, base.shape)), 0, 255).astype(np.uint8)
        if loop:
            tail.append(img)
            tail = tail[-loop:]
        if freeze_at is not None and i + 1 == freeze_at and not loop:
            frozen = img
        yield img


CASES = [
    # name, kwargs, expect_confirmed (None = report only, documented limitation)
    ("wall sigma 0.7 (laptop webcam at rest)", dict(kind="wall", sigma=0.7), False),
    ("wall sigma 2", dict(kind="wall", sigma=2.0), False),
    ("textured sigma 1", dict(kind="textured", sigma=1.0), False),
    ("textured sigma 2 (reviewer FP case)", dict(kind="textured", sigma=2.0), False),
    ("textured sigma 3", dict(kind="textured", sigma=3.0), False),
    ("textured sigma 2, dim (gain 0.3)", dict(kind="textured", sigma=2.0, gain=0.3), False),
    ("wall sigma 0.7, person walks by 30 s then rest (reviewer case)",
     dict(kind="wall", sigma=0.7, motion=(150, 0)), False),
    ("wall sigma 2, 5 min of motion then rest", dict(kind="wall", sigma=2.0, motion=(1500, 0)),
     False),
    ("wall sigma 2, alternating 30 s motion / 30 s rest",
     dict(kind="wall", sigma=2.0, motion=(150, 150)), False),
    ("textured sigma 2, slow light drift 15%", dict(kind="textured", sigma=2.0, drift=0.15),
     False),
    ("textured sigma 2, frozen bit-exact", dict(kind="textured", sigma=2.0, freeze_at=300), True),
    ("textured sigma 2, frozen + codec jitter 0.1",
     dict(kind="textured", sigma=2.0, freeze_at=300, jitter=0.1), True),
    # informative only (None): per-frame decoder noise flips dHash bits once it reaches ~0.3
    # counts (hash repeat 1.0 -> 0.75 at 0.5 counts), so the hash path loses a frozen stream whose
    # decoder is that noisy even though its MSE stays far under the live floor (ADR-004)
    ("textured sigma 2, frozen + codec jitter 0.2",
     dict(kind="textured", sigma=2.0, freeze_at=300, jitter=0.2), None),
    ("textured sigma 2, frozen + codec jitter 0.5",
     dict(kind="textured", sigma=2.0, freeze_at=300, jitter=0.5), None),
    ("wall sigma 0.7, frozen bit-exact", dict(kind="wall", sigma=0.7, freeze_at=300), True),
    ("textured sigma 2, loop of 4 frames", dict(kind="textured", sigma=2.0, freeze_at=300,
                                                 loop=4), True),
]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--minutes", type=float, default=20.0, help="per healthy case")
    ap.add_argument("--fault-minutes", type=float, default=3.0, help="per frozen case")
    ap.add_argument("--out", default="docs/evidence/f3/static-scene.md")
    args = ap.parse_args()
    cfg = load_config(env=False)
    fps = cfg["camera"]["analytic_fps"]
    rows: list[tuple] = []
    findings: list[tuple[str, list[str]]] = []
    for name, kw, expect in CASES:
        minutes = args.minutes if expect is False else args.fault_minutes
        n = int(minutes * 60 * fps)
        t0 = time.perf_counter()
        res = replay(frames(n=n, **kw), fps, cfg)
        fz = sum("freeze" in w.faults for w in res.windows)
        conf = res.confirmed_faults
        freeze_at = kw.get("freeze_at")
        detected = (freeze_at is not None and res.confirmed_window is not None
                    and "freeze" in conf
                    and res.confirmed_window * cfg["window"]["seconds"] >= freeze_at / fps)
        others = sorted(set(conf) - {"freeze"})
        if expect is None:
            verdict = "INFO: detected" if detected else "INFO: not detected (documented)"
        elif expect:
            verdict = "PASS" if detected else "FAIL"
        else:
            # the F3 box is freeze-specific; any other fault confirmed on a healthy static scene
            # is reported as a finding (see "Findings" below), not graded here
            verdict = "PASS" if "freeze" not in conf else "FAIL"
            if others:
                verdict += " (freeze); finding: " + ", ".join(others)
                findings.append((name, others))
        delay = (round(res.confirmed_window * cfg["window"]["seconds"] - freeze_at / fps, 1)
                 if freeze_at is not None and res.confirmed_window is not None else "-")
        rows.append((name, minutes, len(res.windows), fz, ", ".join(conf) or "-", delay, verdict))
        print(f"{name}: windows={len(res.windows)} freeze_windows={fz} confirmed={conf} "
              f"delay={delay} {verdict} ({time.perf_counter() - t0:.0f}s)")
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        "# Static-scene freeze false positives (Gate F3) — SIMULATION",
        "",
        f"Synthetic {W}x{H} scenes, {fps} analytic FPS, full local path "
        "(`benchmarks.replay.replay`: probes -> windows -> baseline -> IncidentTracker). "
        "Healthy cases must never confirm `freeze`; frozen cases must confirm `freeze` after the "
        "freeze. Other faults confirmed on a healthy scene are listed as findings.",
        "",
        "| scene | minutes | windows | freeze windows | confirmed | delay s | result |",
        "|---|---|---|---|---|---|---|",
    ]
    lines += [f"| {r[0]} | {r[1]:g} | {r[2]} | {r[3]} | {r[4]} | {r[5]} | {r[6]} |" for r in rows]
    if findings:
        lines += ["", "## Findings (other faults confirmed on a healthy static scene)", ""]
        lines += [f"- `{name}`: {', '.join(f'`{f}`' for f in fs)} — false positive of another "
                  "detector, tracked in `docs/agents/TASKS.md`" for name, fs in findings]
    lines += ["", f"generated: {time.strftime('%Y-%m-%d %H:%M:%S')}", ""]
    out.write_text("\n".join(lines))
    print(f"wrote {out}")
    if any(r[-1].startswith("FAIL") for r in rows):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
