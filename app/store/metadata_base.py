"""Cinema CI — MetadataStore Protocol Interface.

Defines the unified abstraction for persisting and retrieving build records,
release records, and impact plans across Local JSON, Google Cloud Storage,
and Google Cloud Firestore backends.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from app.impact.models import ImpactPlan
from app.models import Build, ReleaseRecord


@runtime_checkable
class MetadataStore(Protocol):
    """Abstract interface for metadata persistence (Local JSON, GCS, or Firestore)."""

    def save_build(self, build: Build) -> None:
        """Persist a build record."""
        ...

    def get_build(self, build_id: str) -> Build | None:
        """Retrieve a build record by ID."""
        ...

    def list_builds(self, project_id: str | None = None) -> list[Build]:
        """List all builds, optionally filtered by project_id, sorted by created_at descending."""
        ...

    def delete_build(self, build_id: str) -> bool:
        """Delete a build record by ID. Returns True if deleted, False if not found."""
        ...

    def save_release(self, release: ReleaseRecord) -> None:
        """Persist a release record."""
        ...

    def get_release(self, release_id: str) -> ReleaseRecord | None:
        """Retrieve a release record by ID."""
        ...

    def list_releases(self, project_id: str | None = None) -> list[ReleaseRecord]:
        """List all release records, optionally filtered by project_id, sorted by released_at descending."""
        ...

    def save_impact_plan(self, plan: ImpactPlan) -> None:
        """Persist an impact plan."""
        ...

    def get_impact_plan(self, change_id: str) -> ImpactPlan | None:
        """Retrieve an impact plan by change ID."""
        ...

    def get_next_build_id(self) -> str:
        """Generate the next sequential build identifier."""
        ...

    def get_next_release_id(self) -> str:
        """Generate the next sequential release identifier."""
        ...

