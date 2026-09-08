"""Cinema CI — Deterministic Impact Evaluation Policy.

Defines deterministic mapping rules between Change Types and Dependency Types.
Graph traversal and action assignment are 100% deterministic code.
"""

from __future__ import annotations

from app.impact.models import AssetAction, ChangeType, DependencyType


def evaluate_edge_impact(
    change_type: ChangeType,
    edge_type: DependencyType,
) -> tuple[AssetAction, str]:
    """Determines whether an asset should be REBUILT, REVALIDATED, or REUSED across an edge.

    Args:
        change_type: Semantic change classification.
        edge_type: Directed dependency relationship type.

    Returns:
        Tuple of (AssetAction, explanation string).
    """
    # 1. Visual changes (wardrobe, character traits, props, camera angle)
    if change_type in (ChangeType.VISUAL_ATTRIBUTE, ChangeType.PROP_SPEC, ChangeType.CAMERA_DIRECTION):
        if edge_type in (DependencyType.VISUAL_DEPENDENCY, DependencyType.REFERENCE_DEPENDENCY):
            return AssetAction.REBUILD, f"Visual change propagates through {edge_type.value} -> REBUILD required."
        elif edge_type in (DependencyType.AUDIO_DEPENDENCY, DependencyType.TEXT_DEPENDENCY):
            return AssetAction.REUSE, f"Visual change does not affect {edge_type.value} -> SAFE TO REUSE."
        elif edge_type == DependencyType.NARRATIVE_DEPENDENCY:
            return AssetAction.REVALIDATE, "Visual modification may subtly impact narrative pacing -> REVALIDATE."
        elif edge_type == DependencyType.ASSEMBLY_DEPENDENCY:
            return AssetAction.REVALIDATE, "Assembly depends on newly generated cut -> REVALIDATE."

    # 2. Narrative action changes (blocking, character movement, action)
    elif change_type == ChangeType.NARRATIVE_ACTION:
        if edge_type in (DependencyType.VISUAL_DEPENDENCY, DependencyType.NARRATIVE_DEPENDENCY, DependencyType.REFERENCE_DEPENDENCY):
            return AssetAction.REBUILD, f"Narrative action change alters motion and visuals -> REBUILD required."
        elif edge_type == DependencyType.AUDIO_DEPENDENCY:
            return AssetAction.REVALIDATE, "Action timing changed -> REVALIDATE audio synchronization."
        elif edge_type == DependencyType.TEXT_DEPENDENCY:
            return AssetAction.REUSE, "Dialogue text unchanged -> SAFE TO REUSE."

    # 3. Audio changes (score, sound effects, audio mix)
    elif change_type == ChangeType.AUDIO_PROPERTY:
        if edge_type == DependencyType.AUDIO_DEPENDENCY:
            return AssetAction.REBUILD, "Audio specification changed -> REBUILD audio track."
        elif edge_type in (DependencyType.VISUAL_DEPENDENCY, DependencyType.REFERENCE_DEPENDENCY, DependencyType.TEXT_DEPENDENCY):
            return AssetAction.REUSE, f"Audio adjustment does not modify video pixels -> SAFE TO REUSE."

    # 4. Text / dialogue changes (spoken lines, subtitle text)
    elif change_type == ChangeType.TEXT_DIALOGUE:
        if edge_type == DependencyType.TEXT_DEPENDENCY:
            return AssetAction.REBUILD, "Dialogue script updated -> REBUILD subtitles."
        elif edge_type == DependencyType.AUDIO_DEPENDENCY:
            return AssetAction.REBUILD, "Dialogue audio requires re-recording -> REBUILD audio."
        elif edge_type in (DependencyType.VISUAL_DEPENDENCY, DependencyType.REFERENCE_DEPENDENCY):
            return AssetAction.REUSE, "Visual footage unaffected by subtitle edit -> SAFE TO REUSE."

    # Ambiguous edges require revalidation
    return AssetAction.REVALIDATE, f"Edge type {edge_type.value} under {change_type.value} requires verification -> REVALIDATE."

