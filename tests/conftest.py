from datetime import UTC, datetime

import pytest

from reliability_agent.config import load_config
from reliability_agent.contracts.models import (
    GeometryMetrics,
    TaskMetrics,
    TelemetryWindow,
    TransportMetrics,
    VisualMetrics,
)

HEALTHY_VISUAL = dict(
    brightness_p50=110.0, contrast_p50=45.0, black_pixel_ratio=0.01, white_pixel_ratio=0.01,
    laplacian_variance_p50=400.0, blur_effect_p50=0.25, edge_density_p50=0.08,
    temporal_mse_p50=12.0, repeated_hash_ratio=0.0, exact_repeat_ratio=0.0, loop_period=None,
    occluded_cell_ratio=0.0,
)


def make_window(transport=None, visual=None, geometry=None, task=None, camera_id="cam"):
    tr = dict(capture_fps=30.0, frame_age_ms_p95=40.0, connected=True)
    tr.update(transport or {})
    vi = dict(HEALTHY_VISUAL)
    vi.update(visual or {})
    ge = dict(match_count=200, homography_inlier_ratio=0.9, translation_px=1.0, rotation_deg=0.1)
    ge.update(geometry or {})
    ta = dict(success_rate=1.0, confidence_p50=0.9, latency_ms_p95=5.0)
    ta.update(task or {})
    return TelemetryWindow(
        camera_id=camera_id, window_start=datetime.now(UTC), window_seconds=1.0,
        frames_analyzed=5, transport=TransportMetrics(**tr), visual=VisualMetrics(**vi),
        geometry=GeometryMetrics(**ge), task=TaskMetrics(**ta),
    )


@pytest.fixture
def cfg():
    return load_config(env=False)


@pytest.fixture
def window():
    return make_window
