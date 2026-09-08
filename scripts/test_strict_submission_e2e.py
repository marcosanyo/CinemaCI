"""Strict submission integration verification for Cinema CI.

This suite intentionally uses FixtureGenerator for deterministic shot bytes while exercising:
- real Google ADK agent orchestration
- real official mcp-grafana tool calls
- real Grafana Tempo runtime lineage retrieval
- deterministic impact calculation
- causal poster lineage (selected generated shot -> actual poster materialization)
- SHA-256 byte-identical reuse
- strict QA and release logic

It does NOT claim live Veo execution; deployed Veo / Cloud Run Job evidence is captured separately.
"""

import asyncio
import os
import sys

sys.path.insert(0, os.path.abspath("."))

from dotenv import load_dotenv
load_dotenv(override=True)

os.environ["STRICT_MODE"] = "true"
os.environ["CINEMA_STRICT_MODE"] = "1"

from app.telemetry import setup_telemetry
setup_telemetry()

from app.contract import load_contract
from app.engine import BuildEngine, promote_build_to_release
from app.generator.fixture import FixtureGenerator
from app.agent.mcp_grafana import mcp_client
from app.agent.agent import run_impact_agent, get_agent_activity, get_agent_mode


async def run_strict_submission_e2e():
    print("\n=======================================================")
    print("CINEMA CI — STRICT SUBMISSION INTEGRATION VERIFICATION")
    print("=======================================================\n")

    mcp_client.reset_fallback_counter()

    prompt = "Remove Marcus's eyeglasses (change glasses from round eyeglasses to no glasses)."
    print(f"Creative Instruction: '{prompt}'")
    print(f"Strict Mode: {mcp_client.is_strict_mode()}")

    contract = load_contract("cinema.yaml")
    gen = FixtureGenerator(fixtures_dir="fixtures/blue-envelope")
    engine = BuildEngine(contract, gen, "storage")

    print("\n[Step 0] Establishing deterministic baseline + runtime lineage...")
    baseline_id = "test_baseline_strict_01"
    baseline_build = await engine.run_build(baseline_id)
    assert baseline_build.release_ready is True
    assert baseline_build.trace_id

    baseline_poster = next(d for d in baseline_build.deliverables if d.artifact_id == "poster")
    assert baseline_poster.details.get("poster_materialization") == "actual_selected_generated_keyframe"
    baseline_selected_shot_id = baseline_poster.details.get("selected_shot_id")
    baseline_selected_shot = next(s for s in baseline_build.shots if s.shot_id == baseline_selected_shot_id)
    assert baseline_poster.details.get("source_shot_sha256") == baseline_selected_shot.sha256
    assert int(baseline_poster.details.get("visual_candidates_evaluated", 0)) >= 1
    print(
        "  Causal poster lineage verified: "
        f"{baseline_selected_shot_id} ({baseline_selected_shot.sha256}) -> poster"
    )

    print("\n[Step 1] Invoking Google ADK Agent for Change Impact Analysis...")
    plan_dict = await run_impact_agent(prompt, baseline_build_id=baseline_id)

    print(f"Agent Execution Mode: {get_agent_mode()}")
    print(f"Target: {plan_dict.get('target')}")
    print(f"Rebuild Assets: {plan_dict.get('rebuild')}")
    print(f"Reuse Assets: {plan_dict.get('reuse')}")

    activity = get_agent_activity()
    tools_called = {step.tool_name for step in activity if step.tool_name}
    assert "get_contract_info" in tools_called
    assert "get_baseline_build_trace" in tools_called
    assert "compute_deterministic_impact" in tools_called
    print(f"ADK Agent Tools Called: {tools_called}")

    declared_count = plan_dict.get("declared_dependency_count")
    runtime_count = plan_dict.get("observed_runtime_dependency_count")
    assert declared_count == 2, f"Expected 2 declared dependencies, got {declared_count}"
    assert runtime_count == 1, f"Expected 1 runtime dependency, got {runtime_count}"
    assert set(plan_dict["rebuild"]) == {"shot_01", "shot_03", "poster"}
    assert set(plan_dict["reuse"]) == {"shot_02"}
    assert plan_dict["avoided_operations"] == 1
    assert plan_dict["savings_percent"] == 25.0

    print("\n[Step 2] Executing incremental build with exact baseline + SHA-256 proof...")
    build_id = "test_build_strict_submission_01"
    # Pass the exact test baseline object. Test IDs are deliberately excluded from normal
    # latest-production-build discovery, so relying on get_latest_passed_build here would
    # make this E2E vulnerable to an unrelated persisted build masking a broken baseline link.
    build = await engine.run_build(build_id, baseline_build, None, plan_dict)

    assert build.status.value == "RELEASE_READY"
    assert build.release_ready is True
    assert build.tests_passed == build.tests_total
    assert build.operations_rebuilt == 3
    assert build.operations_reused == 1
    assert build.operations_avoided == 1

    gen_total = len(contract.shots)
    gen_rebuilt = sum(1 for s in build.shots if s.status == "generated")
    gen_avoided = gen_total - gen_rebuilt
    assert gen_avoided == 1

    print(f"Build Status: {build.status.value}")
    print(f"Quality Gate: {build.tests_passed}/{build.tests_total} passed")
    print(f"Pipeline Artifact Operations Avoided: {build.operations_avoided}/4 ({build.savings_percent}%)")
    print(f"Video Generation Operations Avoided: {gen_avoided}/{gen_total}")
    print("Video Generator in this deterministic test: FixtureGenerator (NOT live Veo proof)")

    for shot in build.shots:
        assert shot.sha256
        if shot.status == "reused_from_baseline":
            baseline_shot = next(s for s in baseline_build.shots if s.shot_id == shot.shot_id)
            assert shot.sha256 == baseline_shot.sha256
            print(f"  SHA-256 byte-identical reuse: {shot.shot_id} ({shot.sha256})")

    for deliverable in build.deliverables:
        assert deliverable.sha256
        if deliverable.status == "reused_from_baseline":
            baseline_deliverable = next(
                d for d in baseline_build.deliverables if d.artifact_id == deliverable.artifact_id
            )
            assert deliverable.sha256 == baseline_deliverable.sha256
            print(f"  SHA-256 byte-identical reuse: {deliverable.artifact_id} ({deliverable.sha256})")

    # Incremental poster is rebuilt and must again consume the selected shot that exists in this build.
    poster = next(d for d in build.deliverables if d.artifact_id == "poster")
    assert poster.details.get("poster_materialization") == "actual_selected_generated_keyframe"
    selected_shot_id = poster.details.get("selected_shot_id")
    selected_shot = next(s for s in build.shots if s.shot_id == selected_shot_id)
    assert poster.details.get("source_shot_sha256") == selected_shot.sha256
    assert int(poster.details.get("visual_candidates_evaluated", 0)) >= 1

    print("\n[Step 3] Verifying real Grafana Tempo-backed Viewer evidence...")
    from app.main import api_telemetry_trace
    trace_view = await api_telemetry_trace(baseline_id)
    assert trace_view["is_real_tempo"] is True
    assert trace_view["source"] == "official-mcp-grafana"
    assert trace_view["trace_id"] == baseline_build.trace_id

    runtime_spans = [s for s in trace_view["spans"] if "reference.select" in s.get("name", "")]
    assert runtime_spans, "Tempo must contain cinema.reference.select"
    discovery = plan_dict.get("runtime_discoveries", [{}])[0]
    discovery_ref = discovery.get("selected_reference")
    tempo_ref = runtime_spans[0]["attributes"].get("cinema.reference.selected")
    assert discovery_ref == tempo_ref
    assert tempo_ref == baseline_poster.details.get("selected_reference")
    print(f"  Tempo source verified: {trace_view['source']}")
    print(f"  Runtime selected reference verified end-to-end: {tempo_ref}")

    print("\n[Step 4] Promoting verified build to release...")
    release = promote_build_to_release(build_id, "Submission integration verified")
    assert release.release_id.startswith("release_")

    fallbacks_count = mcp_client.get_fallback_count()
    assert fallbacks_count == 0, f"Strict integration used {fallbacks_count} Grafana fallbacks"

    import shutil
    from app.engine import _builds, save_builds_to_disk
    for test_id in (build_id, baseline_id):
        _builds.pop(test_id, None)
        if os.path.exists(f"storage/{test_id}"):
            shutil.rmtree(f"storage/{test_id}", ignore_errors=True)
    save_builds_to_disk()

    print("\n=======================================================")
    print("STRICT SUBMISSION INTEGRATION PASSED")
    print("=======================================================")
    print("  Google ADK Agent             EXECUTED")
    print("  Official mcp-grafana         EXECUTED")
    print("  Grafana Tempo lineage        QUERIED")
    print("  Causal poster dependency     VERIFIED")
    print("  Deterministic ImpactEngine   VERIFIED")
    print(f"  QA Gate                      {build.tests_passed}/{build.tests_total} PASS")
    print("  Artifact operations avoided  1 / 4 (25.0%)")
    print("  Video generations avoided    1 / 3")
    print("  Live Veo execution           NOT ASSERTED BY THIS TEST")
    print(f"  Grafana fallbacks            {fallbacks_count}")
    print("=======================================================\n")


if __name__ == "__main__":
    asyncio.run(run_strict_submission_e2e())
