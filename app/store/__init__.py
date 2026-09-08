"""Cinema CI — Storage & Execution Backend Factory.

Provides unified factory methods to select and initialize:
- ArtifactStore (Local filesystem vs Google Cloud Storage)
- MetadataStore (Local JSON vs Google Cloud Storage vs Google Cloud Firestore)
- BuildExecutor (Local In-Process Task vs Cloud Run Job)

Supports primary execution modes:
1. Local + Local Storage (default)
2. Local + Google Cloud (GCS + Firestore with ADC)
3. Cloud Run Service + Cloud Run Job Worker (Production)
"""

from __future__ import annotations

import logging
import os
from typing import Any, Callable

from app.store.artifact_base import ArtifactStore
from app.store.artifact_gcs import GCSArtifactStore
from app.store.artifact_local import LocalArtifactStore
from app.store.executor_base import BuildExecutor
from app.store.executor_cloud_run import CloudRunJobExecutor
from app.store.executor_local import LocalBuildExecutor
from app.store.metadata_base import MetadataStore
from app.store.metadata_firestore import FirestoreMetadataStore
from app.store.metadata_gcs import GCSMetadataStore
from app.store.metadata_local import LocalMetadataStore

logger = logging.getLogger(__name__)

# Singletons / cached store instances
_cached_artifact_store: ArtifactStore | None = None
_cached_metadata_store: MetadataStore | None = None
_cached_build_executor: BuildExecutor | None = None


def is_cloud_environment() -> bool:
    """Detect whether running in Google Cloud Run environment."""
    env = os.getenv("CINEMA_ENV", "").lower()
    if env in ("cloud", "production", "prod"):
        return True
    if os.getenv("K_SERVICE") or os.getenv("K_REVISION") or os.getenv("CLOUD_RUN_JOB"):
        return True
    return False


def get_artifact_backend() -> str:
    """Return 'gcs' or 'local'."""
    explicit = os.getenv("CINEMA_ARTIFACT_BACKEND", "").lower()
    if explicit:
        return explicit
    return "gcs" if is_cloud_environment() else "local"


def get_metadata_backend() -> str:
    """Return 'gcs', 'firestore', or 'local'."""
    explicit = os.getenv("CINEMA_METADATA_BACKEND", "").lower()
    if explicit:
        return explicit
    return "gcs" if is_cloud_environment() else "local"


def get_executor_backend() -> str:
    """Return 'cloud-run-job' or 'local'."""
    explicit = os.getenv("CINEMA_BUILD_EXECUTOR", "").lower()
    if explicit:
        return explicit
    return "cloud-run-job" if is_cloud_environment() else "local"


def create_artifact_store(backend: str | None = None, force_new: bool = False) -> ArtifactStore:
    """Factory creating the appropriate ArtifactStore instance."""
    global _cached_artifact_store
    if _cached_artifact_store and not force_new:
        return _cached_artifact_store

    selected = (backend or get_artifact_backend()).lower()
    if selected == "gcs":
        store = GCSArtifactStore()
    else:
        store = LocalArtifactStore()

    if not force_new:
        _cached_artifact_store = store
    return store


def create_metadata_store(backend: str | None = None, force_new: bool = False) -> MetadataStore:
    """Factory creating the appropriate MetadataStore instance."""
    global _cached_metadata_store
    if _cached_metadata_store and not force_new:
        return _cached_metadata_store

    selected = (backend or get_metadata_backend()).lower()
    if selected == "firestore":
        store = FirestoreMetadataStore()
    elif selected == "gcs":
        store = GCSMetadataStore()
    else:
        store = LocalMetadataStore()

    if not force_new:
        _cached_metadata_store = store
    return store


def create_build_executor(
    engine_getter: Callable[[], Any] | None = None,
    backend: str | None = None,
    force_new: bool = False,
) -> BuildExecutor:
    """Factory creating the appropriate BuildExecutor instance."""
    global _cached_build_executor
    if _cached_build_executor and not force_new:
        return _cached_build_executor

    selected = (backend or get_executor_backend()).lower()
    if selected in ("cloud-run-job", "cloud_run_job", "cloudrun"):
        executor = CloudRunJobExecutor(metadata_store_getter=create_metadata_store)
    else:
        if engine_getter is None:
            # Default lazy getter for local engine
            def _default_engine_getter():
                from app.main import engine
                return engine
            engine_getter = _default_engine_getter
        executor = LocalBuildExecutor(engine_getter=engine_getter)

    if not force_new:
        _cached_build_executor = executor
    return executor


def validate_backend_config(strict_mode: bool = False) -> None:
    """Validate backend configuration for production strict mode compliance."""
    if not strict_mode:
        return

    if is_cloud_environment():
        art_backend = get_artifact_backend()
        meta_backend = get_metadata_backend()
        exec_backend = get_executor_backend()

        if art_backend != "gcs":
            raise RuntimeError(f"STRICT MODE ENFORCEMENT FAILURE on Cloud: CINEMA_ARTIFACT_BACKEND must be 'gcs' (got '{art_backend}')")
        if meta_backend not in ("gcs", "firestore"):
            raise RuntimeError(f"STRICT MODE ENFORCEMENT FAILURE on Cloud: CINEMA_METADATA_BACKEND must be 'gcs' or 'firestore' (got '{meta_backend}')")
        if exec_backend not in ("cloud-run-job", "cloud_run_job", "cloudrun"):
            raise RuntimeError(f"STRICT MODE ENFORCEMENT FAILURE on Cloud: CINEMA_BUILD_EXECUTOR must be 'cloud-run-job' (got '{exec_backend}')")
        if not os.getenv("CINEMA_GCS_BUCKET"):
            raise RuntimeError("STRICT MODE ENFORCEMENT FAILURE on Cloud: CINEMA_GCS_BUCKET environment variable must be set.")
        if not os.getenv("GOOGLE_CLOUD_PROJECT"):
            raise RuntimeError("STRICT MODE ENFORCEMENT FAILURE on Cloud: GOOGLE_CLOUD_PROJECT environment variable must be set.")
        logger.info(f"STRICT MODE backend verification PASSED: GCS + {meta_backend.upper()} + Cloud Run Job configured.")


__all__ = [
    "ArtifactStore",
    "LocalArtifactStore",
    "GCSArtifactStore",
    "MetadataStore",
    "LocalMetadataStore",
    "GCSMetadataStore",
    "FirestoreMetadataStore",
    "BuildExecutor",
    "LocalBuildExecutor",
    "CloudRunJobExecutor",
    "is_cloud_environment",
    "create_artifact_store",
    "create_metadata_store",
    "create_build_executor",
    "validate_backend_config",
]
