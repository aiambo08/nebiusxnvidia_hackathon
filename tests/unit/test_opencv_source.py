"""OpenCVSource behaviour on undecodable frames, without hardware (fake cv2.VideoCapture)."""

import numpy as np
import pytest

from reliability_agent.capture import CaptureWorker, OpenCVSource
from reliability_agent.capture import sources as sources_mod
from reliability_agent.capture.base import CameraSource, Frame, SourceError, now


class _FakeCapture:
    """Scripted ``cv2.VideoCapture``: ``script`` is a sequence of booleans (True = decodable)."""

    script: list[bool] = []
    default: bool = True  # outcome of reads beyond the script

    def __init__(self, uri):
        self.uri = uri
        self.calls = 0
        self.released = False

    def isOpened(self):  # noqa: N802 - cv2 API
        return not self.released

    def read(self):
        i = self.calls
        self.calls += 1
        ok = self.script[i] if i < len(self.script) else self.default
        return (True, np.zeros((4, 4, 3), np.uint8)) if ok else (False, None)

    def get(self, prop):
        return 0.0

    def set(self, prop, value):
        return True

    def release(self):
        self.released = True


@pytest.fixture
def fake_capture(monkeypatch):
    def _install(script, default=True):
        _FakeCapture.script = list(script)
        _FakeCapture.default = default
        monkeypatch.setattr(sources_mod.cv2, "VideoCapture", _FakeCapture)

    return _install


@pytest.mark.parametrize(
    "uri,kind,network",
    [
        ("rtsp://10.0.0.2:8080/h264_ulaw.sdp", "rtsp", True),
        ("RTSPS://cam/live", "rtsp", True),
        ("http://10.0.0.2:8080/video", "http", True),
        ("clip.avi", "file", False),
        ("0", "webcam", False),
        (1, "webcam", False),
    ],
)
def test_kind_detection(uri, kind, network):
    src = OpenCVSource(uri)
    assert src.kind == kind
    assert src.is_network is network


def test_network_source_skips_undecodable_frames_and_counts_them(fake_capture):
    # warm-up consumes the first good frame; then 1 bad, 1 good, 2 bad, 1 good, always good
    fake_capture([True, False, True, False, False, True])
    src = OpenCVSource("rtsp://phone:8080/h264_ulaw.sdp", read_retries=3)
    src.open()
    frames = [src.read() for _ in range(45)]
    assert all(f is not None for f in frames), "retries must hide isolated bad frames"
    assert [f.seq for f in frames] == list(range(1, 46))
    assert src.decode_errors == 3
    src.close()
    assert not src.is_open


def test_network_source_gives_up_after_bounded_retries(fake_capture):
    fake_capture([True] + [False] * 4 + [True])
    src = OpenCVSource("rtsp://phone:8080/h264_ulaw.sdp", read_retries=3)
    src.open()  # warm-up takes the first good frame
    assert src.read() is None  # 1 read + 3 retries, all bad -> transient failure reported
    assert src.decode_errors == 3
    assert src.read() is not None  # stream recovers on the next call
    assert src._cap.calls == 6


def test_network_open_discards_startup_burst_until_first_decodable_frame(fake_capture):
    # IP Webcam H.264: the first frames fail until PPS/SPS + keyframe arrive (first_fail 0)
    fake_capture([False] * 7 + [True])
    src = OpenCVSource("rtsp://phone:8080/h264_ulaw.sdp", warmup_timeout_s=5.0)
    src.open()
    assert src.is_open
    assert src.warmup_frames == 7 and src.decode_errors == 7
    frames = [src.read() for _ in range(45)]
    assert all(f is not None for f in frames)
    assert [f.seq for f in frames] == list(range(1, 46))
    assert src.decode_errors == 7, "warm-up must not be double counted by read()"


def test_network_open_fails_when_no_decodable_frame_arrives(fake_capture):
    fake_capture([], default=False)
    src = OpenCVSource("rtsp://phone:8080/h264_ulaw.sdp", warmup_timeout_s=0.05)
    with pytest.raises(SourceError, match="no decodable frame"):
        src.open()
    assert not src.is_open
    assert src.warmup_frames >= 1


def test_file_and_webcam_do_not_warm_up(fake_capture):
    for uri in ("clip.avi", 0):
        fake_capture([False, True])
        src = OpenCVSource(uri)
        src.open()
        assert src.warmup_frames == 0 and src._cap.calls == 0


def test_file_and_webcam_never_retry(fake_capture):
    fake_capture([False, True])
    for uri in ("clip.avi", 0):
        _FakeCapture.script = [False, True]
        src = OpenCVSource(uri, read_retries=3)
        src.open()
        assert src.read() is None
        assert src.decode_errors == 0
        assert src._cap.calls == 1


def test_read_before_open_raises(fake_capture):
    fake_capture([])
    with pytest.raises(SourceError):
        OpenCVSource("rtsp://phone:8080/x").read()


class _CountingSource(CameraSource):
    kind = "fake"

    def __init__(self):
        self._open = False
        self.decode_errors = 0
        self.n = 0

    def open(self):
        self._open = True

    def close(self):
        self._open = False

    @property
    def is_open(self):
        return self._open

    def read(self):
        if not self._open:
            raise SourceError("closed")
        self.n += 1
        if self.n % 3 == 0:
            self.decode_errors += 1  # pretend one internal retry happened
        return Frame(np.zeros((2, 2, 3), np.uint8), self.n, now())


def test_worker_reports_source_decode_errors_in_transport_metrics():
    import time

    src = _CountingSource()
    w = CaptureWorker(src, buffer_size=4, max_fps=200)
    w.start()
    time.sleep(0.3)
    w.stop()
    snap = w.meter.snapshot()
    assert snap.decode_errors == src.decode_errors > 0
    assert snap.dropped_frames == 0  # skipped frames are decode errors, not sequence gaps
