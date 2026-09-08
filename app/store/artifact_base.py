"""Cinema CI — ArtifactStore Protocol Interface.

Defines the unified abstraction for storing, retrieving, copying, and hashing
creative film artifacts (videos, character sheets, posters, final master).
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable


@runtime_checkable
class ArtifactStore(Protocol):
    """Abstract interface for artifact storage (Local filesystem or Google Cloud Storage)."""

    def put_file(self, local_path: str, artifact_path: str) -> str:
        """Store a local file into the artifact store at the specified logical artifact path.

        Args:
            local_path: Absolute or relative path to the local source file on disk.
            artifact_path: Logical destination path (e.g. 'projects/blue-envelope/builds/build_0023/shot_01.mp4').

        Returns:
            The canonical URI or path of the stored artifact.
        """
        ...

    def get_file(self, artifact_path: str, local_path: str) -> str:
        """Retrieve an artifact from storage and save it to the specified local path.

        Args:
            artifact_path: Logical artifact path.
            local_path: Local destination file path.

        Returns:
            The local file path where the artifact was saved.
        """
        ...

    def copy(self, source_path: str, destination_path: str) -> str:
        """Copy an artifact directly within the store (server-side for GCS, file copy for Local).
        Enables zero-compute, zero-network byte-identical reuse.

        Args:
            source_path: Logical path of the source artifact.
            destination_path: Logical path of the destination artifact.

        Returns:
            The canonical URI or path of the new destination artifact.
        """
        ...

    def exists(self, artifact_path: str) -> bool:
        """Check if an artifact exists in storage."""
        ...

    def sha256(self, artifact_path: str) -> str:
        """Compute or retrieve the 16-character SHA-256 fingerprint of the artifact."""
        ...

    def uri(self, artifact_path: str) -> str:
        """Return the canonical storage URI (e.g. 'gs://bucket/path' or 'storage/build_0023/shot_01.mp4')."""
        ...

    def get_read_url(self, artifact_path: str, expires_in_seconds: int = 3600) -> str | None:
        """Return an HTTP/HTTPS signed URL or public URL for client playback, if supported."""
        ...

    def get_bytes(self, artifact_path: str) -> bytes:
        """Read artifact binary content directly into memory."""
        ...

    def put_bytes(self, data: bytes, artifact_path: str) -> str:
        """Store in-memory binary content at the specified logical artifact path."""
        ...
