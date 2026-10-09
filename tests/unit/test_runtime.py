"""`run_live` must analyse each captured frame once: `buffer.latest()` keeps returning the same
`Frame` while the source is slower than `analytic_fps`, and judging it twice reads as a bit-exact
repeat (false `freeze`). SIMULATION: a SyntheticSource that blocks in read() like OpenCV does."""

import time

import pytest

from reliability_agent import runtime
from reliability_agent.capture.sources import SyntheticSource
from reliability_agent.config import load_config


class SlowSource(SyntheticSource):
    """Delivers a new frame every `period` seconds, blocking in read() like cv2.VideoCapture."""

    kind = "rtsp"

    def __init__(self, uri, period: float = 0.5) -> None:
        super().__init__(width=160, height=120, noise_sigma=2.0)
        self.period = period

    def read(self):
        time.sleep(self.period)
        return super().read()


@pytest.fixture
def live_cfg(tmp_path, monkeypatch):
    monkeypatch.delenv("NEBIUS_API_KEY", raising=False)
    cfg = load_config(env=False)
    cfg["storage"]["db_path"] = str(tmp_path / "events.db")
    cfg["camera"]["analytic_fps"] = 10
    cfg["window"]["seconds"] = 1.0
    return cfg


def test_run_live_analyses_each_frame_once_on_a_slow_source(live_cfg, monkeypatch):
    sources = []

    def make(uri):
        src = SlowSource(uri, period=0.5)
        sources.append(src)
        return src

    monkeypatch.setattr(runtime, "OpenCVSource", make)
    windows = []
    runtime.run_live(live_cfg, duration_s=3.0, on_window=lambda tw, agent: windows.append(tw))

    analysed = sum(tw.frames_analyzed for tw in windows)
    delivered = sources[0]._seq
    assert windows and analysed > 0
    assert analysed <= delivered, (analysed, delivered)  # 10 polls/s on a 2 fps source
    assert all((tw.visual.exact_repeat_ratio or 0.0) == 0.0 for tw in windows)
