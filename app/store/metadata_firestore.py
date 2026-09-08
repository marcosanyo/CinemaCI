"""Cinema CI — Google Cloud Firestore Metadata Store.

Implements the MetadataStore interface using Firestore collections:
- `builds`
- `releases`
- `impact_plans`
- `projects`

Enables durable, distributed metadata management for Cloud Run services and worker jobs
with local cache fallback.
"""

from __future__ import annotations

import logging
import os
from typing import Any

from app.impact.models import ImpactPlan
from app.models import Build, ReleaseRecord
from app.store.metadata_base import MetadataStore

logger = logging.getLogger(__name__)


class FirestoreMetadataStore(MetadataStore):
    """Google Cloud Firestore implementation of MetadataStore with local cache fallback."""

    def __init__(self, project_id: str | None = None, database: str | None = None) -> None:
        self.project_id = project_id or os.getenv("GOOGLE_CLOUD_PROJECT")
        self.database = database or "(default)"
        self.client = None
        self._build_counter = 0
        self._release_counter = 0

        # In-memory local cache fallback
        self._local_builds: dict[str, Build] = {}
        self._local_releases: dict[str, ReleaseRecord] = {}
        self._local_plans: dict[str, ImpactPlan] = {}

        try:
            from google.cloud import firestore
            self.client = firestore.Client(project=self.project_id, database=self.database)
            logger.info(f"FirestoreMetadataStore connected to project '{self.project_id}' (database: {self.database})")
            self._sync_counters()
        except Exception as e:
            logger.warning(f"FirestoreMetadataStore initialization warning (will retry on demand): {e}")

    def _get_client(self):
        if self.client is None:
            try:
                from google.cloud import firestore
                self.client = firestore.Client(project=self.project_id, database=self.database)
                self._sync_counters()
            except Exception as e:
                logger.warning(f"Firestore client connection failed: {e}")
        return self.client

    def _sync_counters(self) -> None:
        """Scan latest IDs to initialize sequential counters."""
        try:
            db = self._get_client()
            if not db:
                return
            # Check builds
            build_docs = db.collection("builds").order_by("created_at", direction="DESCENDING").limit(10).stream()
            for doc in build_docs:
                bid = doc.id
                if bid.startswith("build_"):
                    try:
                        num = int(bid.split("_")[1])
                        if num > self._build_counter:
                            self._build_counter = num
                    except ValueError:
                        pass

            # Check releases
            rel_docs = db.collection("releases").order_by("released_at", direction="DESCENDING").limit(10).stream()
            for doc in rel_docs:
                rid = doc.id
                if rid.startswith("release_"):
                    try:
                        num = int(rid.split("_")[1])
                        if num > self._release_counter:
                            self._release_counter = num
                    except ValueError:
                        pass
        except Exception as e:
            logger.debug(f"Counter sync warning in Firestore: {e}")

    def save_build(self, build: Build) -> None:
        self._local_builds[build.build_id] = build
        if build.build_id.startswith("build_"):
            try:
                num = int(build.build_id.split("_")[1])
                if num > self._build_counter:
                    self._build_counter = num
            except ValueError:
                pass
        try:
            db = self._get_client()
            if db:
                doc_ref = db.collection("builds").document(build.build_id)
                data = build.model_dump()
                doc_ref.set(data)
                logger.debug(f"Saved build {build.build_id} (status: {build.status.value}) to Firestore")
        except Exception as e:
            logger.warning(f"Firestore save_build failed (cached locally): {e}")

    def get_build(self, build_id: str) -> Build | None:
        try:
            db = self._get_client()
            if db:
                doc = db.collection("builds").document(build_id).get()
                if doc.exists:
                    b = Build(**doc.to_dict())
                    self._local_builds[build_id] = b
                    return b
        except Exception as e:
            logger.debug(f"Firestore get_build error (checking cache): {e}")
        return self._local_builds.get(build_id)

    def list_builds(self, project_id: str | None = None) -> list[Build]:
        found: dict[str, Build] = dict(self._local_builds)
        try:
            db = self._get_client()
            if db:
                query = db.collection("builds")
                if project_id:
                    query = query.where("project_id", "==", project_id)
                docs = query.stream()
                for doc in docs:
                    bdict = doc.to_dict()
                    if not doc.id.startswith("test_"):
                        b = Build(**bdict)
                        found[b.build_id] = b
                        self._local_builds[b.build_id] = b
        except Exception as e:
            logger.warning(f"Firestore list_builds query warning (using memory cache): {e}")

        builds = [b for b in found.values() if not b.build_id.startswith("test_")]
        if project_id:
            builds = [b for b in builds if b.project_id == project_id]
        return sorted(builds, key=lambda b: b.created_at, reverse=True)

    def delete_build(self, build_id: str) -> bool:
        if build_id in self._local_builds:
            del self._local_builds[build_id]
        try:
            db = self._get_client()
            if db:
                db.collection("builds").document(build_id).delete()
                return True
        except Exception as e:
            logger.warning(f"Firestore delete_build error: {e}")
        return True

    def save_release(self, release: ReleaseRecord) -> None:
        self._local_releases[release.release_id] = release
        if release.release_id.startswith("release_"):
            try:
                num = int(release.release_id.split("_")[1])
                if num > self._release_counter:
                    self._release_counter = num
            except ValueError:
                pass
        try:
            db = self._get_client()
            if db:
                doc_ref = db.collection("releases").document(release.release_id)
                doc_ref.set(release.model_dump())
                logger.info(f"Saved release {release.release_id} to Firestore")
        except Exception as e:
            logger.warning(f"Firestore save_release failed (cached locally): {e}")

    def get_release(self, release_id: str) -> ReleaseRecord | None:
        try:
            db = self._get_client()
            if db:
                doc = db.collection("releases").document(release_id).get()
                if doc.exists:
                    r = ReleaseRecord(**doc.to_dict())
                    self._local_releases[release_id] = r
                    return r
        except Exception as e:
            logger.debug(f"Firestore get_release error (checking cache): {e}")
        return self._local_releases.get(release_id)

    def list_releases(self, project_id: str | None = None) -> list[ReleaseRecord]:
        found: dict[str, ReleaseRecord] = dict(self._local_releases)
        try:
            db = self._get_client()
            if db:
                query = db.collection("releases")
                if project_id:
                    query = query.where("project_id", "==", project_id)
                docs = query.stream()
                for doc in docs:
                    r = ReleaseRecord(**doc.to_dict())
                    found[r.release_id] = r
                    self._local_releases[r.release_id] = r
        except Exception as e:
            logger.warning(f"Firestore list_releases query failed: {e}")
        return sorted(found.values(), key=lambda r: r.released_at, reverse=True)

    def save_impact_plan(self, plan: ImpactPlan) -> None:
        self._local_plans[plan.change_id] = plan
        try:
            db = self._get_client()
            if db:
                doc_ref = db.collection("impact_plans").document(plan.change_id)
                doc_ref.set(plan.model_dump())
                logger.info(f"Saved impact plan {plan.change_id} to Firestore")
        except Exception as e:
            logger.warning(f"Firestore save_impact_plan failed (cached locally): {e}")

    def get_impact_plan(self, change_id: str) -> ImpactPlan | None:
        try:
            db = self._get_client()
            if db:
                doc = db.collection("impact_plans").document(change_id).get()
                if doc.exists:
                    p = ImpactPlan(**doc.to_dict())
                    self._local_plans[change_id] = p
                    return p
        except Exception as e:
            logger.debug(f"Firestore get_impact_plan error (checking cache): {e}")
        return self._local_plans.get(change_id)

    def get_next_build_id(self) -> str:
        self._build_counter += 1
        return f"build_{self._build_counter:04d}"

    def get_next_release_id(self) -> str:
        self._release_counter += 1
        return f"release_{self._release_counter:04d}"
