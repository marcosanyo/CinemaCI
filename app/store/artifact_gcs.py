"""Cinema CI — Google Cloud Storage Artifact Store.

Implements the ArtifactStore interface using Google Cloud Storage buckets
with Application Default Credentials (ADC). Enables durable cloud artifact retention
and zero-compute, zero-network server-side object copy for SHA-256 verified reuse.
"""

from __future__ import annotations

import datetime
import hashlib
import logging
import os

from app.store.artifact_base import ArtifactStore

logger = logging.getLogger(__name__)


class GCSArtifactStore(ArtifactStore):
    """Google Cloud Storage implementation of ArtifactStore."""

    def __init__(self, bucket_name: str | None = None, project_id: str | None = None) -> None:
        self.bucket_name = bucket_name or os.getenv("CINEMA_GCS_BUCKET", "cinema-ci-production")
        self.project_id = project_id or os.getenv("GOOGLE_CLOUD_PROJECT")

        try:
            from google.cloud import storage
            self.client = storage.Client(project=self.project_id)
            self.bucket = self.client.bucket(self.bucket_name)
            logger.info(f"GCSArtifactStore connected to bucket: gs://{self.bucket_name} (project: {self.project_id})")
        except Exception as e:
            logger.warning(f"GCSArtifactStore initialization warning (will retry on demand): {e}")
            self.client = None
            self.bucket = None

    def _get_bucket(self):
        if self.bucket is None:
            from google.cloud import storage
            self.client = storage.Client(project=self.project_id)
            self.bucket = self.client.bucket(self.bucket_name)
        return self.bucket

    def _resolve_blob_name(self, artifact_path: str) -> str:
        """Normalize artifact path into a canonical GCS blob key.
        
        Example:
            'projects/blue-envelope/builds/build_0023/shot_01.mp4' -> 'projects/blue-envelope/builds/build_0023/shot_01.mp4'
            'build_0023/shot_01.mp4' -> 'projects/blue-envelope/builds/build_0023/shot_01.mp4'
            'storage/build_0023/shot_01.mp4' -> 'projects/blue-envelope/builds/build_0023/shot_01.mp4'
            'gs://cinema-ci-production/projects/...' -> 'projects/...'
        """
        clean = artifact_path.replace("\\", "/")
        if clean.startswith(f"gs://{self.bucket_name}/"):
            clean = clean[len(f"gs://{self.bucket_name}/"):]
        elif clean.startswith("gs://"):
            clean = clean.split("/", 3)[-1]

        if clean.startswith("projects/"):
            return clean.lstrip("/")
        elif "/builds/" in clean:
            return f"projects/{clean.lstrip('/')}"
        elif clean.startswith("storage/"):
            rel = clean[len("storage/"):]
            return f"projects/blue-envelope/builds/{rel}"
        elif clean.startswith("./storage/"):
            rel = clean[len("./storage/"):]
            return f"projects/blue-envelope/builds/{rel}"
        else:
            return f"projects/blue-envelope/builds/{clean.lstrip('/')}"

    def put_file(self, local_path: str, artifact_path: str) -> str:
        if not os.path.exists(local_path):
            raise FileNotFoundError(f"Local source file not found for GCS upload: {local_path}")
        
        # Calculate local SHA-256
        hasher = hashlib.sha256()
        with open(local_path, "rb") as f:
            while chunk := f.read(65536):
                hasher.update(chunk)
        sha_str = hasher.hexdigest()[:16]

        blob_name = self._resolve_blob_name(artifact_path)
        blob = self._get_bucket().blob(blob_name)
        blob.metadata = {"sha256": sha_str}

        content_type = "video/mp4" if local_path.endswith(".mp4") else "application/octet-stream"
        blob.upload_from_filename(local_path, content_type=content_type)
        logger.info(f"Uploaded to GCS: gs://{self.bucket_name}/{blob_name} (SHA: {sha_str})")
        return self.uri(artifact_path)

    def get_file(self, artifact_path: str, local_path: str) -> str:
        blob_name = self._resolve_blob_name(artifact_path)
        blob = self._get_bucket().blob(blob_name)
        if not blob.exists():
            raise FileNotFoundError(f"Artifact not found in GCS: gs://{self.bucket_name}/{blob_name}")
        
        os.makedirs(os.path.dirname(os.path.abspath(local_path)), exist_ok=True)
        blob.download_to_filename(local_path)
        return os.path.abspath(local_path)

    def copy(self, source_path: str, destination_path: str) -> str:
        src_name = self._resolve_blob_name(source_path)
        dst_name = self._resolve_blob_name(destination_path)
        bucket = self._get_bucket()

        source_blob = bucket.blob(src_name)
        if not source_blob.exists():
            raise FileNotFoundError(f"Source blob not found for GCS copy: gs://{self.bucket_name}/{src_name}")

        # Server-side GCS copy (Zero compute, zero network egress download)
        bucket.copy_blob(source_blob, bucket, dst_name)
        logger.info(f"Server-side GCS copy: gs://{self.bucket_name}/{src_name} -> gs://{self.bucket_name}/{dst_name}")
        return self.uri(destination_path)

    def exists(self, artifact_path: str) -> bool:
        blob_name = self._resolve_blob_name(artifact_path)
        blob = self._get_bucket().blob(blob_name)
        return blob.exists()

    def sha256(self, artifact_path: str) -> str:
        blob_name = self._resolve_blob_name(artifact_path)
        blob = self._get_bucket().get_blob(blob_name)
        if not blob:
            return ""
        if blob.metadata and "sha256" in blob.metadata:
            return blob.metadata["sha256"]
        
        # Download and compute
        data = blob.download_as_bytes()
        return hashlib.sha256(data).hexdigest()[:16]

    def uri(self, artifact_path: str) -> str:
        blob_name = self._resolve_blob_name(artifact_path)
        return f"gs://{self.bucket_name}/{blob_name}"

    def get_read_url(self, artifact_path: str, expires_in_seconds: int = 3600) -> str | None:
        """Generate a secure signed URL for client browser video playback."""
        blob_name = self._resolve_blob_name(artifact_path)
        blob = self._get_bucket().blob(blob_name)
        try:
            url = blob.generate_signed_url(
                version="v4",
                expiration=datetime.timedelta(seconds=expires_in_seconds),
                method="GET",
            )
            return url
        except Exception as e:
            logger.debug(f"Could not generate signed URL with credentials (falling back to storage URL): {e}")
            return f"https://storage.googleapis.com/{self.bucket_name}/{blob_name}"

    def get_bytes(self, artifact_path: str) -> bytes:
        blob_name = self._resolve_blob_name(artifact_path)
        blob = self._get_bucket().blob(blob_name)
        return blob.download_as_bytes()

    def put_bytes(self, data: bytes, artifact_path: str) -> str:
        sha_str = hashlib.sha256(data).hexdigest()[:16]
        blob_name = self._resolve_blob_name(artifact_path)
        blob = self._get_bucket().blob(blob_name)
        blob.metadata = {"sha256": sha_str}
        content_type = "video/mp4" if artifact_path.endswith(".mp4") else "application/octet-stream"
        blob.upload_from_string(data, content_type=content_type)
        return self.uri(artifact_path)
