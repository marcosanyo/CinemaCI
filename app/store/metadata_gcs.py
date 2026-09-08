"""Cinema CI — Google Cloud Storage Metadata Store.

Implements the MetadataStore interface by persisting JSON documents in GCS:
- `gs://{bucket}/metadata/builds.json`
- `gs://{bucket}/metadata/releases.json`
- `gs://{bucket}/metadata/impact_plans.json`

Provides durable, cloud-native persistence across Cloud Run instances and worker jobs
without requiring external database provisioning.
"""

from __future__ import annotations

import json
import logging
import os
from typing import Any

from app.impact.models import ImpactPlan
from app.models import Build, ReleaseRecord
from app.store.metadata_base import MetadataStore

logger = logging.getLogger(__name__)


class GCSMetadataStore(MetadataStore):
    """Google Cloud Storage implementation of MetadataStore."""

    def __init__(self, bucket_name: str | None = None, project_id: str | None = None) -> None:
        self.bucket_name = bucket_name or os.getenv("CINEMA_GCS_BUCKET", "cinema-ci-hackathon-505614")
        self.project_id = project_id or os.getenv("GOOGLE_CLOUD_PROJECT", "hackathon-505614")
        self.client = None
        self._bucket = None

        self._builds: dict[str, Build] = {}
        self._releases: dict[str, ReleaseRecord] = {}
        self._impact_plans: dict[str, ImpactPlan] = {}

        self._build_counter = 0
        self._release_counter = 0

        self._init_gcs()
        self._load_all_from_gcs()

    def _init_gcs(self) -> None:
        try:
            from google.cloud import storage
            self.client = storage.Client(project=self.project_id)
            self._bucket = self.client.bucket(self.bucket_name)
            logger.info(f"GCSMetadataStore connected to gs://{self.bucket_name}/metadata/")
        except Exception as e:
            logger.warning(f"GCSMetadataStore connection warning: {e}")

    def _load_all_from_gcs(self) -> None:
        if not self._bucket:
            return
        try:
            # 1. Load builds
            blob = self._bucket.blob("metadata/builds.json")
            if blob.exists():
                data = json.loads(blob.download_as_text())
                fresh_builds = {}
                max_counter = 0
                for b_dict in data:
                    b = Build(**b_dict)
                    fresh_builds[b.build_id] = b
                    if b.build_id.startswith("build_"):
                        try:
                            num = int(b.build_id.split("_")[1])
                            if num > max_counter:
                                max_counter = num
                        except ValueError:
                            pass
                self._builds = fresh_builds
                self._build_counter = max_counter
                logger.info(f"Loaded {len(self._builds)} builds from gs://{self.bucket_name}/metadata/builds.json")

            # 2. Load releases
            blob_rel = self._bucket.blob("metadata/releases.json")
            if blob_rel.exists():
                data_rel = json.loads(blob_rel.download_as_text())
                fresh_releases = {}
                max_rel_counter = 0
                for r_dict in data_rel:
                    r = ReleaseRecord(**r_dict)
                    fresh_releases[r.release_id] = r
                    if r.release_id.startswith("release_"):
                        try:
                            num = int(r.release_id.split("_")[1])
                            if num > max_rel_counter:
                                max_rel_counter = num
                        except ValueError:
                            pass
                self._releases = fresh_releases
                self._release_counter = max_rel_counter

            # 3. Load impact plans
            blob_ip = self._bucket.blob("metadata/impact_plans.json")
            if blob_ip.exists():
                data_ip = json.loads(blob_ip.download_as_text())
                fresh_plans = {}
                for p_dict in data_ip:
                    p = ImpactPlan(**p_dict)
                    fresh_plans[p.change_id] = p
                self._impact_plans = fresh_plans

        except Exception as e:
            logger.warning(f"Failed to load initial metadata from GCS: {e}")

    def _flush_builds(self) -> None:
        if not self._bucket:
            return
        try:
            blob = self._bucket.blob("metadata/builds.json")
            data = [b.model_dump() for b in self._builds.values() if not b.build_id.startswith("test_")]
            blob.upload_from_string(json.dumps(data, indent=2, default=str), content_type="application/json")
        except Exception as e:
            logger.warning(f"Failed to flush builds to GCS: {e}")

    def _flush_releases(self) -> None:
        if not self._bucket:
            return
        try:
            blob = self._bucket.blob("metadata/releases.json")
            data = [r.model_dump() for r in self._releases.values()]
            blob.upload_from_string(json.dumps(data, indent=2, default=str), content_type="application/json")
        except Exception as e:
            logger.warning(f"Failed to flush releases to GCS: {e}")

    def _flush_plans(self) -> None:
        if not self._bucket:
            return
        try:
            blob = self._bucket.blob("metadata/impact_plans.json")
            data = [p.model_dump() for p in self._impact_plans.values()]
            blob.upload_from_string(json.dumps(data, indent=2, default=str), content_type="application/json")
        except Exception as e:
            logger.warning(f"Failed to flush impact plans to GCS: {e}")

    def save_build(self, build: Build) -> None:
        self._builds[build.build_id] = build
        if build.build_id.startswith("build_"):
            try:
                num = int(build.build_id.split("_")[1])
                if num > self._build_counter:
                    self._build_counter = num
            except ValueError:
                pass
        self._flush_builds()

    def delete_build(self, build_id: str) -> bool:
        self._load_all_from_gcs()
        if build_id in self._builds:
            del self._builds[build_id]
            max_counter = 0
            for bid in self._builds:
                if bid.startswith("build_"):
                    try:
                        num = int(bid.split("_")[1])
                        if num > max_counter:
                            max_counter = num
                    except ValueError:
                        pass
            self._build_counter = max_counter
            self._flush_builds()
            return True
        return False

    def get_build(self, build_id: str) -> Build | None:
        # Always refresh from GCS so polling frontend sees real-time progress from Cloud Run workers
        self._load_all_from_gcs()
        return self._builds.get(build_id)

    def list_builds(self, project_id: str | None = None) -> list[Build]:
        self._load_all_from_gcs()
        builds = [b for b in self._builds.values() if not b.build_id.startswith("test_")]
        if project_id:
            builds = [b for b in builds if b.project_id == project_id]
        return sorted(builds, key=lambda b: b.created_at, reverse=True)

    def save_release(self, release: ReleaseRecord) -> None:
        self._releases[release.release_id] = release
        if release.release_id.startswith("release_"):
            try:
                num = int(release.release_id.split("_")[1])
                if num > self._release_counter:
                    self._release_counter = num
            except ValueError:
                pass
        self._flush_releases()

    def get_release(self, release_id: str) -> ReleaseRecord | None:
        return self._releases.get(release_id)

    def list_releases(self, project_id: str | None = None) -> list[ReleaseRecord]:
        self._load_all_from_gcs()
        releases = list(self._releases.values())
        if project_id:
            releases = [r for r in releases if r.project_id == project_id]
        return sorted(releases, key=lambda r: r.released_at, reverse=True)

    def save_impact_plan(self, plan: ImpactPlan) -> None:
        self._impact_plans[plan.change_id] = plan
        self._flush_plans()

    def get_impact_plan(self, change_id: str) -> ImpactPlan | None:
        return self._impact_plans.get(change_id)

    def get_next_build_id(self) -> str:
        self._build_counter += 1
        return f"build_{self._build_counter:04d}"

    def get_next_release_id(self) -> str:
        self._release_counter += 1
        return f"release_{self._release_counter:04d}"
