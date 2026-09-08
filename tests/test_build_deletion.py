"""Unit tests for build deletion and state reset."""

from __future__ import annotations

import unittest

from app.engine import delete_build, get_all_builds, get_build
from app.models import Build, BuildStatus


class TestBuildDeletion(unittest.TestCase):
    """Verifies that delete_build cleanly removes records and updates counters."""

    def test_delete_build_local_store(self):
        b = Build(build_id="build_9999", project_id="cafe-envelope", status=BuildStatus.QUEUED)
        from app.engine import _builds, get_metadata_store
        store = get_metadata_store()
        store.save_build(b)

        self.assertIsNotNone(get_build("build_9999"))

        deleted = delete_build("build_9999")
        self.assertTrue(deleted)
        self.assertIsNone(get_build("build_9999"))
        self.assertNotIn("build_9999", [x.build_id for x in get_all_builds()])


if __name__ == "__main__":
    unittest.main()
