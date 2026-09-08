"""Unit tests for contract snapshot sync and glasses-removal rewriting."""

import tempfile
import unittest

from app.contract import (
    get_baseline_contract,
    load_shared_contract_snapshot,
    publish_contract_snapshot,
    rewrite_description_remove_glasses,
)
from app.store.artifact_local import LocalArtifactStore


class TestGlassesRemovalRewrite(unittest.TestCase):

    def test_single_clean_negation(self):
        desc = ("Marcus, a man with clean short fade haircut, and thin-rimmed round eyeglasses,"
                " wearing a tailored coat.")
        out = rewrite_description_remove_glasses(desc)
        self.assertIn("no glasses", out.lower())
        # No garbled double negation, no dangling eyewear nouns
        self.assertNotIn("no no glasses", out.lower())
        self.assertNotIn("eyeglasses", out.lower())
        self.assertNotIn("thin-rimmed round", out.lower())

    def test_idempotent_when_already_removed(self):
        desc = "Marcus enters the cafe. He wears no glasses; his face is bare."
        out = rewrite_description_remove_glasses(desc)
        self.assertEqual(out.lower().count("no glasses"), 1)


class TestContractSnapshotSync(unittest.TestCase):

    def test_publish_and_load_roundtrip(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = LocalArtifactStore(root_dir=tmp)
            contract = get_baseline_contract()
            contract.characters["marcus"].traits["glasses"] = "no glasses"
            publish_contract_snapshot(store, contract)
            loaded = load_shared_contract_snapshot(store, contract.project.id)
            self.assertIsNotNone(loaded)
            self.assertEqual(loaded.characters["marcus"].traits["glasses"], "no glasses")

    def test_missing_snapshot_returns_none(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = LocalArtifactStore(root_dir=tmp)
            self.assertIsNone(load_shared_contract_snapshot(store, "no-such-project"))


if __name__ == "__main__":
    unittest.main()
