"""Same contract for every CameraSource (F2). Webcam/RTSP variants run only when available."""

import os

import cv2
import numpy as np
import pytest

from reliability_agent.capture import OpenCVSource, SyntheticSource
from reliability_agent.capture.base import SourceError


@pytest.fixture(scope="module")
def video_file(tmp_path_factory):
    path = tmp_path_factory.mktemp("vid") / "clip.avi"
    src = SyntheticSource(width=320, height=240, seed=3)
    src.open()
    vw = cv2.VideoWriter(str(path), cv2.VideoWriter_fourcc(*"MJPG"), 15, (320, 240))
    for _ in range(30):
        vw.write(src.read().image)
    vw.release()
    return path


def _sources(video_file):
    yield "synthetic", SyntheticSource(width=320, height=240)
    yield "file", OpenCVSource(str(video_file), loop_file=True)
    if os.environ.get("RA_TEST_WEBCAM"):
        yield "webcam", OpenCVSource(int(os.environ["RA_TEST_WEBCAM"]))
    if os.environ.get("RA_TEST_RTSP"):
        yield "rtsp", OpenCVSource(os.environ["RA_TEST_RTSP"])


def test_source_contract(video_file):
    for name, src in _sources(video_file):
        with pytest.raises(SourceError):
            src.read()  # reading before open() must fail loudly
        src.open()
        assert src.is_open, name
        seqs = []
        for _ in range(45):  # more than file length -> exercises looping
            f = src.read()
            assert f is not None, name
            assert f.image.dtype == np.uint8 and f.image.ndim == 3, name
            seqs.append(f.seq)
        assert seqs == sorted(seqs) and len(set(seqs)) == len(seqs), name
        src.close()
        assert not src.is_open, name


def test_missing_file_raises():
    with pytest.raises(SourceError):
        OpenCVSource("does/not/exist.avi").open()
