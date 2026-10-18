"""Live runtime: real camera -> capture worker -> probes -> MAPE-K agent (real hardware path)."""

from __future__ import annotations

import logging
import threading
import time
from collections.abc import Callable
from typing import Any

from reliability_agent.capture.sources import OpenCVSource
from reliability_agent.capture.worker import BackoffPolicy, CaptureWorker
from reliability_agent.config import api_key, load_config
from reliability_agent.contracts.models import TelemetryWindow
from reliability_agent.nemotron.budget import BudgetGuard
from reliability_agent.nemotron.planner import make_planner
from reliability_agent.orchestrator import CameraInUseError, ReliabilityAgent
from reliability_agent.probes.runner import ProbeRunner, WindowAggregator
from reliability_agent.storage.event_store import EventStore

log = logging.getLogger(__name__)


def run_live(cfg: dict | None = None, *, duration_s: float | None = None,
             on_window: Callable[[TelemetryWindow, ReliabilityAgent], None] | None = None,
             on_frame: Callable[[Any], None] | None = None,
             store: EventStore | None = None,
             stop_event: threading.Event | None = None) -> None:
    cfg = cfg or load_config()
    cam = cfg["camera"]
    owns_store = store is None
    store = store if store is not None else EventStore(cfg["storage"]["db_path"])
    budget = BudgetGuard.from_config(cfg, spent_usd=store.spent_usd())
    key = api_key()
    if key is None:
        log.warning("NEBIUS_API_KEY not set: running in LOCAL MODE (rule-based planner)")
    planner = make_planner(cfg, key, budget)
    source = OpenCVSource(cam["uri"])
    rc = cam["reconnect"]
    worker = CaptureWorker(source, cam["ring_buffer_size"], cam["frame_age_timeout_s"],
                           BackoffPolicy(rc["initial_backoff_s"], rc["max_backoff_s"],
                                         rc["jitter"]))
    agent = ReliabilityAgent(cfg, source, planner, store, restart_cb=worker.request_restart)
    runner = ProbeRunner(cfg)
    win_s = cfg["window"]["seconds"]
    fps = cam["analytic_fps"]
    t_end = time.monotonic() + duration_s if duration_s else None
    calibrated = False
    last_seq: int | None = None
    try:
        worker.start()
        while ((t_end is None or time.monotonic() < t_end)
               and not (stop_event and stop_event.is_set())):
            agg = WindowAggregator(cam["id"], win_s)
            t0 = time.monotonic()
            stopped = False
            while time.monotonic() - t0 < win_s:
                if stop_event and stop_event.is_set():
                    stopped = True
                    break
                time.sleep(1.0 / fps)
                if stop_event and stop_event.is_set():
                    stopped = True
                    break
                f = worker.buffer.latest()
                if f is None or f.seq == last_seq:
                    continue  # no new frame since the last poll: never judge the same pixels twice
                last_seq = f.seq
                if on_frame:
                    on_frame(f.image)
                if not calibrated:
                    runner.calibrate_reference(f)
                    calibrated = True
                agg.add(runner.analyse(f))
            if stopped:
                break
            tw = agg.emit(worker.meter.snapshot(), runner._geom_quality)
            agent.on_window(tw)
            if on_window:
                on_window(tw, agent)
            if agent.lease_lost:
                raise CameraInUseError(f"camera id {cam['id']!r} was taken over by another agent "
                                       f"on this event store; this agent stopped")
    finally:
        worker.stop()
        agent.checkpoint()
        agent.release_lease()
        if owns_store:
            store.close()
