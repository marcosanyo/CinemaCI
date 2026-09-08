"""End-to-End Verification Test for Cinema CI/CD with Change Impact Intelligence."""

import asyncio
import json
import os
import sys

# Add project root to sys.path
sys.path.insert(0, os.path.abspath("."))
from dotenv import load_dotenv
load_dotenv(override=True)
os.environ.setdefault("STRICT_MODE", "false")
os.environ.setdefault("CINEMA_STRICT_MODE", "0")

from app.contract import load_contract
from app.engine import BuildEngine, get_all_builds, get_build, promote_build_to_release, get_all_releases
from app.generator.fixture import FixtureGenerator
from app.impact.parser import parse_creative_change_prompt
from app.impact.engine import ImpactEngine
from app.agent.agent import run_impact_agent


async def test_hero_flow():
    print("\n=======================================================")
    print("🎬 CINEMA CI/CD — END-TO-END VERIFICATION TEST")
    print("=======================================================\n")

    # Step 1: Change Prompt
    prompt = "Remove Marcus's eyeglasses (change glasses from round eyeglasses to no glasses)."
    print(f"Step 1: Creative Change Request -> '{prompt}'")

    # Step 2: Running Impact Agent (Gemini 3.8 Flash + Grafana Tempo Trace)...
    print("\nStep 2: Running Impact Agent (Gemini 3.8 Flash + Grafana Tempo Trace)...")
    plan_dict = await run_impact_agent(prompt, baseline_build_id="build_0016")

    print("\n--- Impact Plan Results ---")
    print(f"Target: {plan_dict['target']}")
    print(f"Rebuild Assets ({len(plan_dict['rebuild'])}): {plan_dict['rebuild']}")
    assert "shot_01" in plan_dict["rebuild"], "shot_01 must be in rebuild"
    assert "shot_03" in plan_dict["rebuild"], "shot_03 must be in rebuild"
    assert "poster" in plan_dict["rebuild"], "poster must be in rebuild due to runtime lineage"
    assert "shot_02" in plan_dict["reuse"], "shot_02 must be reused"
    assert plan_dict["avoided_operations"] == 1, f"Expected 1 avoided operations, got {plan_dict['avoided_operations']}"
    assert plan_dict["savings_percent"] == 25.0, f"Expected 25.0% savings, got {plan_dict['savings_percent']}"
    print("✅ Step 2 Assertions Passed!")

    # Step 3: Run Incremental Build
    print("\nStep 3: Executing Incremental Build (verifying True Blast Radius execution)...")
    contract = load_contract("cinema.yaml")
    gen = FixtureGenerator(fixtures_dir="fixtures/blue-envelope")
    engine = BuildEngine(contract, gen, "storage")

    build_id = "test_build_hero_01"
    build = await engine.run_build(build_id, None, None, plan_dict)

    print(f"\nBuild Status: {build.status.value}")
    print(f"Tests Passed: {build.tests_passed}/{build.tests_total}")
    print(f"Rebuilt Pipeline Operations: {build.operations_rebuilt}/4")
    print(f"Reused Pipeline Operations: {build.operations_reused}/4")
    print(f"Avoided Pipeline Operations: {build.operations_avoided}/4 ({build.savings_percent}% pipeline operations avoided)")

    # Veo video compute metrics
    veo_total_shots = len(contract.shots)  # 3
    veo_rebuilt_shots = sum(1 for s in build.shots if s.status == "generated")  # shot_01, shot_03 = 2
    veo_reused_shots = sum(1 for s in build.shots if s.status == "reused_from_baseline")  # shot_02 = 1
    veo_avoided_shots = veo_total_shots - veo_rebuilt_shots  # 1
    veo_savings_pct = round((veo_avoided_shots / veo_total_shots) * 100, 1)

    print(f"🎬 Veo Video Generation Avoided: {veo_avoided_shots}/{veo_total_shots} operations ({veo_savings_pct}% video-generation operations avoided)")

    assert build.status.value == "RELEASE_READY", f"Expected RELEASE_READY, got {build.status.value}"
    assert build.release_ready is True, "Expected release_ready to be True"
    assert build.operations_avoided == 1, f"Expected 1 avoided ops, got {build.operations_avoided}"
    assert veo_avoided_shots == 1, f"Expected 1 Veo call saved, got {veo_avoided_shots}"

    # Verify SHA-256 fingerprints exist for all shots
    for s in build.shots:
        print(f"  - Shot {s.shot_id} (status: {s.status}, sha256: {s.sha256})")
        assert len(s.sha256) > 0, f"Missing SHA-256 for {s.shot_id}"

    # Verify deliverable SHA-256
    for d in build.deliverables:
        print(f"  - Deliverable {d.artifact_id} (status: {d.status}, sha256: {d.sha256})")
        assert len(d.sha256) > 0, f"Missing SHA-256 for deliverable {d.artifact_id}"

    print("✅ Step 3 Assertions Passed!")

    # Step 4: Promote to Production Release (Human Approval Gate)
    print("\nStep 4: Promoting Build to Production Release (Human Approval Gate)...")
    release = promote_build_to_release(build_id, "Approved production release for Hero Demo")

    print(f"Release ID: {release.release_id}")
    print(f"Film Path: {release.film_path}")
    print(f"Pipeline Savings: {release.savings_percent}% ({release.avoided_operations} operations avoided)")
    print(f"Veo Video Generation Savings: {veo_savings_pct}% ({veo_avoided_shots} of {veo_total_shots} calls avoided)")

    assert release.release_id.startswith("release_"), "Invalid release ID"
    assert build.status.value == "RELEASED", f"Expected RELEASED, got {build.status.value}"
    assert build.is_released is True, "Expected is_released to be True"

    all_rel = get_all_releases()
    assert len(all_rel) > 0, "Expected at least 1 recorded release"
    print("✅ Step 4 Assertions Passed!")

    # Clean up test build artifact from in-memory engine and storage
    import shutil
    from app.engine import _builds, save_builds_to_disk
    if build_id in _builds:
        del _builds[build_id]
        save_builds_to_disk()
    if os.path.exists(f"storage/{build_id}"):
        shutil.rmtree(f"storage/{build_id}", ignore_errors=True)

    print("\n🎉 ALL HERO DEMO VERIFICATION CHECKS PASSED PERFECTLY!\n")


if __name__ == "__main__":
    asyncio.run(test_hero_flow())
