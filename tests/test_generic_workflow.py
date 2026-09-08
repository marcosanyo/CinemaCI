"""Unit tests for generalized prompt templates and dynamic contract mutation."""

from __future__ import annotations

import unittest

from app.contract import apply_change_to_contract, get_baseline_contract
from app.generator.veo import VeoGenerator
from app.models import CharacterSpec, CinemaContract, ProjectSpec, PropSpec, ReleaseSpec, ShotPropRule, ShotSpec


class TestGenericPromptSynthesis(unittest.TestCase):
    """Verifies that prompt generation is fully driven by contract specifications."""

    def setUp(self):
        self.generator = VeoGenerator(project_id="test-proj")

    def test_prompt_build_uses_shot_description_and_traits_generically(self):
        char = CharacterSpec(
            name="elena",
            description="Elena, a detective in a trenchcoat.",
            traits={"coat": "beige trenchcoat", "hair": "auburn bob"},
        )
        prop = PropSpec(name="lantern", description="vintage brass lantern", color="brass")
        shot = ShotSpec(
            id="shot_99",
            description="Elena enters an ancient lighthouse holding the brass lantern.",
            setting="Stormy cliffside lighthouse interior.",
            camera="Wide cinematic tracking shot, 35mm lens.",
            characters=["elena"],
            props={"lantern": ShotPropRule(present=True)},
        )

        prompt = self.generator._build_prompt(
            shot_spec=shot,
            characters={"elena": char},
            props={"lantern": prop},
        )

        self.assertIn("Elena enters an ancient lighthouse", prompt)
        self.assertIn("Setting: Stormy cliffside lighthouse interior.", prompt)
        self.assertIn("Camera & Style: Wide cinematic tracking shot, 35mm lens.", prompt)
        self.assertIn("Character elena: Elena, a detective in a trenchcoat.", prompt)
        self.assertIn("Character elena mandatory traits", prompt)
        self.assertIn("Wardrobe Continuity: Elena must wear the exact same beige trenchcoat across all scenes.", prompt)
        self.assertIn("Key Prop (lantern): vintage brass lantern, color: brass", prompt)

    def test_prompt_build_handles_negative_traits_dynamically(self):
        char = CharacterSpec(
            name="bob",
            description="Bob without glasses.",
            traits={"glasses": "no glasses", "hat": "no hat"},
        )
        shot = ShotSpec(
            id="shot_01",
            description="Bob sits at a table.",
            characters=["bob"],
        )

        prompt = self.generator._build_prompt(
            shot_spec=shot,
            characters={"bob": char},
            props={},
        )

        self.assertIn("Glasses Removal (must strictly follow): Bob wears NO glasses in this shot.", prompt)
        self.assertIn("Hat Removal (must strictly follow): Bob wears NO hat in this shot.", prompt)


class TestGenericContractMutation(unittest.TestCase):
    """Verifies that apply_change_to_contract mutates contracts generically without hardcoding."""

    def test_eyewear_removal_on_baseline(self):
        contract = get_baseline_contract()
        target = {
            "entity": "character:marcus",
            "property": "glasses",
            "to": "no glasses",
            "from": "round eyeglasses",
        }

        updated = apply_change_to_contract(contract, target)
        marcus = updated.characters["marcus"]

        self.assertEqual(marcus.traits["glasses"], "no glasses")
        self.assertIn("no glasses", marcus.description.lower())
        self.assertNotIn("thin-rimmed round eyeglasses", marcus.description)

        # Shot 01 & 03 should have glasses removed
        s1 = next(s for s in updated.shots if s.id == "shot_01")
        self.assertNotIn("thin-rimmed round eyeglasses", s1.description)
        self.assertIn("no glasses", s1.description.lower())

    def test_coat_color_mutation_generic_character(self):
        contract = CinemaContract(
            project=ProjectSpec(id="test", title="Test"),
            release=ReleaseSpec(),
            characters={
                "alice": CharacterSpec(
                    name="alice",
                    description="Alice wearing a tailored black wool coat.",
                    traits={"coat": "tailored black wool coat"},
                )
            },
            props={},
            shots=[
                ShotSpec(
                    id="shot_01",
                    description="Alice in her black wool coat steps outside.",
                    characters=["alice"],
                )
            ],
        )

        target = {
            "entity": "character:alice",
            "property": "coat",
            "to": "crimson red",
        }

        updated = apply_change_to_contract(contract, target)
        alice = updated.characters["alice"]

        self.assertIn("crimson red", alice.traits["coat"])
        self.assertIn("crimson red wool coat", alice.description)
        self.assertIn("crimson red wool coat", updated.shots[0].description)

    def test_prop_color_mutation_generic_prop(self):
        contract = CinemaContract(
            project=ProjectSpec(id="test", title="Test"),
            release=ReleaseSpec(),
            characters={},
            props={
                "umbrella": PropSpec(
                    name="umbrella",
                    description="A classic black umbrella",
                    color="black",
                )
            },
            shots=[
                ShotSpec(
                    id="shot_01",
                    description="The camera pans past the black umbrella resting against the door.",
                    props={"umbrella": ShotPropRule(present=True)},
                )
            ],
        )

        target = {
            "entity": "prop:umbrella",
            "property": "color",
            "to": "yellow",
        }

        updated = apply_change_to_contract(contract, target)
        umbrella = updated.props["umbrella"]

        self.assertEqual(umbrella.color, "yellow")
        self.assertIn("yellow", umbrella.description)
        self.assertIn("yellow umbrella", updated.shots[0].description)


if __name__ == "__main__":
    unittest.main()


class TestIncrementalBuildExecution(unittest.IsolatedAsyncioTestCase):
    """Verifies that engine.run_build reuses assets specified in impact_plan."""

    async def test_impact_plan_triggers_reuse(self):
        import os
        import tempfile
        from app.engine import BuildEngine
        from app.generator.fixture import FixtureGenerator
        from app.store.artifact_local import LocalArtifactStore
        from app.store.metadata_local import LocalMetadataStore

        old_mock = os.environ.get("MOCK_MODE")
        os.environ["MOCK_MODE"] = "true"
        try:
            with tempfile.TemporaryDirectory() as tmpdir:
                contract = get_baseline_contract()
                art_store = LocalArtifactStore(root_dir=f"{tmpdir}/artifacts")
                meta_store = LocalMetadataStore(root_dir=f"{tmpdir}/metadata")
                generator = FixtureGenerator(fixtures_dir="fixtures/blue-envelope")

            engine = BuildEngine(
                contract=contract,
                generator=generator,
                storage_path=f"{tmpdir}/storage",
                artifact_store=art_store,
                metadata_store=meta_store,
            )

            # Baseline build
            b_base = await engine.run_build(build_id="test_b_base")
            self.assertEqual(b_base.operations_avoided, 0)

            # Incremental build with impact_plan reusing shot_02
            plan = {
                "rebuild": ["shot_01", "shot_03", "poster"],
                "reuse": ["shot_02"],
                "baseline_build_id": "test_b_base",
            }

            b_inc = await engine.run_build(
                build_id="test_b_inc",
                baseline_build=b_base,
                impact_plan=plan,
            )

            self.assertTrue(b_inc.impact_plan)
            s2 = next(s for s in b_inc.shots if s.shot_id == "shot_02")
            self.assertEqual(s2.status, "reused_from_baseline")
            self.assertEqual(s2.reused_from_build, "test_b_base")
            self.assertEqual(b_inc.operations_avoided, 1)
            self.assertEqual(b_inc.operations_reused, 1)
        finally:
            if old_mock is not None:
                os.environ["MOCK_MODE"] = old_mock
            else:
                os.environ.pop("MOCK_MODE", None)
