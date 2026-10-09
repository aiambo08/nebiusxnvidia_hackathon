"""`scripts/bench_detectors.py`: recall / precision per detector (F3, SIMULATION)."""

import bench_detectors as bench
import pytest

from benchmarks.replay import EXPECTED, ReplayResult, WindowResult, score
from reliability_agent.config import load_config
from reliability_agent.contracts.models import FaultType, IncidentState


@pytest.fixture(scope="module")
def cfg():
    return load_config(env=False)


def test_loops_are_graded_as_freeze():
    assert EXPECTED["loop4"] == FaultType.FREEZE and EXPECTED["loop8"] == FaultType.FREEZE


def test_score_treats_an_injector_without_expectation_as_a_negative_control(cfg):
    res = ReplayResult(windows=[WindowResult(0, 1.0, IncidentState.HEALTHY, [])])
    out = score(res, "lighting_change", 0.5, 5, cfg)
    assert out["expected"] is None and out["passed"] and out["detection_delay_s"] is None
    res.confirmed_window, res.confirmed_faults = 0, ["lens_occlusion"]
    assert not score(res, "lighting_change", 0.5, 5, cfg)["passed"]


@pytest.mark.parametrize("kind,expected", [("dark", "blackout"), ("freeze", "freeze")])
def test_run_confirms_the_expected_detector_after_onset(cfg, kind, expected):
    r = bench.run(kind, 1.0, seed=0, sigma=2.0, cfg=cfg, lead_s=6.0, fault_s=8.0)
    assert r["passed"] and r["expected"] == expected and r["false_positives"] == []
    assert 0 <= r["detection_delay_s"] <= 8.0


def test_run_clean_scene_confirms_nothing(cfg):
    r = bench.run(None, 0.0, seed=1, sigma=2.0, cfg=cfg, lead_s=6.0, fault_s=6.0)
    assert r["passed"] and r["confirmed_faults"] == [] and r["false_positives"] == []


def test_aggregate_counts_false_positives_against_the_wrong_detector():
    results = [
        {"expected": "blackout", "passed": True, "detection_delay_s": 2.0, "false_positives": []},
        {"expected": "blackout", "passed": False, "detection_delay_s": None,
         "false_positives": ["lens_occlusion"]},
        {"expected": None, "passed": False, "detection_delay_s": None,
         "false_positives": ["lens_occlusion"]},
        {"expected": "lens_occlusion", "passed": True, "detection_delay_s": 3.0,
         "false_positives": []},
    ]
    st = bench.aggregate(results)
    assert st["blackout"]["recall"] == 0.5 and st["blackout"]["precision"] == 1.0
    assert st["lens_occlusion"]["fp"] == 2
    assert st["lens_occlusion"]["precision"] == pytest.approx(1 / 3)
    assert not bench.gate_ok(st)
    good = {n: {"recall": 1.0, "precision": 1.0} for n in bench.GATED}
    assert bench.gate_ok(good)
    good["overexposure"] = {"recall": 1.0, "precision": 0.5}
    assert not bench.gate_ok(good), "precision gate applies to every detector"
