"""Child process used by the F7 crash-recovery integration test."""

from __future__ import annotations

import argparse
import json
import os
import threading
from datetime import UTC, datetime
from pathlib import Path

from reliability_agent.capture.sources import SyntheticSource
from reliability_agent.contracts.models import (
    GeometryMetrics,
    TaskMetrics,
    TelemetryWindow,
    TransportMetrics,
    VisualMetrics,
)
from reliability_agent.nemotron.planner import RuleBasedPlanner
from reliability_agent.orchestrator import ReliabilityAgent
from reliability_agent.storage import EventStore

HEALTHY_VISUAL = {
    "brightness_p50": 110.0,
    "contrast_p50": 45.0,
    "black_pixel_ratio": 0.01,
    "white_pixel_ratio": 0.01,
    "laplacian_variance_p50": 400.0,
    "blur_effect_p50": 0.25,
    "edge_density_p50": 0.08,
    "temporal_mse_p50": 12.0,
    "noise_ratio_p50": 1.0,
    "temporal_sigma_p50": 2.0,
    "repeated_hash_ratio": 0.0,
    "exact_repeat_ratio": 0.0,
    "loop_period": None,
    "occluded_cell_ratio": 0.0,
}


def _write_kill_marker(marker_path: Path, kill_point: str) -> None:
    temporary_path = marker_path.with_suffix(".tmp")
    temporary_path.write_text(
        json.dumps({"kill_point": kill_point}),
        encoding="utf-8",
    )
    os.replace(temporary_path, marker_path)


class FileBackedDevice(SyntheticSource):
    """SyntheticSource controls whose settings survive process death."""

    def __init__(
        self,
        settings_path: Path,
        *,
        kill_point: str | None = None,
        marker_path: Path | None = None,
    ) -> None:
        super().__init__(width=64, height=48)
        self.settings_path = settings_path
        self.kill_point = kill_point
        self.marker_path = marker_path
        self._blocked = False
        self._release = threading.Event()
        if settings_path.exists():
            self.settings = json.loads(settings_path.read_text(encoding="utf-8"))
        else:
            self._persist()

    def _persist(self) -> None:
        self.settings_path.write_text(
            json.dumps(self.settings, sort_keys=True),
            encoding="utf-8",
        )

    def _block(self) -> None:
        if self._blocked:
            return
        self._blocked = True
        assert self.marker_path is not None
        _write_kill_marker(self.marker_path, self.kill_point)
        self._release.wait()

    def apply_settings(self, settings: dict) -> None:
        super().apply_settings(settings)
        self._persist()
        if self.kill_point == "mid_apply" and "exposure" in settings:
            self._block()


class BlockingEventStore:
    """EventStore wrapper that pauses at one test-only crash checkpoint."""

    def __init__(self, store: EventStore, kill_point: str, marker_path: Path) -> None:
        self._store = store
        self._kill_point = kill_point
        self._marker_path = marker_path
        self._blocked = False
        self._release = threading.Event()

    def __getattr__(self, name: str):
        return getattr(self._store, name)

    def _block(self) -> None:
        if self._blocked:
            return
        self._blocked = True
        _write_kill_marker(self._marker_path, self._kill_point)
        self._release.wait()

    def save_snapshot(self, execution_id: str, incident_id: str, action: str,
                      snapshot: dict) -> None:
        self._store.save_snapshot(execution_id, incident_id, action, snapshot)
        if self._kill_point == "after_snapshot":
            self._block()

    def append(self, *args, **kwargs):
        event = self._store.append(*args, **kwargs)
        kind = args[0] if args else kwargs.get("kind")
        payload = args[1] if len(args) > 1 else kwargs.get("payload")
        if (
            self._kill_point == "verifying"
            and kind == "state"
            and isinstance(payload, dict)
            and str(payload.get("to")) == "VERIFYING"
        ):
            self._block()
        return event


def telemetry_window(camera_id: str, *, dark: bool = False) -> TelemetryWindow:
    visual = dict(HEALTHY_VISUAL)
    if dark:
        visual.update(brightness_p50=5.0, black_pixel_ratio=0.95)
    return TelemetryWindow(
        camera_id=camera_id,
        window_start=datetime.now(UTC),
        window_seconds=1.0,
        frames_analyzed=5,
        transport=TransportMetrics(capture_fps=30.0, frame_age_ms_p95=40.0),
        visual=VisualMetrics(**visual),
        geometry=GeometryMetrics(
            match_count=200,
            homography_inlier_ratio=0.9,
            translation_px=1.0,
            rotation_deg=0.1,
        ),
        task=TaskMetrics(success_rate=1.0, confidence_p50=0.9, latency_ms_p95=5.0),
    )


def run(args: argparse.Namespace) -> None:
    cfg = json.loads(Path(args.config).read_text(encoding="utf-8"))
    db_path = Path(args.db)
    device_path = Path(args.device)
    marker_path = Path(args.marker)
    store = EventStore(db_path)
    device = FileBackedDevice(
        device_path,
        kill_point=args.kill_point,
        marker_path=marker_path,
    )
    wrapped_store = BlockingEventStore(store, args.kill_point, marker_path)
    agent = ReliabilityAgent(cfg, device, RuleBasedPlanner(), wrapped_store)

    for _ in range(25):
        agent.on_window(telemetry_window(cfg["camera"]["id"]))
    if not agent.tracker.baseline.ready:
        raise RuntimeError("baseline did not become ready during warm-up")

    for _ in range(cfg["fusion"]["enter_windows"]):
        agent.on_window(telemetry_window(cfg["camera"]["id"], dark=True))

    raise RuntimeError(f"kill point was not reached: {args.kill_point}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", required=True)
    parser.add_argument("--db", required=True)
    parser.add_argument("--device", required=True)
    parser.add_argument("--marker", required=True)
    parser.add_argument(
        "--kill-point",
        choices=("after_snapshot", "mid_apply", "verifying"),
        required=True,
    )
    run(parser.parse_args())


if __name__ == "__main__":
    main()
