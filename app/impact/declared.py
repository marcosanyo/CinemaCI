"""Cinema CI — Declared Manifest Dependency Extractor.

Extracts typed dependency edges from the design manifest (cinema.yaml).
Represents what should depend on what by design.
"""

from __future__ import annotations

from app.impact.models import DependencyEdge, DependencyOrigin, DependencyType
from app.models import CinemaContract


def extract_declared_dependencies(contract: CinemaContract) -> list[DependencyEdge]:
    """Extracts all declared dependencies from the CinemaContract manifest.

    Args:
        contract: Parsed CinemaContract from cinema.yaml.

    Returns:
        List of declared DependencyEdge objects.
    """
    edges: list[DependencyEdge] = []

    # 1. Shots declaring characters depend directly on character visual traits
    for char_id in contract.characters.keys():
        char_node = f"character:{char_id}"
        for shot in contract.shots:
            if char_id in shot.characters:
                edges.append(
                    DependencyEdge(
                        from_node=char_node,
                        to_node=shot.id,
                        dependency_type=DependencyType.VISUAL_DEPENDENCY,
                        origin=DependencyOrigin.DECLARED,
                        detail=f"{shot.id} declares {char_id} in scene cast.",
                    )
                )

    # 3. Shots declaring props depend on those props
    for prop_id in contract.props.keys():
        prop_node = f"prop:{prop_id}"
        for shot in contract.shots:
            if prop_id in shot.props and shot.props[prop_id].present:
                edges.append(
                    DependencyEdge(
                        from_node=prop_node,
                        to_node=shot.id,
                        dependency_type=DependencyType.VISUAL_DEPENDENCY,
                        origin=DependencyOrigin.DECLARED,
                        detail=f"{shot.id} declares prop {prop_id} as required.",
                    )
                )

    return edges

