"""Unit tests for Cinema CI/CD Continuous Delivery & Human Approval Promotion."""

import os
import unittest
from app.models import Build, BuildStatus, TestResult, TestStatus
from app.engine import promote_build_to_release, get_all_releases, _builds


class TestContinuousDelivery(unittest.TestCase):

    def test_promotion_gate(self):
        bid = "test_promo_build_01"
        build = Build(
            build_id=bid,
            project_id="cafe-envelope",
            status=BuildStatus.RELEASE_READY,
            release_ready=True,
            master_film_path="storage/test_build_hero_01/final_film.mp4",
            operations_total=8,
            operations_rebuilt=5,
            operations_reused=3,
            operations_avoided=3,
            savings_percent=37.5,
        )
        _builds[bid] = build

        rel = promote_build_to_release(bid, "Approved test release")
        self.assertTrue(rel.release_id.startswith("release_"))
        self.assertEqual(build.status, BuildStatus.RELEASED)
        self.assertTrue(build.is_released)
        self.assertEqual(rel.avoided_operations, 3)
        self.assertEqual(rel.savings_percent, 37.5)

    def test_blocked_build_cannot_be_promoted(self):
        bid = "test_blocked_build_01"
        build = Build(
            build_id=bid,
            project_id="cafe-envelope",
            status=BuildStatus.BLOCKED,
            release_ready=False,
        )
        _builds[bid] = build

        with self.assertRaises(ValueError):
            promote_build_to_release(bid)

    def tearDown(self):
        from app.engine import save_builds_to_disk
        for bid in ["test_promo_build_01", "test_blocked_build_01"]:
            if bid in _builds:
                del _builds[bid]
        save_builds_to_disk()


if __name__ == "__main__":
    unittest.main()
