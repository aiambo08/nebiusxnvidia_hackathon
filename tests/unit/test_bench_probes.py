"""scripts/bench_probes.py: the F3 probe-latency benchmark and its gap-attribution flags."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))

import bench_probes  # noqa: E402

from reliability_agent.probes import runner as runner_mod  # noqa: E402

STAGES = {"downscale", "exposure_probe", "sharpness_probe", "occlusion_probe", "freeze",
          "geometry", "task"}


def test_isolated_run_reports_percentiles_against_the_gate():
    r = bench_probes.run((320, 240), n=6)
    assert r["n"] == 6 and r["size"] == "320x240"
    assert r["p50_ms"] <= r["p95_ms"] and r["gate_ms"] == 40.0
    assert r["gate_pass"] == (r["p95_ms"] <= 40.0)
    assert not r["paced"] and not r["worker"] and not r["tracemalloc"]
    assert r["breakdown_p95_ms"] == {}
    assert r["machine"]["cpus"] and r["machine"]["opencv"]


def test_breakdown_times_every_stage_inside_the_real_analyse_and_restores_the_module():
    original = runner_mod.exposure_probe
    r = bench_probes.run((320, 240), n=6, breakdown=True)
    assert set(r["breakdown_p95_ms"]) == STAGES
    assert all(v >= 0 for v in r["breakdown_p95_ms"].values())
    assert runner_mod.exposure_probe is original


def test_worker_mode_paces_and_pulls_frames_from_a_live_buffer():
    r = bench_probes.run((320, 240), n=3, worker=True)
    assert r["worker"] and r["paced"] and r["n"] == 3


def test_tracemalloc_mode_stops_tracing_afterwards():
    import tracemalloc

    bench_probes.run((320, 240), n=3, trace=True)
    assert not tracemalloc.is_tracing()


def test_report_names_the_conditions_and_the_verdict():
    r = bench_probes.run((320, 240), n=3, paced=True, breakdown=True)
    text = bench_probes.format_report(r)
    assert "probes 320x240 (paced, n=3)" in text and "gate <= 40 ms" in text
    assert "per-probe p95 ms:" in text and "machine: cpus=" in text


@pytest.mark.parametrize("argv", [[], ["--size", "320x240", "--frames", "3", "--breakdown"]])
def test_cli_never_fails_the_build_on_a_slow_machine(argv, capsys):
    argv = argv or ["--size", "320x240", "--frames", "3"]
    assert bench_probes.main(argv) == 0
    assert "p95=" in capsys.readouterr().out
