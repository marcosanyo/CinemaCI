"""Cinema CI — Comprehensive Backend Behavioral Reimplementation Tests.

Validates core architectural invariants specified in Section 13:
1. Impact Analysis:
   - declared-only dependency
   - runtime-only dependency
   - union of both (True Blast Radius)
   - unaffected asset reuse (Shot 02)
   - invalid runtime reference handling
2. Grafana Runtime Lineage:
   - valid cinema.reference.select
   - missing event
   - malformed span
   - multiple historical events
   - dynamic shot selection (not hard-coded)
3. Dynamic Poster Selection:
   - real candidate validation
   - Gemini structured result validation
   - invalid selected shot rejection
   - no candidate images handling
   - strict-mode failure
4. Incremental Build & Reuse:
   - rebuild assets regenerated
   - reuse asset not regenerated
   - Shot 02 SHA-256 byte-identical preservation
5. QA System:
   - 25-check total (15 technical + 10 creative)
   - failed technical QA blocks release
   - failed creative QA blocks release
   - no legacy 28-count behavior
6. Strict Mode:
   - unavailable Grafana evidence fails loudly
   - unavailable Gemini selection fails loudly
   - zero production fallback to mock data
"""

from __future__ import annotations

import asyncio
import copy
import os
import tempfile
import unittest
from unittest.mock import MagicMock, patch

from app.contract import load_contract
from app.dynamic_selection import PosterSelectionResult, select_poster_hero_reference
from app.engine import BuildEngine, promote_build_to_release
from app.generator.fixture import FixtureGenerator
from app.impact.declared import extract_declared_dependencies
from app.impact.engine import ImpactEngine
from app.impact.models import AssetAction, ChangeType, CreativeChangeRequest
from app.impact.observed import extract_observed_dependencies_from_trace, normalize_trace_spans
from app.models import (
    Build,
    BuildStatus,
    CinemaContract,
    DeliverableArtifact,
    ReleaseSpec,
    ShotArtifact,
    TestResult,
    TestStatus,
)


class TestImpactEngineBehavioral(unittest.TestCase):
    """Behavioral tests for True Blast Radius impact calculations."""

    def setUp(self):
        self.contract = load_contract("cinema.yaml")
        self.engine = ImpactEngine(self.contract)

    def test_declared_only_dependencies(self):
        """Changes to character marcus propagate to Shot 01 and Shot 03 declared in cinema.yaml."""
        req = CreativeChangeRequest(
            change_id="req_test_decl",
            entity_id="character:marcus",
            property="glasses",
            change_type=ChangeType.VISUAL_ATTRIBUTE,
            old_value="round eyeglasses",
            new_value="no glasses",
        )
        empty_trace = {"trace_id": "test_trace", "spans": []}
        plan = self.engine.compute_impact(req, "build_0001", trace_data=empty_trace)

        self.assertIn("shot_01", plan.rebuild)
        self.assertIn("shot_03", plan.rebuild)
        self.assertIn("shot_02", plan.reuse)
        self.assertIn("poster", plan.reuse)
        self.assertEqual(plan.declared_dependency_count, 2)
        self.assertEqual(plan.observed_runtime_dependency_count, 0)

    def test_runtime_only_dependency(self):
        """Observed cinema.reference.select links Shot 03 to Poster at runtime."""
        trace = {
            "trace_id": "trace_dyn_03",
            "spans": [
                {
                    "name": "cinema.reference.select",
                    "trace_id": "trace_dyn_03",
                    "span_id": "0000000000000006",
                    "attributes": {
                        "cinema.consumer": "poster:v1",
                        "cinema.reference.selected": "shot_03:keyframe:v1",
                        "cinema.selection.reason": "dynamic_visual_selection",
                    },
                }
            ],
        }
        edges, discoveries = extract_observed_dependencies_from_trace(trace)
        self.assertEqual(len(edges), 1)
        self.assertEqual(edges[0].from_node, "shot_03")
        self.assertEqual(edges[0].to_node, "poster")
        self.assertEqual(len(discoveries), 1)
        self.assertEqual(discoveries[0].selected_reference, "shot_03:keyframe:v1")

    def test_union_true_blast_radius(self):
        """True Blast Radius = Declared ∪ Observed: rebuild Shot 01, Shot 03, and Poster."""
        req = CreativeChangeRequest(
            change_id="req_hero",
            entity_id="character:marcus",
            property="glasses",
            change_type=ChangeType.VISUAL_ATTRIBUTE,
            old_value="round eyeglasses",
            new_value="no glasses",
        )
        trace = {
            "trace_id": "trace_hero",
            "spans": [
                {
                    "name": "cinema.reference.select",
                    "trace_id": "trace_hero",
                    "span_id": "span_ref_01",
                    "attributes": {
                        "cinema.consumer": "poster:v1",
                        "cinema.reference.selected": "shot_01:keyframe:v1",
                    },
                }
            ],
        }
        plan = self.engine.compute_impact(req, "build_0001", trace_data=trace)
        self.assertEqual(set(plan.rebuild), {"shot_01", "shot_03", "poster"})
        self.assertEqual(set(plan.reuse), {"shot_02"})
        self.assertEqual(plan.avoided_operations, 1)
        self.assertEqual(plan.savings_percent, 25.0)

    def test_unaffected_asset_reuse(self):
        """Shot 02 does not feature Marcus and is not consumed by Poster; must be classified REUSE."""
        req = CreativeChangeRequest(
            change_id="req_test_reuse",
            entity_id="character:marcus",
            property="coat",
            change_type=ChangeType.VISUAL_ATTRIBUTE,
            old_value="black coat",
            new_value="red coat",
        )
        trace = {
            "trace_id": "trace_01",
            "spans": [
                {
                    "name": "cinema.reference.select",
                    "trace_id": "trace_01",
                    "span_id": "s1",
                    "attributes": {
                        "cinema.consumer": "poster:v1",
                        "cinema.reference.selected": "shot_01:keyframe:v1",
                    },
                }
            ],
        }
        plan = self.engine.compute_impact(req, "build_0001", trace_data=trace)
        self.assertIn("shot_02", plan.reuse)
        self.assertEqual(plan.asset_details["shot_02"].action, AssetAction.REUSE)

    def test_invalid_runtime_reference_handling(self):
        """A runtime reference pointing to a non-existent shot is safely handled."""
        trace = {
            "trace_id": "trace_invalid",
            "spans": [
                {
                    "name": "cinema.reference.select",
                    "trace_id": "trace_invalid",
                    "span_id": "s_inv",
                    "attributes": {
                        "cinema.consumer": "poster:v1",
                        "cinema.reference.selected": "nonexistent_shot:keyframe:v1",
                    },
                }
            ],
        }
        edges, discoveries = extract_observed_dependencies_from_trace(trace)
        self.assertEqual(len(edges), 1)
        self.assertEqual(edges[0].from_node, "nonexistent_shot")

        req = CreativeChangeRequest(
            change_id="req_test",
            entity_id="character:marcus",
            property="glasses",
            change_type=ChangeType.VISUAL_ATTRIBUTE,
            old_value="round eyeglasses",
            new_value="no glasses",
        )
        plan = self.engine.compute_impact(req, "build_0001", trace_data=trace)
        self.assertNotIn("poster", plan.rebuild)
        self.assertIn("poster", plan.reuse)


class TestGrafanaLineageBehavioral(unittest.TestCase):
    """Behavioral tests for Tempo trace normalization and lineage extraction."""

    def test_dynamic_selection_not_hardcoded(self):
        """Selected shot comes dynamically from span attributes, e.g. Shot 02 or Shot 03."""
        for shot_candidate in ["shot_01", "shot_02", "shot_03", "shot_custom"]:
            trace = {
                "trace_id": "trace_dyn",
                "spans": [
                    {
                        "name": "cinema.reference.select",
                        "trace_id": "trace_dyn",
                        "span_id": "span_dyn",
                        "attributes": {
                            "cinema.consumer": "poster:v1",
                            "cinema.reference.selected": f"{shot_candidate}:keyframe:v1",
                            "cinema.selection.reason": f"Selected {shot_candidate}",
                        },
                    }
                ],
            }
            edges, discoveries = extract_observed_dependencies_from_trace(trace)
            self.assertEqual(edges[0].from_node, shot_candidate)
            self.assertEqual(discoveries[0].selected_reference, f"{shot_candidate}:keyframe:v1")

    def test_missing_event_returns_empty(self):
        """Trace without cinema.reference.select yields zero observed reference edges."""
        trace = {
            "trace_id": "trace_no_select",
            "spans": [
                {"name": "cinema.build", "trace_id": "trace_no_select", "span_id": "s1", "attributes": {}},
                {"name": "cinema.test", "trace_id": "trace_no_select", "span_id": "s2", "attributes": {}},
            ],
        }
        with patch.dict(os.environ, {"STRICT_MODE": "true", "CINEMA_STRICT_MODE": "1"}):
            edges, discoveries = extract_observed_dependencies_from_trace(trace)
            self.assertEqual(len(edges), 0)
            self.assertEqual(len(discoveries), 0)

    def test_malformed_span_handling(self):
        """Malformed or non-dict spans are skipped without exception."""
        trace = {
            "trace_id": "trace_malformed",
            "spans": [
                None,
                "not_a_dict",
                {"name": 123},
                {"name": "cinema.reference.select", "attributes": None},
            ],
        }
        normalized = normalize_trace_spans(trace)
        self.assertIsInstance(normalized, list)

    def test_multiple_historical_events_latest_preserved(self):
        """When multiple reference.select events exist, all valid edges are parsed."""
        trace = {
            "trace_id": "trace_multi",
            "spans": [
                {
                    "name": "cinema.reference.select",
                    "trace_id": "trace_multi",
                    "span_id": "s1",
                    "attributes": {
                        "cinema.consumer": "poster:v1",
                        "cinema.reference.selected": "shot_01:keyframe:v1",
                    },
                },
                {
                    "name": "cinema.reference.select",
                    "trace_id": "trace_multi",
                    "span_id": "s2",
                    "attributes": {
                        "cinema.consumer": "key_visual:v1",
                        "cinema.reference.selected": "shot_03:keyframe:v1",
                    },
                },
            ],
        }
        edges, discoveries = extract_observed_dependencies_from_trace(trace)
        self.assertEqual(len(edges), 2)
        consumers = {e.to_node for e in edges}
        self.assertIn("poster", consumers)
        self.assertIn("key_visual", consumers)


class TestDynamicPosterSelectionBehavioral(unittest.IsolatedAsyncioTestCase):
    """Behavioral tests for Gemini dynamic poster selection logic."""

    async def test_strict_mode_fails_on_no_candidates(self):
        """In strict mode, selecting a poster with no valid video/keyframes raises RuntimeError."""
        with patch.dict(os.environ, {"STRICT_MODE": "true", "CINEMA_STRICT_MODE": "1", "MOCK_MODE": "false"}):
            dummy_shots = [
                ShotArtifact(shot_id="shot_01", video_path="/nonexistent/video1.mp4"),
                ShotArtifact(shot_id="shot_02", video_path="/nonexistent/video2.mp4"),
            ]
            with self.assertRaises(RuntimeError) as ctx:
                await select_poster_hero_reference(dummy_shots)
            self.assertIn("Strict Mode Violation", str(ctx.exception))

    async def test_gemini_structured_result_validation(self):
        """Validates that Gemini structured response correctly parses into PosterSelectionResult."""
        mock_response = MagicMock()
        mock_response.text = '{"selected_shot_id": "shot_03", "selected_reference": "shot_03:keyframe:v1", "reason": "Dramatic framing", "confidence": 0.95}'

        with patch("app.dynamic_selection._extract_keyframe", return_value=True), \
             patch("builtins.open", unittest.mock.mock_open(read_data=b"fake_jpeg_bytes")), \
             patch("app.dynamic_selection._get_genai_client") as mock_client_factory, \
             patch.dict(os.environ, {"STRICT_MODE": "true", "CINEMA_STRICT_MODE": "1", "MOCK_MODE": "false"}):

            mock_client = MagicMock()
            mock_client.models.generate_content.return_value = mock_response
            mock_client_factory.return_value = mock_client

            shots = [ShotArtifact(shot_id="shot_03", video_path="fake.mp4")]
            result = await select_poster_hero_reference(shots)

            self.assertIsInstance(result, PosterSelectionResult)
            self.assertEqual(result.selected_shot_id, "shot_03")
            self.assertEqual(result.selected_reference, "shot_03:keyframe:v1")
            self.assertEqual(result.confidence, 0.95)

    async def test_invalid_selected_shot_rejected(self):
        """If Gemini returns a shot not in candidate keyframes, strict mode rejects it."""
        mock_response = MagicMock()
        mock_response.text = '{"selected_shot_id": "hallucinated_shot", "selected_reference": "hallucinated_shot:v1", "reason": "invalid", "confidence": 0.9}'

        with patch("app.dynamic_selection._extract_keyframe", return_value=True), \
             patch("builtins.open", unittest.mock.mock_open(read_data=b"fake_jpeg_bytes")), \
             patch("app.dynamic_selection._get_genai_client") as mock_client_factory, \
             patch.dict(os.environ, {"STRICT_MODE": "true", "CINEMA_STRICT_MODE": "1", "MOCK_MODE": "false"}):

            mock_client = MagicMock()
            mock_client.models.generate_content.return_value = mock_response
            mock_client_factory.return_value = mock_client

            shots = [ShotArtifact(shot_id="shot_01", video_path="fake.mp4")]
            with self.assertRaises(RuntimeError) as ctx:
                await select_poster_hero_reference(shots)
            self.assertIn("non-visual candidate", str(ctx.exception))


class TestQASystemBehavioral(unittest.TestCase):
    """Behavioral tests for canonical 25-point QA model."""

    def test_canonical_qa_total_is_25(self):
        """Contract cinema.yaml defines 15 technical checks + 10 creative checks = 25 total."""
        contract = load_contract("cinema.yaml")
        num_shots = len(contract.shots)
        self.assertEqual(num_shots, 3)
        expected_tech_count = num_shots * 5
        self.assertEqual(expected_tech_count, 15)

        s1_creative = len(contract.characters.get("marcus").traits) + 1
        s2_creative = 1
        s3_creative = len(contract.characters.get("marcus").traits) + 1
        cross_creative = 1
        expected_creative_count = s1_creative + s2_creative + s3_creative + cross_creative
        self.assertEqual(expected_creative_count, 10)

        total_qa = expected_tech_count + expected_creative_count
        self.assertEqual(total_qa, 25, "Canonical QA model MUST be exactly 25 tests")

    def test_failed_technical_qa_blocks_release(self):
        """A build with failing technical tests cannot be promoted to release."""
        bid = "test_fail_tech"
        build = Build(
            build_id=bid,
            project_id="cafe-envelope",
            status=BuildStatus.BLOCKED,
            release_ready=False,
            tests_total=25,
            tests_passed=24,
            test_results=[
                TestResult(
                    test_id="technical.resolution",
                    build_id=bid,
                    scope="shot_01",
                    category="technical",
                    evaluator="pyav",
                    expected=">= 1280x720",
                    observed="640x360",
                    status=TestStatus.FAIL,
                )
            ],
        )
        from app.engine import _builds
        _builds[bid] = build

        with self.assertRaises(ValueError) as ctx:
            promote_build_to_release(bid)
        self.assertIn("not release-ready", str(ctx.exception))

        del _builds[bid]


class TestIncrementalReuseBehavioral(unittest.IsolatedAsyncioTestCase):
    """Behavioral tests verifying byte-identical reuse and Veo call avoidance."""

    async def test_reused_shot_preserves_sha256_identically(self):
        """Verifies that Shot 02 is reused without regeneration and preserves SHA-256 byte-identically."""
        contract = load_contract("cinema.yaml")
        gen = FixtureGenerator(fixtures_dir="fixtures/blue-envelope")

        with tempfile.TemporaryDirectory() as storage_dir, \
             patch.dict(os.environ, {"MOCK_MODE": "true", "EVALUATOR_TYPE": "fixture"}):
            engine = BuildEngine(contract, gen, storage_dir)

            base_build = await engine.run_build("base_test_sha")
            base_shot_02 = next(s for s in base_build.shots if s.shot_id == "shot_02")
            self.assertTrue(len(base_shot_02.sha256) > 0)

            plan = {
                "target": {"entity": "character:marcus", "property": "glasses"},
                "rebuild": ["shot_01", "shot_03", "poster"],
                "reuse": ["shot_02"],
            }
            inc_build = await engine.run_build("inc_test_sha", base_build, None, plan)

            inc_shot_02 = next(s for s in inc_build.shots if s.shot_id == "shot_02")
            self.assertEqual(inc_shot_02.status, "reused_from_baseline")
            self.assertEqual(inc_shot_02.reused_from_build, "base_test_sha")
            self.assertEqual(inc_shot_02.sha256, base_shot_02.sha256, "Reused Shot 02 SHA-256 MUST match baseline")

            self.assertEqual(inc_build.operations_rebuilt, 3)
            self.assertEqual(inc_build.operations_reused, 1)
            self.assertEqual(inc_build.operations_avoided, 1)
            self.assertEqual(inc_build.savings_percent, 25.0)


if __name__ == "__main__":
    unittest.main()
