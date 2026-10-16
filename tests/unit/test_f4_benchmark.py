"""F4 dataset + benchmark tooling: session index, manifests, degraded clips, one-command report."""

import json
from types import SimpleNamespace

import cv2
import numpy as np
import pytest
import run_benchmark
import yaml

from benchmarks import build_manifests, dataset, make_degraded
from benchmarks.injectors.faults import apply_stream
from benchmarks.replay import replay
from reliability_agent.capture.base import Frame
from reliability_agent.capture.sources import SyntheticSource
from reliability_agent.config import load_config

FPS = 5.0


def _clip(path, seconds, seed=0, size=(320, 240)):
    src = SyntheticSource(width=size[0], height=size[1], seed=seed, noise_sigma=2.0)
    src.open()
    vw = cv2.VideoWriter(str(path), cv2.VideoWriter_fourcc(*"MJPG"), FPS, size)
    n = int(seconds * FPS)
    for _ in range(n):
        vw.write(src.read().image)
    vw.release()
    src.close()
    return n


@pytest.fixture
def sandbox(tmp_path, monkeypatch):
    data = tmp_path / "benchmarks" / "data"
    data.mkdir(parents=True)
    man = tmp_path / "benchmarks" / "manifests"
    man.mkdir(parents=True)
    monkeypatch.setattr(dataset, "ROOT", tmp_path)
    monkeypatch.setattr(dataset, "INDEX", man / "sessions.yaml")
    monkeypatch.setattr(dataset, "DATA", data)
    monkeypatch.setattr(build_manifests, "OUT", man / "f4")
    monkeypatch.setattr(make_degraded, "ROOT", tmp_path)
    monkeypatch.setattr(make_degraded, "F4_DIR", man / "f4")
    monkeypatch.setattr(make_degraded, "OUT_DIR", data / "degraded")
    monkeypatch.setattr(run_benchmark, "ROOT", tmp_path)
    make_degraded._DIGESTS.clear()
    return tmp_path


def _session(sid, split="test", seconds=100, seed=0):
    n = _clip(dataset.DATA / f"{sid}_clean.avi", seconds, seed)
    clip = dataset.DATA / f"{sid}_clean.avi"
    s = dataset.Session(id=sid, split=split, sha256=dataset.sha256(clip),
                        frames=n, fps=FPS, resolution=[320, 240], seconds=n / FPS,
                        conditions="synthetic", label="SIMULATION")
    dataset.add(s)
    return s


def _small_protocol(monkeypatch, faults=None):
    monkeypatch.setattr(build_manifests, "LEAD_S", 25.0)
    monkeypatch.setattr(build_manifests, "FAULT_S", 8.0)
    monkeypatch.setattr(build_manifests, "FAULTS", faults or {"dark": [1.0, 1.0, 1.0]})
    monkeypatch.setattr(build_manifests, "NEGATIVES", {"lighting_change": [1.0, 1.0, 1.0]})


# --- session index ---------------------------------------------------------------------------

def test_index_rejects_duplicates_bad_ids_and_bad_splits(sandbox):
    _session("s010", seconds=2)
    with pytest.raises(ValueError, match="already"):
        _session("s010", seconds=2)
    for bad in ("s1", "S010", "s010-x", "../s010"):
        with pytest.raises(ValueError):
            dataset.check_session_id(bad)
    with pytest.raises(ValueError, match="split"):
        dataset.validate([dataset.Session("s011", "train", "x", 1, 5.0, [1, 1], 1.0)])
    assert [s.id for s in dataset.load()] == ["s010"]


def test_verify_reports_missing_clip_and_changed_clip(sandbox):
    a, b = _session("s010", seconds=2), _session("s011", seconds=2, seed=1)
    assert dataset.verify([a, b]) == []
    (dataset.DATA / "s010_clean.avi").unlink()
    with (dataset.DATA / "s011_clean.avi").open("ab") as fh:
        fh.write(b"x")
    assert dataset.verify([a, b]) == ["s010: clip missing",
                                      "s011: sha256 mismatch (dataset changed)"]


@pytest.mark.parametrize("field, value", [
    ("conditions", "rtsp://192.168.1.20:8080/h264"), ("notes", "C:\\Users\\x\\clip.avi"),
    ("extra", {"uri": "http://x"}), ("extra", {"host": "10.0.0.2"})])
def test_index_rejects_uri_ip_or_path_in_any_metadata(field, value):
    s = dataset.Session("s011", "test", "x", 1, 5.0, [1, 1], 1.0, **{field: value})
    with pytest.raises(ValueError, match="URL"):
        dataset.validate([s])


def test_verify_reports_a_frame_count_that_differs_from_the_index(sandbox):
    s = _session("s010", seconds=2)
    s.frames += 1
    assert dataset.verify([s]) == [f"s010: decoder reports {s.frames - 1} frames, "
                                   f"index says {s.frames}"]


def test_index_holds_no_path_or_uri(sandbox):
    _session("s010", seconds=2)
    text = dataset.INDEX.read_text(encoding="utf-8")
    assert "rtsp" not in text and str(sandbox) not in text and "://" not in text


# --- manifests -------------------------------------------------------------------------------

def test_manifests_are_deterministic_and_only_for_test_sessions(sandbox):
    sessions = [_session("s010", "dev", seconds=61), _session("s011", seconds=180, seed=1),
                _session("s012", seconds=200, seed=2)]
    first = build_manifests.build(sessions)
    files = {p.name: p.read_text() for p in build_manifests.OUT.glob("*.yaml")}
    second = build_manifests.build(sessions)
    assert first == second
    assert files == {p.name: p.read_text() for p in build_manifests.OUT.glob("*.yaml")}
    kinds = len(build_manifests.FAULTS) + len(build_manifests.NEGATIVES)
    assert len(first) == 2 * kinds * build_manifests.SLOTS
    assert {m["session"] for m in first} == {"s011", "s012"}
    assert len({m["fault"]["seed"] for m in first}) == len(first)


def test_slots_do_not_overlap_and_fault_follows_the_lead_in(sandbox):
    s = _session("s012", seconds=200)
    ms = build_manifests.manifests_for(s)
    lead, fault = round(build_manifests.LEAD_S * FPS), round(build_manifests.FAULT_S * FPS)
    for m in ms:
        seg, fz = m["segment"], m["fault"]
        assert 0 <= seg["start_frame"] and seg["end_frame"] <= s.frames
        assert fz["start_frame"] == seg["start_frame"] + lead
        assert fz["end_frame"] == seg["end_frame"] == fz["start_frame"] + fault
    starts = sorted({m["segment"]["start_frame"] for m in ms})
    assert len(starts) == 3 and all(b - a >= lead + fault for a, b in zip(starts, starts[1:]))


def test_strengths_are_three_per_mvp_fault_and_map_to_mvp_detectors():
    assert set(build_manifests.FAULTS) == {"dark", "gaussian_blur", "freeze", "occlude_opaque",
                                           "overexpose"}
    assert all(len(v) == build_manifests.SLOTS for v in build_manifests.FAULTS.values())
    from benchmarks.replay import EXPECTED
    assert {str(EXPECTED[k]) for k in build_manifests.FAULTS} == set(run_benchmark.MVP)
    assert all(k not in EXPECTED for k in build_manifests.NEGATIVES)


@pytest.mark.parametrize("seconds", [30, 90, 179])
def test_session_too_short_for_three_non_overlapping_runs_is_refused(sandbox, seconds):
    s = _session("s010", seconds=seconds)
    with pytest.raises(ValueError, match="non-overlapping"):
        build_manifests.manifests_for(s)
    assert len(build_manifests.manifests_for(_session("s011", seconds=180))) > 0


def test_stale_manifests_are_removed(sandbox):
    build_manifests.OUT.mkdir(parents=True)
    (build_manifests.OUT / "f4-s099-dark-0.yaml").write_text("id: old\n")
    build_manifests.build([_session("s010", seconds=180)])
    assert not (build_manifests.OUT / "f4-s099-dark-0.yaml").exists()


# --- degraded clips --------------------------------------------------------------------------

def test_segment_frames_equal_the_fault_applied_to_the_full_clip(sandbox):
    s = _session("s010", seconds=180)
    m = build_manifests.manifests_for(s)[-1]  # last slot: segment starts mid-clip
    seg, fz = m["segment"], m["fault"]
    assert seg["start_frame"] > 0
    full = list(make_degraded.frames_of(s.clip))
    want = list(apply_stream(iter(full), fz["kind"], fz["start_frame"], fz["end_frame"],
                             fz["strength"], fz["seed"]))[seg["start_frame"]:seg["end_frame"]]
    got = list(make_degraded.degraded_frames(m))
    assert len(got) == len(want) == seg["end_frame"] - seg["start_frame"]
    assert all(np.array_equal(a, b) for a, b in zip(got, want))
    again = list(make_degraded.degraded_frames(m))
    assert all(np.array_equal(a, b) for a, b in zip(got, again))


def test_make_degraded_all_rebuilds_every_manifest_and_checks_hashes(sandbox, monkeypatch,
                                                                    capsys):
    _small_protocol(monkeypatch)
    build_manifests.build([_session("s010", seconds=100)])
    assert make_degraded.main(["--all"]) == 0
    built = sorted(p.stem for p in make_degraded.OUT_DIR.glob("*.avi"))
    assert built == sorted(p.stem for p in build_manifests.OUT.glob("*.yaml"))
    with (dataset.DATA / "s010_clean.avi").open("ab") as fh:
        fh.write(b"x")
    make_degraded._DIGESTS.clear()
    assert make_degraded.main(["--all"]) == 1
    assert "hash mismatch" in capsys.readouterr().err


def test_make_degraded_all_without_manifests_fails(sandbox):
    assert make_degraded.main(["--all"]) == 1


# --- replay re-arm ---------------------------------------------------------------------------

def test_rearm_counts_every_confirmation_of_a_persistent_fault():
    cfg = load_config(env=False)
    src = SyntheticSource(width=320, height=240, seed=0)
    src.open()
    clean = [src.read().image for _ in range(150)]
    src.close()
    frames = list(apply_stream(iter(clean + clean[:100]), "dark", 125, 250, 1.0, 0))
    once = replay(iter(frames), FPS, cfg)
    many = replay(iter(frames), FPS, cfg, rearm=True)
    assert len(once.confirmations) == 1 and once.confirmed_window is not None
    assert len(many.confirmations) > 1
    assert many.confirmations[0] == once.confirmations[0]
    assert all("blackout" in f for _, _, f in many.confirmations)


# --- one-command report ----------------------------------------------------------------------

def test_run_benchmark_end_to_end_report(sandbox, monkeypatch, capsys):
    _small_protocol(monkeypatch)
    _session("s010", "dev", seconds=2)
    _session("s011", seconds=100, seed=3)
    rc = run_benchmark.main(["--out-dir", str(sandbox / "reports"), "--name", "t"])
    out = capsys.readouterr().out
    assert rc == 1  # 3 runs per fault and < 30 normal minutes cannot pass the gate
    md = next((sandbox / "reports").glob("*-t.md")).read_text(encoding="utf-8")
    js = json.loads(next((sandbox / "reports").glob("*-t.json")).read_text(encoding="utf-8"))
    boxes = {g["box"]: g["passed"] for g in js["gate"]}
    assert boxes[">= 15 independent runs per MVP fault"] is False
    assert boxes[">= 30 min of normal conditions"] is False
    assert boxes["Split by session"] is True
    assert boxes["Dataset versioned by manifest + hashes"] is True
    assert boxes["No published metric from data reused as test"] is True
    dark = [r for r in js["runs"] if r["kind"] == "dark"]
    assert len(dark) == 3 and all(r["passed"] for r in dark)
    assert js["detectors"]["blackout"]["recall"] == 1.0
    assert {r["session"] for r in js["runs"]} == {"s011"}
    assert [n["session"] for n in js["normals"]] == ["s011"]
    assert "SIMULATION" in md and "overall: **FAIL**" in md and "FAIL" in out
    for text in (md, json.dumps(js)):
        assert str(sandbox) not in text and "://" not in text


def test_run_benchmark_flags_a_test_clip_used_during_development(sandbox, monkeypatch):
    _small_protocol(monkeypatch)
    s = _session("s011", seconds=100)
    (sandbox / "benchmarks" / "manifests" / "f1-s001-dark.yaml").write_text(
        yaml.safe_dump({"id": "f1", "source": {"sha256": s.sha256}}))
    run_benchmark.main(["--out-dir", str(sandbox / "reports")])
    js = json.loads(next((sandbox / "reports").glob("*.json")).read_text(encoding="utf-8"))
    leak = next(g for g in js["gate"] if g["box"].startswith("No published"))
    assert leak["passed"] is False and "s011" in leak["evidence"]


def test_run_benchmark_flags_a_test_session_reusing_a_development_session_id(sandbox, monkeypatch):
    _small_protocol(monkeypatch)
    _session("s001", seconds=100)
    (sandbox / "benchmarks" / "manifests" / "f1-s001-dark.yaml").write_text(
        yaml.safe_dump({"id": "f1", "session": "s001", "source": {"sha256": "other"}}))
    run_benchmark.main(["--out-dir", str(sandbox / "reports")])
    js = json.loads(next((sandbox / "reports").glob("*.json")).read_text(encoding="utf-8"))
    leak = next(g for g in js["gate"] if g["box"].startswith("No published"))
    assert leak["passed"] is False and "s001" in leak["evidence"]


def test_runs_box_needs_five_sessions_per_fault():
    stats = {f: {"runs": 18, "sessions": 4, "f1": 1.0} for f in run_benchmark.MVP}
    boxes = run_benchmark.gate_boxes([], [], [], stats, [], (set(), set()))
    assert boxes[0][1] is False and "sessions per fault" in boxes[0][2]
    stats = {f: {"runs": 15, "sessions": 5, "f1": 1.0} for f in run_benchmark.MVP}
    assert run_benchmark.gate_boxes([], [], [], stats, [], (set(), set()))[0][1] is True


def test_run_benchmark_refuses_a_changed_dataset_and_an_existing_report(sandbox, monkeypatch,
                                                                        capsys):
    _small_protocol(monkeypatch)
    assert run_benchmark.main(["--out-dir", str(sandbox / "r")]) == 2  # no test sessions
    _session("s011", seconds=100)
    (dataset.DATA / "s011_clean.avi").unlink()
    assert run_benchmark.main(["--out-dir", str(sandbox / "r")]) == 2
    assert "clip missing" in capsys.readouterr().err
    (sandbox / "r").mkdir()
    import time
    (sandbox / "r" / f"{time.strftime('%Y-%m-%d')}-f4.md").write_text("old")
    with pytest.raises(SystemExit):
        run_benchmark.main(["--out-dir", str(sandbox / "r")])


def test_aggregate_counts_normal_confirmations_as_false_positives():
    runs = [{"expected": "blackout", "passed": True, "session": "s1", "detection_delay_s": 1.0,
             "false_positives": []},
            {"expected": None, "passed": False, "session": "s1", "detection_delay_s": None,
             "false_positives": ["blackout"]}]
    normals = [{"confirmations": [{"t_s": 3.0, "faults": ["blackout", "focus_drift"]}]}]
    st = run_benchmark.aggregate(runs, normals)
    assert st["blackout"]["tp"] == 1 and st["blackout"]["fp"] == 2
    assert st["blackout"]["precision"] == pytest.approx(1 / 3)
    assert st["focus_drift"]["fp"] == 1 and st["focus_drift"]["f1"] == 0.0
    assert st["freeze"]["runs"] == 0 and st["freeze"]["f1"] == 0.0


# --- record_clip guards ----------------------------------------------------------------------

@pytest.mark.parametrize("extra, msg", [
    (["--session", "s1", "--split", "test"], "session id"),
    (["--session", "s010", "--split", "test", "--conditions", "cam at 192.168.1.20"], "IP"),
    (["--session", "s010", "--split", "test", "--conditions", "desk C:\\x"], "path"),
    (["--session", "s010", "--split", "test", "--conditions", "rtsp://x"], "URL"),
    (["--session", "s001", "--split", "test"], "building the detectors"),
    (["--session", "s010", "--split", "test", "--seconds", "179"], "--seconds must be"),
])
def test_record_clip_rejects_bad_session_metadata_before_opening_a_camera(extra, msg, monkeypatch,
                                                                          capsys):
    import record_clip
    monkeypatch.setattr("sys.argv", ["record_clip.py", "--uri", "999", *extra])
    with pytest.raises(SystemExit):
        record_clip.main()
    assert msg in capsys.readouterr().err


def test_record_clip_split_refuses_a_file_source(monkeypatch, capsys):
    import record_clip
    monkeypatch.setattr("sys.argv", ["record_clip.py", "--uri", "clip.avi", "--session", "s010",
                                     "--split", "test"])
    with pytest.raises(SystemExit):
        record_clip.main()
    assert "live camera" in capsys.readouterr().err


def test_public_metadata_error_names_the_refused_characters():
    with pytest.raises(ValueError, match="no ':'"):
        dataset.check_public("10:30 daylight")


class _FakeCamera:
    kind = "webcam"

    def __init__(self, uri):
        self.seq = 0

    def open(self):
        pass

    def close(self):
        pass

    def read(self):
        self.seq += 1
        return Frame(np.zeros((48, 64, 3), np.uint8), self.seq, 0.0)


def _fake_clock(step):
    t = [0.0]

    def monotonic():
        t[0] += step
        return t[0]
    return monotonic


@pytest.mark.parametrize("seconds, indexed", [("180", False), ("200", True)])
def test_record_clip_indexes_only_a_recording_long_enough_for_three_runs(
        sandbox, monkeypatch, capsys, seconds, indexed):
    import record_clip
    monkeypatch.setattr(record_clip, "REPO_ROOT", sandbox)
    monkeypatch.setattr(record_clip, "OpenCVSource", _FakeCamera)
    # ~9.65 FPS: 180 s give 1739 frames, but three runs at that rate need 1740
    monkeypatch.setattr(record_clip, "time", SimpleNamespace(monotonic=_fake_clock(0.1035)))
    monkeypatch.setattr("sys.argv", ["record_clip.py", "--uri", "0", "--session", "s010",
                                     "--split", "test", "--seconds", seconds])
    rc = record_clip.main()
    ids = [s.id for s in dataset.load()]
    if indexed:
        assert rc == 0 and ids == ["s010"]
    else:
        assert rc == 1 and ids == [] and "not added" in capsys.readouterr().err
