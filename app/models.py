"""Cinema CI — Core Data Models.

Defines Pydantic models and schemas across creative contracts, artifacts,
build lifecycles, and verification results.
"""

from __future__ import annotations

import datetime
import enum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------

class TestStatus(str, enum.Enum):
    """Status classification for technical and creative evaluations."""
    PASS = "PASS"
    FAIL = "FAIL"
    REGRESSION = "REGRESSION"
    UNKNOWN = "UNKNOWN"


class BuildStatus(str, enum.Enum):
    """Build execution lifecycle states."""
    DRAFT = "DRAFT"
    ANALYZING_IMPACT = "ANALYZING_IMPACT"
    IMPACT_READY = "IMPACT_READY"
    APPROVED = "APPROVED"
    QUEUED = "QUEUED"
    GENERATING = "GENERATING"
    BUILDING = "BUILDING"
    TESTING = "TESTING"
    VALIDATING = "VALIDATING"
    PASSED = "PASSED"
    RELEASE_READY = "RELEASE_READY"
    APPROVED_FOR_RELEASE = "APPROVED_FOR_RELEASE"
    RELEASED = "RELEASED"
    BLOCKED = "BLOCKED"
    CANCELED = "CANCELED"
    INVESTIGATING = "INVESTIGATING"
    REPAIRING = "REPAIRING"
    REBUILDING = "REBUILDING"
    HUMAN_REVIEW = "HUMAN_REVIEW"


class RepairStatus(str, enum.Enum):
    """Autonomous agent repair states."""
    PENDING = "PENDING"
    IN_PROGRESS = "IN_PROGRESS"
    SUCCESS = "SUCCESS"
    FAILED = "FAILED"
    HUMAN_REVIEW = "HUMAN_REVIEW"


class EvaluatorType(str, enum.Enum):
    """Evaluator engine classifications."""
    FFPROBE = "ffprobe"
    FFMPEG = "ffmpeg"
    GEMINI_VIDEO = "gemini_video"


# ---------------------------------------------------------------------------
# Creative Contract Models (Parsed from cinema.yaml)
# ---------------------------------------------------------------------------

class CharacterSpec(BaseModel):
    """Specification for a character's visual and identity traits."""
    model_config = ConfigDict(extra="ignore")

    name: str
    description: str
    traits: dict[str, Any] = Field(default_factory=dict)


class PropSpec(BaseModel):
    """Specification for key scene props."""
    model_config = ConfigDict(extra="ignore")

    name: str
    description: str
    color: str | None = None


class ShotPropRule(BaseModel):
    """Rule defining whether a prop must appear in a specific shot."""
    model_config = ConfigDict(extra="ignore")

    present: bool = True


class ShotSpec(BaseModel):
    """Specification for an individual scene shot."""
    model_config = ConfigDict(extra="ignore")

    id: str
    description: str
    action: str = ""
    setting: str = ""
    camera: str = ""
    characters: list[str] = Field(default_factory=list)
    props: dict[str, ShotPropRule] = Field(default_factory=dict)
    duration_sec: float = 5.0


class ReleaseSpec(BaseModel):
    """Quality and technical constraints for theatrical release."""
    model_config = ConfigDict(extra="ignore")

    aspect_ratio: str = "16:9"
    min_resolution: str = "1280x720"
    target_fps: float = 24.0
    max_duration_sec: float = 20.0
    audio_required: bool = False


class ProjectSpec(BaseModel):
    """Top-level project metadata."""
    model_config = ConfigDict(extra="ignore")

    id: str
    title: str


class CinemaContract(BaseModel):
    """Creative contract loaded from cinema.yaml."""
    model_config = ConfigDict(extra="ignore")

    project: ProjectSpec
    release: ReleaseSpec
    characters: dict[str, CharacterSpec] = Field(default_factory=dict)
    props: dict[str, PropSpec] = Field(default_factory=dict)
    shots: list[ShotSpec] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Test Results & Evaluation Evidence
# ---------------------------------------------------------------------------

class BuildLogEntry(BaseModel):
    """Structured log event emitted during build execution."""
    model_config = ConfigDict(extra="ignore")

    timestamp: str = Field(
        default_factory=lambda: datetime.datetime.now(datetime.timezone.utc).isoformat()
    )
    level: str = "INFO"  # "INFO" | "WARNING" | "ERROR"
    stage: str = "PIPELINE"  # "SETUP" | "GENERATE" | "EVALUATE" | "REGRESSION" | "QUALITY_GATE"
    shot_id: str | None = None
    message: str = ""
    details: dict[str, Any] | None = None


class TestEvidence(BaseModel):
    """Granular evidence item supporting an evaluation outcome."""
    model_config = ConfigDict(extra="ignore")

    timestamp: str = ""
    description: str = ""


class TestResult(BaseModel):
    """Result of an individual technical or creative evaluation test."""
    model_config = ConfigDict(extra="ignore")

    test_id: str
    build_id: str
    scope: str  # shot_id or "release"
    category: str  # "creative" | "technical"
    evaluator: str  # e.g., "ffprobe", "gemini_video"
    evaluator_model: str | None = None  # e.g., "gemini-3.8-flash"
    evaluated_at: str = ""
    expected: str
    observed: str
    status: TestStatus
    confidence: float = 1.0
    evidence: list[TestEvidence] = Field(default_factory=list)
    error_details: str | None = None


# ---------------------------------------------------------------------------
# Artifacts & Build State
# ---------------------------------------------------------------------------

class ShotArtifact(BaseModel):
    """Generated or reused video shot artifact."""
    model_config = ConfigDict(extra="ignore")

    shot_id: str
    video_path: str
    generated_at: str = ""
    prompt_used: str = ""
    version: int = 1
    sha256: str = ""  # SHA-256 digest proving incremental reuse
    status: str = ""  # "generated" | "reused_from_baseline" | "failed"
    reused_from_build: str | None = None
    generation_duration_sec: float = 0.0
    model_used: str = ""
    error: str | None = None


class DeliverableArtifact(BaseModel):
    """Non-shot deliverable artifact (e.g. promotional poster, key visual)."""
    model_config = ConfigDict(extra="ignore")

    artifact_id: str
    artifact_type: str = ""  # "poster" | "key_visual"
    file_path: str = ""
    sha256: str = ""
    status: str = ""  # "generated" | "reused_from_baseline" | "failed"
    reused_from_build: str | None = None
    version: int = 1
    generated_at: str = ""
    model_used: str = ""
    details: dict[str, Any] = Field(default_factory=dict)


class Build(BaseModel):
    """Complete record of a Cinema CI build run."""
    model_config = ConfigDict(extra="ignore")

    build_id: str
    project_id: str
    baseline_build_id: str | None = None
    status: BuildStatus = BuildStatus.QUEUED
    created_at: str = Field(
        default_factory=lambda: datetime.datetime.now(datetime.timezone.utc).isoformat()
    )
    shots: list[ShotArtifact] = Field(default_factory=list)
    deliverables: list[DeliverableArtifact] = Field(default_factory=list)
    test_results: list[TestResult] = Field(default_factory=list)
    tests_total: int = 0
    tests_passed: int = 0
    creative_tests_total: int = 0
    creative_tests_passed: int = 0
    technical_tests_total: int = 0
    technical_tests_passed: int = 0
    regressions: int = 0
    unknowns: int = 0
    build_duration_sec: float = 0.0

    # Operations & Incremental Metrics
    operations_total: int = 0
    operations_rebuilt: int = 0
    operations_reused: int = 0
    operations_avoided: int = 0
    savings_percent: float = 0.0

    trace_id: str = ""  # OpenTelemetry distributed trace ID
    span_id: str = ""   # OpenTelemetry span ID for span linking
    spans: list[dict[str, Any]] = Field(default_factory=list)
    release_ready: bool = False
    is_released: bool = False
    repair_attempts: int = 0
    repair_of: str | None = None
    error_summary: str | None = None
    logs: list[BuildLogEntry] = Field(default_factory=list)
    master_film_path: str | None = None
    impact_plan: dict[str, Any] | None = None


class ReleaseRecord(BaseModel):
    """Immutable production release record promoted through human approval."""
    model_config = ConfigDict(extra="ignore")

    release_id: str
    build_id: str
    project_id: str
    film_path: str
    manifest_version: int = 1
    baseline_release_id: str | None = None
    rebuilt_count: int = 0
    reused_count: int = 0
    avoided_operations: int = 0
    savings_percent: float = 0.0
    approved_at: str = Field(
        default_factory=lambda: datetime.datetime.now(datetime.timezone.utc).isoformat()
    )
    released_at: str = Field(
        default_factory=lambda: datetime.datetime.now(datetime.timezone.utc).isoformat()
    )
    notes: str = ""


# ---------------------------------------------------------------------------
# Repair & Agent Models
# ---------------------------------------------------------------------------

class RepairAction(BaseModel):
    """Autonomous surgical repair task definition."""
    model_config = ConfigDict(extra="ignore")

    repair_id: str
    project_id: str
    source_build_id: str
    shot_id: str
    trigger: str = "grafana_alert"
    root_cause: str = ""
    action: str = "regenerate_shot"
    status: RepairStatus = RepairStatus.PENDING
    result_build_id: str | None = None
    created_at: str = Field(
        default_factory=lambda: datetime.datetime.now(datetime.timezone.utc).isoformat()
    )


class AgentStep(BaseModel):
    """Individual action step in an agent workflow for real-time streaming."""
    model_config = ConfigDict(extra="ignore")

    step_id: int = 0
    action: str = ""
    detail: str = ""
    tool_name: str = ""
    tool_input: dict[str, Any] = Field(default_factory=dict)
    tool_output: str = ""
    timestamp: str = Field(
        default_factory=lambda: datetime.datetime.now(datetime.timezone.utc).isoformat()
    )
    done: bool = False


class GenerationResult(BaseModel):
    """Output from video generator execution."""
    model_config = ConfigDict(extra="ignore")

    shot_id: str
    video_path: str
    success: bool
    error: str | None = None
    duration_sec: float = 0.0
