"""Cinema CI — Change Impact Intelligence Data Models.

Defines schemas for creative change requests, declared/observed typed dependencies,
reachability edges, and deterministic impact plans.
"""

from __future__ import annotations

import datetime
import enum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class ChangeType(str, enum.Enum):
    """Semantic category of creative changes."""
    VISUAL_ATTRIBUTE = "VISUAL_ATTRIBUTE"       # Wardrobe, color, haircut, lighting
    NARRATIVE_ACTION = "NARRATIVE_ACTION"       # Character movement, blocking, interactions
    AUDIO_PROPERTY = "AUDIO_PROPERTY"           # Soundtrack tone, score, Foley
    TEXT_DIALOGUE = "TEXT_DIALOGUE"             # Spoken lines, subtitle text
    PROP_SPEC = "PROP_SPEC"                     # Prop appearance, material, color
    CAMERA_DIRECTION = "CAMERA_DIRECTION"       # Camera angle, focal length, motion


class DependencyType(str, enum.Enum):
    """Typed dependency relationship between assets."""
    VISUAL_DEPENDENCY = "VISUAL_DEPENDENCY"
    NARRATIVE_DEPENDENCY = "NARRATIVE_DEPENDENCY"
    AUDIO_DEPENDENCY = "AUDIO_DEPENDENCY"
    TEXT_DEPENDENCY = "TEXT_DEPENDENCY"
    REFERENCE_DEPENDENCY = "REFERENCE_DEPENDENCY"
    ASSEMBLY_DEPENDENCY = "ASSEMBLY_DEPENDENCY"


class DependencyOrigin(str, enum.Enum):
    """Source origin of a dependency edge."""
    DECLARED = "declared"      # Defined statically in cinema.yaml
    OBSERVED = "observed"      # Discovered dynamically in Grafana Tempo traces


class AssetAction(str, enum.Enum):
    """Required execution action for an asset."""
    REBUILD = "REBUILD"
    REVALIDATE = "REVALIDATE"
    REUSE = "REUSE"


class CreativeChangeRequest(BaseModel):
    """Structured representation of a natural language creative change."""
    model_config = ConfigDict(extra="ignore")

    change_id: str = Field(
        default_factory=lambda: f"change_{int(datetime.datetime.now().timestamp())}"
    )
    raw_prompt: str = ""
    entity_id: str  # e.g. "character:marcus", "prop:envelope", "shot:shot_02"
    change_type: ChangeType = ChangeType.VISUAL_ATTRIBUTE
    property: str   # e.g. "coat", "color", "hair"
    old_value: str = ""
    new_value: str = ""
    description: str = ""


class DependencyEdge(BaseModel):
    """A directed dependency between assets or creative entities."""
    model_config = ConfigDict(extra="ignore")

    from_node: str               # e.g. "character:marcus", "shot_01:keyframe:v1"
    to_node: str                 # e.g. "shot_01", "poster"
    dependency_type: DependencyType
    origin: DependencyOrigin = DependencyOrigin.DECLARED
    trace_id: str | None = None
    span_id: str | None = None
    detail: str = ""


class RuntimeDiscovery(BaseModel):
    """Dependency discovered exclusively through Grafana Tempo runtime traces."""
    model_config = ConfigDict(extra="ignore")

    consumer: str                # e.g. "poster"
    selected_reference: str      # e.g. "shot_01:keyframe:v1"
    reason: str = "runtime_tool_selection"
    trace_id: str = ""
    span_id: str = ""
    explanation: str = ""


class AssetImpact(BaseModel):
    """Deterministic impact calculation result for a single asset."""
    model_config = ConfigDict(extra="ignore")

    artifact_id: str             # e.g. "shot_01", "shot_02", "poster"
    action: AssetAction          # REBUILD, REVALIDATE, REUSE
    reasons: list[str] = Field(default_factory=list)
    dependency_chain: list[str] = Field(default_factory=list)
    source_origins: list[str] = Field(default_factory=list)


class ImpactPlan(BaseModel):
    """Deterministic build and reuse plan derived from Declared ∪ Observed dependencies."""
    model_config = ConfigDict(extra="ignore")

    change_id: str
    baseline_build_id: str
    created_at: str = Field(
        default_factory=lambda: datetime.datetime.now(datetime.timezone.utc).isoformat()
    )
    target: dict[str, Any]

    rebuild: list[str] = Field(default_factory=list)
    revalidate: list[str] = Field(default_factory=list)
    reuse: list[str] = Field(default_factory=list)

    asset_details: dict[str, AssetImpact] = Field(default_factory=dict)
    runtime_discoveries: list[RuntimeDiscovery] = Field(default_factory=list)

    declared_dependency_count: int = 0
    observed_runtime_dependency_count: int = 0

    full_build_operations: int = 0
    total_operations: int = 7
    incremental_operations: int = 0
    avoided_operations: int = 0
    savings_percent: float = 0.0

    reasoning_summary: str = ""

