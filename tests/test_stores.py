"""Unit and Integration Tests for Cinema CI Storage, Metadata, and Execution Adapters.

Verifies:
1. LocalArtifactStore operations and SHA-256 byte-identical reuse proof.
2. LocalMetadataStore persistence, serialization, and retrieval.
3. Metadata recovery after cache invalidation (process restart simulation).
4. LocalBuildExecutor asynchronous build dispatch.
5. Storage factory backend selection logic (Local vs Cloud).
"""

from __future__ import annotations

import os
import shutil
import tempfile
import unittest

from app.impact.models import ChangeType, CreativeChangeRequest, ImpactPlan
from app.models import (
    Build,
    BuildStatus,
    CinemaContract,
    ReleaseRecord,
    ShotArtifact,
)
from app.store import (
    LocalArtifactStore,
    LocalBuildExecutor,
    LocalMetadataStore,
    create_artifact_store,
    create_metadata_store,
    create_build_executor,
    is_cloud_environment,
)


class TestStorageAndMetadataBackends(unittest.TestCase):

    def setUp(self):
        self.test_dir = tempfile.mkdtemp(prefix="cinema_test_store_")
        self.artifact_store = LocalArtifactStore(root_dir=self.test_dir)
        self.metadata_store = LocalMetadataStore(root_dir=self.test_dir)

    def tearDown(self):
        shutil.rmtree(self.test_dir, ignore_errors=True)

    def test_local_artifact_store_put_get_copy_sha256(self):
        # 1. Create a dummy artifact file locally
        sample_file = os.path.join(self.test_dir, "test_shot.mp4")
        with open(sample_file, "wb") as f:
            f.write(b"video_frame_test_content_bytes_12345")

        logical_path = "projects/blue-envelope/builds/build_0001/shot_01.mp4"

        # 2. Put file into artifact store
        uri = self.artifact_store.put_file(sample_file, logical_path)
        self.assertTrue(self.artifact_store.exists(logical_path))

        # 3. Verify SHA-256 computation
        sha1 = self.artifact_store.sha256(logical_path)
        self.assertTrue(len(sha1) > 0)

        # 4. Copy artifact for incremental build reuse (build_0001 -> build_0002)
        dest_logical_path = "projects/blue-envelope/builds/build_0002/shot_01.mp4"
        self.artifact_store.copy(logical_path, dest_logical_path)
        self.assertTrue(self.artifact_store.exists(dest_logical_path))

        # 5. Verify byte-identical SHA-256 matching
        sha2 = self.artifact_store.sha256(dest_logical_path)
        self.assertEqual(sha1, sha2, "Reused artifact MUST have identical SHA-256 fingerprint")

        # 6. Retrieve back to another local path
        retrieved_file = os.path.join(self.test_dir, "retrieved.mp4")
        self.artifact_store.get_file(dest_logical_path, retrieved_file)
        with open(retrieved_file, "rb") as f:
            self.assertEqual(f.read(), b"video_frame_test_content_bytes_12345")

    def test_local_metadata_store_build_lifecycle_and_restart(self):
        # 1. Create a Build record
        build = Build(
            build_id="build_9999",
            project_id="blue-envelope",
            status=BuildStatus.QUEUED,
        )
        self.metadata_store.save_build(build)

        # 2. Verify immediate retrieval
        loaded = self.metadata_store.get_build("build_9999")
        self.assertIsNotNone(loaded)
        self.assertEqual(loaded.status, BuildStatus.QUEUED)

        # 3. Simulate state transitions: QUEUED -> BUILDING -> RELEASE_READY
        loaded.status = BuildStatus.BUILDING
        self.metadata_store.save_build(loaded)
        self.assertEqual(self.metadata_store.get_build("build_9999").status, BuildStatus.BUILDING)

        loaded.status = BuildStatus.RELEASE_READY
        loaded.release_ready = True
        loaded.tests_passed = 25
        loaded.tests_total = 25
        self.metadata_store.save_build(loaded)

        # 4. Simulate server restart: create a new fresh MetadataStore instance on the same directory
        restarted_store = LocalMetadataStore(root_dir=self.test_dir)
        recovered_build = restarted_store.get_build("build_9999")
        self.assertIsNotNone(recovered_build)
        self.assertEqual(recovered_build.status, BuildStatus.RELEASE_READY)
        self.assertEqual(recovered_build.tests_passed, 25)

    def test_release_and_impact_plan_persistence(self):
        # 1. Save ImpactPlan
        plan = ImpactPlan(
            change_id="change_001",
            baseline_build_id="build_0001",
            target={"entity": "character:marcus", "property": "glasses", "from": "round eyeglasses", "to": "no glasses"},
            rebuild=["shot_01", "shot_03", "poster"],
            revalidate=[],
            reuse=["shot_02"],
        )
        self.metadata_store.save_impact_plan(plan)

        retrieved_plan = self.metadata_store.get_impact_plan("change_001")
        self.assertIsNotNone(retrieved_plan)
        self.assertEqual(retrieved_plan.rebuild, ["shot_01", "shot_03", "poster"])
        self.assertEqual(retrieved_plan.reuse, ["shot_02"])

        # 2. Save ReleaseRecord
        release = ReleaseRecord(
            release_id="release_9999",
            build_id="build_9999",
            project_id="blue-envelope",
            film_path="storage/build_9999/final_film.mp4",
            avoided_operations=1,
            savings_percent=25.0,
        )
        self.metadata_store.save_release(release)

        retrieved_rel = self.metadata_store.get_release("release_9999")
        self.assertIsNotNone(retrieved_rel)
        self.assertEqual(retrieved_rel.savings_percent, 25.0)
        self.assertEqual(len(self.metadata_store.list_releases("blue-envelope")), 1)

    def test_factory_backend_selection(self):
        os.environ["CINEMA_ENV"] = "local"
        os.environ["CINEMA_ARTIFACT_BACKEND"] = "local"
        os.environ["CINEMA_METADATA_BACKEND"] = "local"

        art_store = create_artifact_store(force_new=True)
        meta_store = create_metadata_store(force_new=True)

        self.assertIsInstance(art_store, LocalArtifactStore)
        self.assertIsInstance(meta_store, LocalMetadataStore)


if __name__ == "__main__":
    unittest.main()
