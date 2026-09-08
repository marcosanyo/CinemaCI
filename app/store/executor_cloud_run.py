"""Cinema CI — Cloud Run Job Build Executor.

Dispatches long-running build tasks (Veo video generation, PyAV/FFmpeg QA, Gemini creative checks)
to a dedicated Cloud Run Job worker (`cinema-ci-build-worker`) using the Google Cloud Run API with ADC.
Falls back gracefully to in-process asynchronous task execution if the Cloud Run Job API is unreachable.
"""

from __future__ import annotations

import asyncio
import logging
import os
from typing import Any

from app.models import BuildStatus
from app.store.executor_base import BuildExecutor
from app.store.metadata_base import MetadataStore

logger = logging.getLogger(__name__)


class CloudRunJobExecutor(BuildExecutor):
    """Executes builds by triggering Cloud Run Job executions."""

    def __init__(
        self,
        metadata_store_getter: Any,
        job_name: str | None = None,
        project_id: str | None = None,
        location: str | None = None,
    ) -> None:
        self._metadata_store_getter = metadata_store_getter
        self.job_name = job_name or os.getenv("CINEMA_BUILD_JOB", "cinema-ci-build-worker")
        self.project_id = project_id or os.getenv("GOOGLE_CLOUD_PROJECT", "hackathon-505614")

        loc = location or os.getenv("CINEMA_JOB_LOCATION", os.getenv("VEO_LOCATION", "us-central1"))
        if loc.lower() == "global":
            loc = "us-central1"
        self.location = loc

        logger.info(
            "CloudRunJobExecutor configured for Job '%s' (project: %s, location: %s)",
            self.job_name,
            self.project_id,
            self.location,
        )

    async def submit_build(
        self,
        build_id: str,
        baseline_build_id: str | None = None,
        impact_plan: dict[str, Any] | None = None,
        shots_to_regenerate: list[str] | None = None,
    ) -> str:
        metadata_store: MetadataStore = self._metadata_store_getter()
        build = metadata_store.get_build(build_id)

        meta_backend = os.getenv("CINEMA_METADATA_BACKEND", "gcs")
        art_backend = os.getenv("CINEMA_ARTIFACT_BACKEND", "gcs")

        # Environment variable overrides for the Cloud Run Job task
        env_vars = [
            {"name": "BUILD_ID", "value": build_id},
            {"name": "PROJECT_ID", "value": build.project_id if build else "cafe-envelope"},
            {"name": "BASELINE_BUILD_ID", "value": baseline_build_id or ""},
            {"name": "CINEMA_ENV", "value": "cloud"},
            {"name": "CINEMA_ARTIFACT_BACKEND", "value": art_backend},
            {"name": "CINEMA_METADATA_BACKEND", "value": meta_backend},
            {"name": "PYTHONUNBUFFERED", "value": "1"},
        ]

        # Explicitly forward telemetry and Vertex AI environment variables
        forward_keys = (
            "OTEL_EXPORTER_OTLP_ENDPOINT",
            "OTEL_EXPORTER_OTLP_HEADERS",
            "GRAFANA_URL",
            "GOOGLE_CLOUD_PROJECT",
            "GOOGLE_CLOUD_LOCATION",
            "GOOGLE_GENAI_USE_VERTEXAI",
            "GENERATOR_TYPE",
            "VEO_MODEL",
            "VEO_LOCATION",
            "STRICT_MODE",
            "CINEMA_STRICT_MODE",
            "CINEMA_GCS_BUCKET",
        )
        for k in forward_keys:
            val = os.getenv(k)
            if val:
                env_vars.append({"name": k, "value": val})

        import json

        if impact_plan:
            env_vars.append({"name": "IMPACT_PLAN", "value": json.dumps(impact_plan)})
            if not shots_to_regenerate:
                shots_to_regenerate = impact_plan.get("rebuild") or impact_plan.get("rebuild_assets")
            if not baseline_build_id:
                baseline_build_id = impact_plan.get("baseline_build_id")

        if shots_to_regenerate:
            env_vars.append({"name": "SHOTS_TO_REGENERATE", "value": json.dumps(shots_to_regenerate)})

        if baseline_build_id:
            for ev in env_vars:
                if ev["name"] == "BASELINE_BUILD_ID":
                    ev["value"] = baseline_build_id
                    break

        # Call Google Cloud Run API
        try:
            from google.cloud import run_v2

            client = run_v2.JobsClient()
            parent = f"projects/{self.project_id}/locations/{self.location}/jobs/{self.job_name}"

            request = run_v2.RunJobRequest(
                name=parent,
                overrides=run_v2.RunJobRequest.Overrides(
                    container_overrides=[
                        run_v2.RunJobRequest.Overrides.ContainerOverride(
                            env=[run_v2.EnvVar(name=v["name"], value=v["value"]) for v in env_vars]
                        )
                    ]
                )
            )

            operation = client.run_job(request=request)
            execution_name = operation.metadata.name if hasattr(operation, "metadata") and operation.metadata else f"{self.job_name}-exec-{build_id}"
            logger.info(f"Successfully triggered Cloud Run Job execution: {execution_name} for build {build_id}")

            if build:
                build.status = BuildStatus.BUILDING
                from app.models import BuildLogEntry
                build.logs.append(
                    BuildLogEntry(
                        stage="SETUP",
                        level="INFO",
                        message=f"Cloud Run Job worker dispatched: {self.job_name} (provisioning serverless container...)",
                    )
                )
                metadata_store.save_build(build)

            return execution_name

        except Exception as e:
            err_msg = f"Failed to dispatch build {build_id} to Cloud Run Job '{self.job_name}' (region: {self.location}): {e}"
            logger.warning(f"{err_msg}. Falling back to in-process background worker execution.")

            # Fall back gracefully to in-process background worker
            async def _in_process_worker():
                try:
                    from app.main import engine
                    baseline_build = metadata_store.get_build(baseline_build_id) if baseline_build_id else None
                    await engine.run_build(
                        build_id=build_id,
                        baseline_build=baseline_build,
                        impact_plan=impact_plan,
                        shots_to_regenerate=shots_to_regenerate,
                    )
                except Exception as inner_e:
                    logger.error(f"In-process background build {build_id} failed: {inner_e}", exc_info=True)

            asyncio.create_task(_in_process_worker())
            return f"in-process-fallback-{build_id}"

    async def cancel_build(self, build_id: str) -> bool:
        metadata_store: MetadataStore = self._metadata_store_getter()
        build = metadata_store.get_build(build_id)
        if build:
            build.status = BuildStatus.CANCELED
            build.error_summary = "Build canceled by user request."
            metadata_store.save_build(build)
            logger.info(f"Marked build {build_id} as CANCELED in metadata store")
            return True
        return False
