"""Fault classification over telemetry windows + temporal fusion with hysteresis.

Detection is local and deterministic. Nemotron is only invoked by the orchestrator after the
tracker reports CONFIRMED.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from reliability_agent.baselines.robust import RobustBaseline
from reliability_agent.contracts.models import (
    Evidence,
    FaultType,
    Incident,
    IncidentState,
    TelemetryWindow,
)
from reliability_agent.incidents.state_machine import IncidentStateMachine

F = FaultType


# Ranking priority among faults with equal scores: the rule planner walks ``candidate_faults`` in
# order, so a frozen pipeline must outrank a co-occurring exposure fault even though freeze is now
# evaluated last (ADR-003). Transport faults come first because nothing else is measurable then.
_RANK_PRIORITY = {FaultType.STREAM_DOWN: 0, FaultType.LOW_FPS: 1, FaultType.FREEZE: 2}


def rank_faults(faults: dict[FaultType, float]) -> list[FaultType]:
    """Order candidate faults by score, then by actionability priority; the stable sort keeps the
    evaluation order (exposure before occlusion before blur) for the rest."""
    return sorted(faults, key=lambda f: (-faults[f], _RANK_PRIORITY.get(f, 9)))


def classify_window(
    tw: TelemetryWindow, baseline: RobustBaseline | None, rules: dict[str, Any]
) -> tuple[dict[FaultType, float], list[Evidence]]:
    """Return {fault: score in (0, 1]} and the evidence that triggered each rule."""
    t, v, g = tw.transport, tw.visual, tw.geometry
    faults: dict[FaultType, float] = {}
    ev: list[Evidence] = []

    def base(metric: str) -> float | None:
        return baseline.median(metric) if baseline else None

    def hit(fault: FaultType, metric: str, value: float | None, score: float = 1.0, note=""):
        faults[fault] = max(faults.get(fault, 0.0), min(1.0, score))
        ev.append(Evidence(metric=metric, value=value, baseline=base(metric), note=note or fault))

    r = rules
    # transport
    if not t.connected or t.frame_age_ms_p95 >= r["stream_down"]["frame_age_ms_min"]:
        hit(F.STREAM_DOWN, "transport.frame_age_ms_p95", t.frame_age_ms_p95)
        return faults, ev  # nothing else is measurable
    fps_base = base("transport.capture_fps")
    if fps_base and t.capture_fps < r["low_fps"]["fps_ratio_max"] * fps_base:
        hit(F.LOW_FPS, "transport.capture_fps", t.capture_fps)

    # content
    dark = (v.brightness_p50 is not None and v.brightness_p50 <= r["blackout"]["brightness_p50_max"]
            ) or (v.black_pixel_ratio or 0) >= r["blackout"]["black_pixel_ratio_min"]
    if dark:
        hit(F.BLACKOUT, "visual.brightness_p50", v.brightness_p50)
    if (v.white_pixel_ratio or 0) >= r["overexposure"]["white_pixel_ratio_min"]:
        hit(F.OVEREXPOSURE, "visual.white_pixel_ratio", v.white_pixel_ratio)

    occ = v.occluded_cell_ratio or 0
    if not dark and occ >= r["lens_occlusion"]["occluded_cell_ratio_min"]:
        hit(F.LENS_OCCLUSION, "visual.occluded_cell_ratio", occ, score=min(1.0, occ / 0.6))

    fr = r["focus_drift"]
    be = v.blur_effect_p50
    if be is not None and not dark and F.LENS_OCCLUSION not in faults:
        z = baseline.z("visual.blur_effect_p50", be) if baseline else None
        be_base = base("visual.blur_effect_p50")
        ed, ed_base = v.edge_density_p50, base("visual.edge_density_p50")
        edge_drop = (1 - ed / ed_base) if (ed is not None and ed_base) else 0.0
        worse = be_base is None or be > be_base
        if be >= fr["blur_effect_min"] or (
            worse and z is not None and z >= fr["blur_z_min"]
            and edge_drop >= fr["edge_density_drop_min"]
        ):
            hit(F.FOCUS_DRIFT, "visual.blur_effect_p50", be)

    # Freeze is judged last: it needs a scene that can carry sensor noise. Blackout crushes the
    # noise (pixels repeat, even bit-exactly, on a live camera) and strong blur removes the
    # high-frequency detail that makes perceptual hashes differ, so those faults explain the
    # missing motion (ADR-003). Perceptual-hash repeats are never freeze evidence, with or
    # without a temporal-noise collapse: a live static scene behind an H.264 encoder or an ISP
    # denoiser decodes with the same hashes and no fresh noise at all (ADR-005). Only bit-exact
    # repeats and loops count; the per-window noise figures ride along as diagnostic evidence.
    fz = r["freeze"]
    if not dark and (
        (v.exact_repeat_ratio or 0) >= fz["exact_repeat_ratio_min"] or (v.loop_period or 0) > 0
    ):
        hit(F.FREEZE, "visual.exact_repeat_ratio", v.exact_repeat_ratio,
            note="content frozen while transport connected")
        if v.loop_period:
            ev.append(Evidence(metric="visual.loop_period", value=v.loop_period,
                               note="frame sequence repeats with this period"))
        if v.noise_ratio_p50 is not None:
            ev.append(Evidence(metric="visual.noise_ratio_p50", value=v.noise_ratio_p50,
                               note="temporal / spatial noise of the repeated frames"))

    fv = r["fov_shift"]
    if (g.quality == "ok" and g.homography_inlier_ratio is not None
            and g.homography_inlier_ratio >= fv["inlier_ratio_min"]
            and ((g.translation_px or 0) >= fv["translation_px_min"]
                 or abs(g.rotation_deg or 0) >= fv["rotation_deg_min"])):
        hit(F.FOV_SHIFT, "geometry.translation_px", g.translation_px)
    return faults, ev


@dataclass
class TrackerStep:
    state: IncidentState
    faults: dict[FaultType, float]
    incident: Incident | None = None   # set only on the SUSPECT -> CONFIRMED edge
    baseline_learned: bool = False


@dataclass
class IncidentTracker:
    """Drives HEALTHY <-> SUSPECT -> CONFIRMED with persistence and hysteresis."""

    camera_id: str
    rules: dict[str, Any]
    enter_windows: int = 3
    exit_windows: int = 2
    cooldown_s: float = 20.0
    baseline: RobustBaseline = field(default_factory=RobustBaseline)
    fsm: IncidentStateMachine = field(default_factory=IncidentStateMachine)
    _bad: int = 0
    _good: int = 0
    _suppressed: dict[FaultType, float] = field(default_factory=dict)
    _evidence: list[Evidence] = field(default_factory=list)
    _scores: dict[FaultType, float] = field(default_factory=dict)

    def suppress(self, faults: list[FaultType], now_s: float) -> None:
        for f in faults:
            self._suppressed[f] = now_s + self.cooldown_s

    def _sample(self, tw: TelemetryWindow) -> dict[str, float]:
        return tw.flat()

    def step(self, tw: TelemetryWindow, now_s: float = 0.0) -> TrackerStep:
        faults, ev = classify_window(tw, self.baseline if self.baseline.ready else None,
                                     self.rules)
        faults = {f: s for f, s in faults.items() if self._suppressed.get(f, -1) <= now_s}
        state = self.fsm.state
        learned = False
        incident = None

        if state is IncidentState.HEALTHY:
            if faults:
                self.fsm.to(IncidentState.SUSPECT, ",".join(faults))
                self._bad, self._good = 1, 0
                self._scores, self._evidence = dict(faults), list(ev)
            else:
                learned = self.baseline.update(self._sample(tw), frozen=self.fsm.baseline_frozen)
        elif state is IncidentState.SUSPECT:
            if faults:
                self._bad += 1
                self._good = 0
                for f, s in faults.items():
                    self._scores[f] = max(self._scores.get(f, 0), s)
                self._evidence = list(ev)
                if self._bad >= self.enter_windows:
                    self.fsm.to(IncidentState.CONFIRMED, f"persisted {self._bad} windows")
                    incident = Incident(
                        camera_id=self.camera_id,
                        candidate_faults=rank_faults(faults),
                        fault_scores={str(k): round(v, 3) for k, v in self._scores.items()},
                        evidence=self._evidence,
                        baseline_ref=self.baseline.version,
                        telemetry=tw,
                    )
            else:
                self._good += 1
                if self._good >= self.exit_windows:
                    self.fsm.to(IncidentState.HEALTHY, "hysteresis exit")
                    self._bad = 0
        # Other states are driven by the orchestrator (MAPE-K Plan/Execute/Verify).
        return TrackerStep(self.fsm.state, faults, incident, learned)

    def reset_healthy(self) -> None:
        """Called by the orchestrator once an incident is closed and the camera is healthy."""
        self._bad = self._good = 0
        self._scores.clear()
        self._evidence.clear()
