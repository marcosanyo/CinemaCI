"""Cinema CI — Local JSON File Metadata Store.

Implements the MetadataStore interface using local JSON files in `./storage/`,
providing simple, fast, file-based persistence for local development.
"""

from __future__ import annotations

import json
import logging
import os

from app.impact.models import ImpactPlan
from app.models import Build, ReleaseRecord
from app.store.metadata_base import MetadataStore

logger = logging.getLogger(__name__)


class LocalMetadataStore(MetadataStore):
    """Local JSON file implementation of MetadataStore."""

    def __init__(self, root_dir: str | None = None) -> None:
        self.root_dir = os.path.abspath(root_dir or os.getenv("CINEMA_STORAGE_ROOT", "./storage"))
        os.makedirs(self.root_dir, exist_ok=True)

        self.builds_file = os.path.join(self.root_dir, "builds.json")
        self.releases_file = os.path.join(self.root_dir, "releases.json")
        self.plans_file = os.path.join(self.root_dir, "impact_plans.json")

        self._builds: dict[str, Build] = {}
        self._releases: dict[str, ReleaseRecord] = {}
        self._plans: dict[str, ImpactPlan] = {}

        self._build_counter = 0
        self._release_counter = 0

        self._load()
        logger.info(f"LocalMetadataStore initialized: {len(self._builds)} builds, {len(self._releases)} releases from {self.root_dir}")

    def _load(self) -> None:
        """Load records from local JSON files."""
        # Load Builds
        if os.path.exists(self.builds_file):
            try:
                with open(self.builds_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                for bid, bdict in data.items():
                    self._builds[bid] = Build(**bdict)
                    if bid.startswith("build_"):
                        try:
                            num = int(bid.split("_")[1])
                            if num > self._build_counter:
                                self._build_counter = num
                        except ValueError:
                            pass
            except Exception as e:
                logger.warning(f"Could not load builds from {self.builds_file}: {e}")

        # Load Releases
        if os.path.exists(self.releases_file):
            try:
                with open(self.releases_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                for rid, rdict in data.items():
                    self._releases[rid] = ReleaseRecord(**rdict)
                    if rid.startswith("release_"):
                        try:
                            num = int(rid.split("_")[1])
                            if num > self._release_counter:
                                self._release_counter = num
                        except ValueError:
                            pass
            except Exception as e:
                logger.warning(f"Could not load releases from {self.releases_file}: {e}")

        # Load Plans
        if os.path.exists(self.plans_file):
            try:
                with open(self.plans_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                for pid, pdict in data.items():
                    self._plans[pid] = ImpactPlan(**pdict)
            except Exception as e:
                logger.warning(f"Could not load impact plans from {self.plans_file}: {e}")

    def _save_builds(self) -> None:
        try:
            data = {bid: b.model_dump() for bid, b in self._builds.items()}
            with open(self.builds_file, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, default=str)
        except Exception as e:
            logger.warning(f"Failed to persist builds to {self.builds_file}: {e}")

    def _save_releases(self) -> None:
        try:
            data = {rid: r.model_dump() for rid, r in self._releases.items()}
            with open(self.releases_file, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, default=str)
        except Exception as e:
            logger.warning(f"Failed to persist releases to {self.releases_file}: {e}")

    def _save_plans(self) -> None:
        try:
            data = {pid: p.model_dump() for pid, p in self._plans.items()}
            with open(self.plans_file, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, default=str)
        except Exception as e:
            logger.warning(f"Failed to persist impact plans to {self.plans_file}: {e}")

    def save_build(self, build: Build) -> None:
        self._builds[build.build_id] = build
        if build.build_id.startswith("build_"):
            try:
                num = int(build.build_id.split("_")[1])
                if num > self._build_counter:
                    self._build_counter = num
            except ValueError:
                pass
        self._save_builds()

    def get_build(self, build_id: str) -> Build | None:
        return self._builds.get(build_id)

    def list_builds(self, project_id: str | None = None) -> list[Build]:
        if project_id:
            builds = [b for b in self._builds.values() if b.project_id == project_id and not b.build_id.startswith("test_")]
        else:
            builds = [b for b in self._builds.values() if not b.build_id.startswith("test_")]
        return sorted(builds, key=lambda b: b.created_at, reverse=True)

    def delete_build(self, build_id: str) -> bool:
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
            self._save_builds()
            return True
        return False

    def save_release(self, release: ReleaseRecord) -> None:
        self._releases[release.release_id] = release
        if release.release_id.startswith("release_"):
            try:
                num = int(release.release_id.split("_")[1])
                if num > self._release_counter:
                    self._release_counter = num
            except ValueError:
                pass
        self._save_releases()

    def get_release(self, release_id: str) -> ReleaseRecord | None:
        return self._releases.get(release_id)

    def list_releases(self, project_id: str | None = None) -> list[ReleaseRecord]:
        if project_id:
            releases = [r for r in self._releases.values() if r.project_id == project_id]
        else:
            releases = list(self._releases.values())
        return sorted(releases, key=lambda r: r.released_at, reverse=True)

    def save_impact_plan(self, plan: ImpactPlan) -> None:
        self._plans[plan.change_id] = plan
        self._save_plans()

    def get_impact_plan(self, change_id: str) -> ImpactPlan | None:
        return self._plans.get(change_id)

    def get_next_build_id(self) -> str:
        self._build_counter += 1
        return f"build_{self._build_counter:04d}"

    def get_next_release_id(self) -> str:
        self._release_counter += 1
        return f"release_{self._release_counter:04d}"
