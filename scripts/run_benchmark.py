"""Gate F4 benchmark report in one command (local detection path, no network, no LLM):

    python scripts/run_benchmark.py

Checks every session clip against its sha256 in `benchmarks/manifests/sessions.yaml`, writes the
run manifests (`benchmarks.build_manifests`), replays each fault/negative run and every test
session in full (`benchmarks.replay.replay`), and writes `benchmarks/reports/<date>-<name>.md`
plus a `.json` with every run. The JSON and the report contain no frames, URIs or absolute
paths. Exit code 0 only when every F4 gate box this report can judge passes.

A fault run is a true positive of detector D when D is the fault `benchmarks.replay.EXPECTED`
maps its injector to and D is confirmed after onset. Every detector confirmed where it is not
expected (another fault's run, a lighting-change run, before onset, or anywhere in a normal
test session) is a false positive of that detector. Normal test sessions are replayed with
`rearm=True`, so every confirmation counts towards false alarms per hour.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import time
from collections import defaultdict
from pathlib import Path

import _src_path  # noqa: F401  (adds src/ to sys.path)
from spike_static_scene import code_revision

from benchmarks import build_manifests, dataset
from benchmarks.make_degraded import degraded_frames, frames_of
from benchmarks.replay import replay, score
from reliability_agent.config import load_config

ROOT = dataset.ROOT
MVP = ("blackout", "focus_drift", "freeze", "lens_occlusion", "overexposure")
RUNS_PER_FAULT_MIN = 15
NORMAL_MINUTES_MIN = 30.0
MACRO_F1_MIN = 0.85
FALSE_ALARMS_PER_HOUR_MAX = 1.0


def config_digest(cfg: dict) -> str:
    return hashlib.sha256(json.dumps(cfg, sort_keys=True).encode()).hexdigest()[:12]


SESSIONS_PER_FAULT_MIN = 5


def development() -> tuple[set[str], set[str]]:
    """Session ids and clip sha256 used while building the detectors (F1/F3 manifests)."""
    return dataset.development(ROOT / "benchmarks" / "manifests")


def run_manifest(m: dict, cfg: dict) -> dict:
    fps = m["camera"]["fps"]
    kind = m["fault"]["kind"]
    onset_s = (m["fault"]["start_frame"] - m["segment"]["start_frame"]) / fps
    res = replay(degraded_frames(m), fps, cfg)
    out = score(res, kind, onset_s, fps, cfg)
    expected = out["expected"]
    pre = res.confirmed_window is not None and out["confirmed_at_s"] < onset_s
    out["false_positives"] = sorted(f for f in res.confirmed_faults
                                    if f != expected or pre or expected is None)
    out.update(id=m["id"], session=m["session"], strength=m["fault"]["strength"])
    return out


def run_normal(s: dataset.Session, cfg: dict) -> dict:
    res = replay(frames_of(s.clip), s.fps, cfg, rearm=True)
    return {"session": s.id, "seconds": s.seconds, "windows": len(res.windows),
            "confirmations": [{"t_s": t, "faults": f} for _, t, f in res.confirmations]}


def aggregate(runs: list[dict], normals: list[dict]) -> dict[str, dict]:
    stats = {f: {"runs": 0, "tp": 0, "fp": 0, "sessions": set(), "delays": []} for f in MVP}
    extra: dict[str, dict] = defaultdict(lambda: {"runs": 0, "tp": 0, "fp": 0,
                                                  "sessions": set(), "delays": []})
    get = lambda f: stats[f] if f in stats else extra[f]  # noqa: E731
    for r in runs:
        if r["expected"]:
            d = get(r["expected"])
            d["runs"] += 1
            d["sessions"].add(r["session"])
            if r["passed"]:
                d["tp"] += 1
                d["delays"].append(r["detection_delay_s"])
        for f in r["false_positives"]:
            get(f)["fp"] += 1
    for n in normals:
        for c in n["confirmations"]:
            for f in c["faults"]:
                get(f)["fp"] += 1
    out = {**stats, **extra}
    for d in out.values():
        d["sessions"] = len(d["sessions"])
        d["recall"] = d["tp"] / d["runs"] if d["runs"] else None
        d["precision"] = d["tp"] / (d["tp"] + d["fp"]) if d["tp"] + d["fp"] else None
        p, r = d["precision"], d["recall"]
        d["f1"] = 2 * p * r / (p + r) if p and r else 0.0
        delays = sorted(d.pop("delays"))
        d["delay_p50_s"] = delays[len(delays) // 2] if delays else None
    return out


def gate_boxes(sessions, runs, normals, stats, problems, dev) -> list[tuple[str, bool, str]]:
    dev_ids, dev_hashes = dev
    test = [s for s in sessions if s.split == "test"]
    normal_min = sum(s.seconds for s in test) / 60
    hours = sum(n["seconds"] for n in normals) / 3600
    alarms = sum(len(n["confirmations"]) for n in normals)
    fa_h = alarms / hours if hours else float("inf")
    macro = sum(stats[f]["f1"] for f in MVP) / len(MVP)
    per_fault = min(stats[f]["runs"] for f in MVP)
    sessions_per_fault = min(stats[f]["sessions"] for f in MVP)
    hashes = [s.sha256 for s in sessions]
    leaked = sorted(s.id for s in test if s.sha256 in dev_hashes or s.id in dev_ids)
    run_sessions = {r["session"] for r in runs}
    split_ok = (len(set(hashes)) == len(hashes)
                and run_sessions <= {s.id for s in test} and bool(test))
    return [
        (f">= {RUNS_PER_FAULT_MIN} independent runs per MVP fault",
         per_fault >= RUNS_PER_FAULT_MIN and sessions_per_fault >= SESSIONS_PER_FAULT_MIN,
         f"needs >= {SESSIONS_PER_FAULT_MIN} sessions per fault; "
         + ", ".join(f"{f} {stats[f]['runs']} runs / {stats[f]['sessions']} sessions"
                     for f in MVP)),
        (f">= {NORMAL_MINUTES_MIN:g} min of normal conditions",
         normal_min >= NORMAL_MINUTES_MIN, f"{normal_min:.1f} min in {len(test)} test sessions"),
        ("Split by session", split_ok,
         f"{len(test)} test / {len(sessions) - len(test)} dev sessions, distinct clip hashes, "
         "runs only on test sessions"),
        ("Dataset versioned by manifest + hashes", not problems and bool(runs),
         "; ".join(problems) or f"{len(sessions)} clips match their sha256, {len(runs)} manifests"),
        (f"Macro F1 >= {MACRO_F1_MIN:g} on the 5 MVP faults", macro >= MACRO_F1_MIN,
         f"macro F1 {macro:.3f}"),
        (f"<= {FALSE_ALARMS_PER_HOUR_MAX:g} false alarm / hour in normal conditions",
         hours > 0 and fa_h <= FALSE_ALARMS_PER_HOUR_MAX,
         f"{alarms} confirmations in {hours * 60:.1f} min = {fa_h:.2f} / h"),
        ("No published metric from data reused as test", not leaked and bool(test),
         "test sessions sharing a clip hash or a session id with F1/F3 development manifests: "
         f"{', '.join(leaked) or 'none'}"),
    ]


def render(meta: dict, sessions, stats, boxes, runs, normals) -> str:
    fmt = lambda v: "-" if v is None else f"{v:.2f}"  # noqa: E731
    lines = [f"# F4 benchmark — {meta['label']}", "",
             f"commit: `{meta['commit']}` | config sha256: `{meta['config']}` | generated: "
             f"{meta['generated']} | wall time: {meta['wall_s']:.0f} s | overall: "
             f"**{meta['overall']}**", "",
             "Regenerate: `python scripts/run_benchmark.py` (same clips, same commit, same "
             "report). Local detection path only: no Nemotron calls, no cost.", "",
             "## Gate F4", "", "| box | result | evidence |", "|---|---|---|"]
    lines += [f"| {b} | {'PASS' if ok else 'FAIL'} | {ev} |" for b, ok, ev in boxes]
    lines += ["", "Not judged here: one command rebuilds every F4 degradation "
              "(`python -m benchmarks.make_degraded --all`).", "",
              "Reading the numbers:",
              "- Every fault strength is strong (>= 0.7, freeze 1.0): macro F1 measures detection "
              "of strong faults only.",
              "- Fault runs score the first confirmation only; a wrong detector confirmed after "
              "the right one is not counted, so fault-run precision may read high.",
              "- Normal sessions re-arm after every confirmation: a condition that persists is "
              "counted again (errs towards more false alarms).",
              "- Runs are scored on the degraded frames in memory, the same frames "
              "`make_degraded` writes before AVI encoding.", "",
              "## Per detector", "",
              "| detector | runs | sessions | TP | FN | FP | recall | precision | F1 | "
              "delay p50 s |", "|---|---|---|---|---|---|---|---|---|---|"]
    for name, d in stats.items():
        lines.append(f"| {name}{'' if name in MVP else ' (not MVP)'} | {d['runs']} | "
                     f"{d['sessions']} | {d['tp']} | {d['runs'] - d['tp']} | {d['fp']} | "
                     f"{fmt(d['recall'])} | {fmt(d['precision'])} | {d['f1']:.2f} | "
                     f"{fmt(d['delay_p50_s'])} |")
    lines += ["", "## Sessions", "", "| session | split | sha256 | min | fps | resolution | "
              "conditions |", "|---|---|---|---|---|---|---|"]
    lines += [f"| {s.id} | {s.split} | `{s.sha256[:12]}` | {s.seconds / 60:.1f} | {s.fps:g} | "
              f"{s.resolution[0]}x{s.resolution[1]} | {s.conditions or '-'} |" for s in sessions]
    lines += ["", "## Normal test sessions (full clip, every confirmation counted)", "",
              "| session | min | windows | confirmations |", "|---|---|---|---|"]
    lines += [f"| {n['session']} | {n['seconds'] / 60:.1f} | {n['windows']} | "
              + (", ".join(f"{c['t_s']:.0f}s {'/'.join(c['faults'])}"
                           for c in n["confirmations"]) or "0") + " |" for n in normals]
    lines += ["", "## Runs", "", "| run | strength | expected | confirmed | delay s | "
              "false positives | result |", "|---|---|---|---|---|---|---|"]
    lines += [f"| {r['id']} | {r['strength']:g} | {r['expected'] or '- (negative)'} | "
              f"{', '.join(r['confirmed_faults']) or '-'} | "
              f"{'-' if r['detection_delay_s'] is None else r['detection_delay_s']} | "
              f"{', '.join(r['false_positives']) or '-'} | {'PASS' if r['passed'] else 'FAIL'} |"
              for r in runs]
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--name", default="f4", help="report file tag")
    ap.add_argument("--out-dir", default=str(ROOT / "benchmarks" / "reports"))
    ap.add_argument("--overwrite", action="store_true")
    args = ap.parse_args(argv)
    t0 = time.perf_counter()
    stamp = time.strftime("%Y-%m-%d")
    out = Path(args.out_dir) / f"{stamp}-{args.name}.md"
    if out.exists() and not args.overwrite:
        ap.error(f"{out.name} exists; use another --name or --overwrite")
    sessions = dataset.load()
    if not any(s.split == "test" for s in sessions):
        print("no test sessions in benchmarks/manifests/sessions.yaml (record_clip.py --split "
              "test)", file=sys.stderr)
        return 2
    problems = dataset.verify(sessions)
    if problems:
        print("dataset does not match its index:\n  " + "\n  ".join(problems), file=sys.stderr)
        return 2
    cfg = load_config(env=False)
    manifests = build_manifests.build(sessions)
    runs = []
    for i, m in enumerate(manifests, 1):
        r = run_manifest(m, cfg)
        runs.append(r)
        print(f"[{i}/{len(manifests)}] {r['id']}: confirmed={r['confirmed_faults']} "
              f"fp={r['false_positives']} {'PASS' if r['passed'] else 'FAIL'}", flush=True)
    normals = []
    for s in (s for s in sessions if s.split == "test"):
        n = run_normal(s, cfg)
        normals.append(n)
        print(f"[normal] {s.id}: {len(n['confirmations'])} confirmations in "
              f"{s.seconds / 60:.1f} min", flush=True)
    stats = aggregate(runs, normals)
    boxes = gate_boxes(sessions, runs, normals, stats, problems, development())
    ok = all(b[1] for b in boxes)
    labels = sorted({s.label for s in sessions if s.split == "test"})
    meta = {"label": f"SIMULATION faults on {' + '.join(labels)} clips",
            "commit": code_revision(), "config": config_digest(cfg),
            "generated": time.strftime("%Y-%m-%d %H:%M:%S"),
            "wall_s": time.perf_counter() - t0, "overall": "PASS" if ok else "FAIL"}
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(render(meta, sessions, stats, boxes, runs, normals), encoding="utf-8",
                   newline="\n")
    out.with_suffix(".json").write_text(json.dumps(
        {"meta": meta, "gate": [{"box": b, "passed": ok_, "evidence": ev}
                                for b, ok_, ev in boxes],
         "detectors": stats, "sessions": [vars(s) for s in sessions],
         "normals": normals, "runs": runs}, indent=2, default=str), encoding="utf-8",
        newline="\n")
    print(f"wrote {out.name} (+ .json) overall={meta['overall']}")
    for b, ok_, ev in boxes:
        print(f"  {'PASS' if ok_ else 'FAIL'}  {b}: {ev}")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
