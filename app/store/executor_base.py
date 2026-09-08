"""Cinema CI — BuildExecutor Protocol Interface.

Defines the interface for submitting build execution tasks (in-process local async task
or Cloud Run Job worker execution).
"""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable


@runtime_checkable
class BuildExecutor(Protocol):
    """Abstract interface for submitting and controlling build executions."""

    async def submit_build(
        self,
        build_id: str,
        baseline_build_id: str | None = None,
        impact_plan: dict[str, Any] | None = None,
        shots_to_regenerate: list[str] | None = None,
    ) -> str:
        """Submit a build execution task.
        
        Args:
            build_id: Target build identifier.
            baseline_build_id: Optional baseline build ID to reuse from.
            impact_plan: Optional ImpactPlan dictionary for incremental builds.
            shots_to_regenerate: Optional explicit shot regeneration list.
            
        Returns:
            Execution handle or tracking identifier.
        """
        ...

    async def cancel_build(self, build_id: str) -> bool:
        """Cancel an active or queued build execution."""
        ...
