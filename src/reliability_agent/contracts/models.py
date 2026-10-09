"""Versioned data contracts (schema_version 1.0).

Owned by the Architecture role. Any change requires an ADR. These models mirror the JSON
contracts in the technical report: telemetry window, confirmed incident, Nemotron plan and
action result.
"""

from __future__ import annotations

import math
import uuid
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator

SCHEMA_VERSION = "1.0"


def utcnow() -> datetime:
    return datetime.now(UTC)


class FaultType(StrEnum):
    BLACKOUT = "blackout"
    OVEREXPOSURE = "overexposure"
    FOCUS_DRIFT = "focus_drift"
    MOTION_BLUR = "motion_blur"
    FREEZE = "freeze"
    LENS_OCCLUSION = "lens_occlusion"
    FOV_SHIFT = "fov_shift"
    LOW_FPS = "low_fps"
    STREAM_DOWN = "stream_down"
    PIPELINE_SATURATION = "pipeline_saturation"
    UNKNOWN = "unknown"


class ActionName(StrEnum):
    RESTART_CAPTURE = "restart_capture"
    SWITCH_STREAM_PROFILE = "switch_stream_profile"
    SET_EXPOSURE_BOUNDED = "set_exposure_bounded"
    TRIGGER_AUTOFOCUS = "trigger_autofocus"
    ENTER_SAFE_MODE = "enter_safe_mode"
    REQUEST_MANUAL_CLEANING = "request_manual_cleaning"
    REQUEST_RECALIBRATION = "request_recalibration"
    NEEDS_HUMAN = "needs_human"


class IncidentState(StrEnum):
    HEALTHY = "HEALTHY"
    SUSPECT = "SUSPECT"
    CONFIRMED = "CONFIRMED"
    SAFE_MODE = "SAFE_MODE"
    DIAGNOSING = "DIAGNOSING"
    PLANNED = "PLANNED"
    REJECTED = "REJECTED"
    ACTING = "ACTING"
    FAILED = "FAILED"
    VERIFYING = "VERIFYING"
    ROLLING_BACK = "ROLLING_BACK"
    ROLLED_BACK = "ROLLED_BACK"
    RECOVERED = "RECOVERED"
    NEEDS_HUMAN = "NEEDS_HUMAN"
    CLOSED = "CLOSED"


class VerificationStatus(StrEnum):
    COMMITTED = "committed"
    ROLLED_BACK = "rolled_back"
    INCONCLUSIVE = "inconclusive"
    EXECUTION_FAILED = "execution_failed"
    NOT_RUN = "not_run"


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=False)


# ---------------------------------------------------------------- telemetry


class TransportMetrics(_Strict):
    capture_fps: float = Field(ge=0)
    frame_age_ms_p95: float = Field(ge=0)
    dropped_frames: int = Field(ge=0, default=0)
    reconnect_count: int = Field(ge=0, default=0)
    decode_errors: int = Field(ge=0, default=0)
    connected: bool = True


class VisualMetrics(_Strict):
    brightness_p50: float | None = None
    contrast_p50: float | None = None
    black_pixel_ratio: float | None = None
    white_pixel_ratio: float | None = None
    laplacian_variance_p50: float | None = None
    blur_effect_p50: float | None = None
    edge_density_p50: float | None = None
    temporal_mse_p50: float | None = None
    repeated_hash_ratio: float | None = None
    exact_repeat_ratio: float | None = None
    noise_ratio_p50: float | None = None  # temporal / spatial sensor noise (ADR-005)
    loop_period: int | None = None
    occluded_cell_ratio: float | None = None


class GeometryMetrics(_Strict):
    match_count: int | None = None
    homography_inlier_ratio: float | None = None
    translation_px: float | None = None
    rotation_deg: float | None = None
    quality: str = "ok"  # ok | low_texture | no_reference | failed


class TaskMetrics(_Strict):
    name: str = "reference_marker_detection"
    success_rate: float | None = Field(default=None, ge=0, le=1)
    confidence_p50: float | None = Field(default=None, ge=0, le=1)
    latency_ms_p95: float | None = Field(default=None, ge=0)


class TelemetryWindow(_Strict):
    schema_version: str = SCHEMA_VERSION
    camera_id: str
    window_start: datetime
    window_seconds: float = Field(gt=0)
    frames_analyzed: int = Field(ge=0)
    transport: TransportMetrics
    visual: VisualMetrics
    geometry: GeometryMetrics = Field(default_factory=GeometryMetrics)
    task: TaskMetrics = Field(default_factory=TaskMetrics)

    def flat(self) -> dict[str, float]:
        """Flatten numeric metrics as ``section.field`` -> value (None dropped)."""
        out: dict[str, float] = {}
        for section in ("transport", "visual", "geometry", "task"):
            for key, val in getattr(self, section).model_dump().items():
                if isinstance(val, bool):
                    out[f"{section}.{key}"] = float(val)
                elif isinstance(val, (int, float)) and val is not None:
                    out[f"{section}.{key}"] = float(val)
        return out


# ---------------------------------------------------------------- incident


class Evidence(_Strict):
    metric: str
    value: float | None
    baseline: float | None = None
    z_score: float | None = None
    note: str = ""


class Incident(_Strict):
    schema_version: str = SCHEMA_VERSION
    incident_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    camera_id: str
    state: IncidentState = IncidentState.CONFIRMED
    opened_at: datetime = Field(default_factory=utcnow)
    candidate_faults: list[FaultType]
    fault_scores: dict[str, float] = Field(default_factory=dict)
    evidence: list[Evidence] = Field(default_factory=list)
    baseline_ref: str | None = None
    current_config: dict[str, Any] = Field(default_factory=dict)
    capabilities: list[str] = Field(default_factory=list)
    allowed_actions: list[ActionName] = Field(default_factory=list)
    telemetry: TelemetryWindow | None = None
    budget_remaining_usd: float | None = None


# ---------------------------------------------------------------- plan


class PlanAction(_Strict):
    name: ActionName
    arguments: dict[str, Any] = Field(default_factory=dict)


class VerificationSpec(_Strict):
    window_seconds: float = Field(default=15, gt=0, le=120)
    primary_metric: str = "task.success_rate"
    minimum_relative_improvement: float = Field(default=0.10, ge=0, le=10)
    guard_metrics: list[str] = Field(
        default_factory=lambda: ["transport.capture_fps", "task.latency_ms_p95"]
    )


class NemotronPlan(_Strict):
    schema_version: str = SCHEMA_VERSION
    diagnosis: FaultType
    confidence: float = Field(ge=0, le=1)
    evidence_refs: list[str] = Field(default_factory=list, max_length=12)
    alternatives: list[FaultType] = Field(default_factory=list, max_length=4)
    action: PlanAction
    verification: VerificationSpec = Field(default_factory=VerificationSpec)
    human_message: str = Field(default="", max_length=400)

    @field_validator("confidence")
    @classmethod
    def _finite(cls, v: float) -> float:
        if not math.isfinite(v):
            raise ValueError("confidence must be finite")
        return v


# ---------------------------------------------------------------- results


class TokenUsage(_Strict):
    model: str | None = None
    prompt_version: str | None = None
    input_tokens: int = 0
    output_tokens: int = 0
    estimated_cost_usd: float = 0.0
    latency_ms: float | None = None
    cached: bool = False


class ActionResult(_Strict):
    incident_id: str
    action: ActionName
    arguments: dict[str, Any] = Field(default_factory=dict)
    previous_state: dict[str, Any] = Field(default_factory=dict)
    execution_status: str  # success | failed | rejected | skipped
    verification_status: VerificationStatus = VerificationStatus.NOT_RUN
    before: dict[str, float] = Field(default_factory=dict)
    after: dict[str, float] = Field(default_factory=dict)
    reasons: list[str] = Field(default_factory=list)
    rollback_available: bool = True
    token_usage: TokenUsage = Field(default_factory=TokenUsage)
