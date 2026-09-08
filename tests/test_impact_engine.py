"""Unit tests for Cinema CI/CD Change Impact Intelligence."""

import os
import unittest
from app.contract import load_contract
from app.impact.models import CreativeChangeRequest, ChangeType, AssetAction
from app.impact.engine import ImpactEngine
from app.impact.observed import extract_observed_dependencies_from_trace
from app.impact.declared import extract_declared_dependencies


class TestImpactEngine(unittest.TestCase):

    def setUp(self):
        self.contract = load_contract("cinema.yaml")
        self.engine = ImpactEngine(self.contract)

    def test_declared_dependencies(self):
        edges = extract_declared_dependencies(self.contract)
        char_targets = {e.to_node for e in edges if e.from_node.startswith("character:")}
        self.assertIn("shot_01", char_targets)
        self.assertIn("shot_03", char_targets)
        # shot_02 is envelope closeup, no character
        self.assertNotIn("shot_02", char_targets)

    def test_observed_lineage_extraction(self):
        sample_trace = {
            "trace_id": "4bf92f3577b34da6a3ce929d0e0e4736",
            "spans": [
                {
                    "name": "cinema.reference.select",
                    "trace_id": "4bf92f3577b34da6a3ce929d0e0e4736",
                    "span_id": "0000000000000006",
                    "attributes": {
                        "cinema.consumer": "poster:v1",
                        "cinema.reference.selected": "shot_01:keyframe:v1",
                        "cinema.selection.reason": "runtime_visual_composition",
                    },
                }
            ],
        }
        edges, discoveries = extract_observed_dependencies_from_trace(sample_trace)
        self.assertEqual(len(edges), 1)
        self.assertEqual(edges[0].from_node, "shot_01")
        self.assertEqual(edges[0].to_node, "poster")
        self.assertEqual(len(discoveries), 1)
        self.assertEqual(discoveries[0].consumer, "poster")

    def test_observed_lineage_extraction_shot_03(self):
        sample_trace = {
            "trace_id": "4bf92f3577b34da6a3ce929d0e0e4736",
            "spans": [
                {
                    "name": "cinema.reference.select",
                    "trace_id": "4bf92f3577b34da6a3ce929d0e0e4736",
                    "span_id": "0000000000000006",
                    "attributes": {
                        "cinema.consumer": "poster:v1",
                        "cinema.reference.selected": "shot_03:keyframe:v1",
                        "cinema.selection.reason": "Marcus holding titular blue envelope direct to camera",
                    },
                }
            ],
        }
        edges, discoveries = extract_observed_dependencies_from_trace(sample_trace)
        self.assertEqual(len(edges), 1)
        self.assertEqual(edges[0].from_node, "shot_03")
        self.assertEqual(edges[0].to_node, "poster")
        self.assertEqual(len(discoveries), 1)
        self.assertEqual(discoveries[0].consumer, "poster")
        self.assertEqual(discoveries[0].selected_reference, "shot_03:keyframe:v1")

    def test_blast_radius_computation_hero_scenario(self):
        char_key = list(self.contract.characters.keys())[0]
        req = CreativeChangeRequest(
            change_id="req_test_01",
            entity_id=f"character:{char_key}",
            property="glasses",
            change_type=ChangeType.VISUAL_ATTRIBUTE,
            old_value="round eyeglasses",
            new_value="no glasses",
        )
        sample_trace = {
            "trace_id": "4bf92f3577b34da6a3ce929d0e0e4736",
            "spans": [
                {
                    "name": "cinema.reference.select",
                    "trace_id": "4bf92f3577b34da6a3ce929d0e0e4736",
                    "span_id": "0000000000000006",
                    "attributes": {
                        "cinema.consumer": "poster:v1",
                        "cinema.reference.selected": "shot_01:keyframe:v1",
                    },
                }
            ],
        }
        plan = self.engine.compute_impact(req, "build_0001", trace_data=sample_trace)

        # Expected: 3 rebuild, 1 reuse, 1 avoided (Shot 02 safe reuse), 25.0% compute savings
        self.assertEqual(len(plan.rebuild), 3)
        self.assertEqual(len(plan.reuse), 1)
        self.assertEqual(plan.avoided_operations, 1)
        self.assertEqual(plan.savings_percent, 25.0)

        self.assertIn("shot_01", plan.rebuild)
        self.assertIn("shot_03", plan.rebuild)
        self.assertIn("poster", plan.rebuild)  # Derived from runtime lineage

        self.assertIn("shot_02", plan.reuse)


if __name__ == "__main__":
    unittest.main()
