"""Cinema CI — Google ADK Agent Tools.

Callable tools exposed to the Google ADK Agent during Change Impact
Intelligence and Autonomous Reliability workflows.
"""

from __future__ import annotations

import asyncio
import concurrent.futures
import json
import logging
import os
from typing import Any

logger = logging.getLogger(__name__)


def get_build_info(build_id: str) -> dict[str, Any]:
    """Retrieves detailed information about a specific Cinema CI build.

    Includes build status, test results, shot artifacts, deliverables,
    and release eligibility.

    Args:
        build_id: Unique build identifier (e.g. 'build_0001').

    Returns:
        Serialized build dictionary, or error object if not found.
    """
    from app.engine import get_build
    build = get_build(build_id)
    if build:
        return build.model_dump()
    return {"error": f"Build {build_id} not found"}


def get_failing_tests(build_id: str) -> list[dict[str, Any]]:
    """Retrieves all FAIL and REGRESSION test results for a specific build.

    Used by the reliability agent to diagnose root cause failures before repair.

    Args:
        build_id: Unique build identifier.

    Returns:
        List of serialized failing TestResult records.
    """
    from app.engine import get_build
    build = get_build(build_id)
    if not build:
        return [{"error": f"Build {build_id} not found"}]

    return [
        t.model_dump()
        for t in build.test_results
        if t.status.value in ("FAIL", "REGRESSION")
    ]


def get_contract_info() -> dict[str, Any]:
    """Retrieves the active Creative Contract (cinema.yaml).

    Provides explicit project specifications, characters, traits, props,
    shot requirements, and release quality gates.

    Returns:
        Serialized CinemaContract dictionary.
    """
    from app.contract import load_contract
    from app.telemetry import get_tracer
    with get_tracer().start_as_current_span(
        "execute_tool get_contract_info",
        attributes={"cinema.tool": "get_contract_info"},
    ):
        try:
            loaded = load_contract(os.getenv("CINEMA_CONTRACT_PATH", "cinema.yaml"))
            return loaded.model_dump()
        except Exception as exc:
            return {"error": f"Failed to load contract: {exc}"}


def regenerate_shot(
    project_id: str,
    shot_id: str,
    repair_instruction: str = "",
    shots_to_regenerate: str | list[str] = "",
) -> dict[str, Any]:
    """Triggers surgical regeneration of failing shots while reusing passing ones.

    Unaffected shots are preserved and byte-identically reused from baseline.

    Args:
        project_id: The project identifier.
        shot_id: Primary shot to regenerate (e.g. 'shot_02').
        repair_instruction: Detailed diagnosis explaining the repair intent.
        shots_to_regenerate: Optional comma-separated list or array of shots to rebuild.

    Returns:
        Trigger confirmation status dictionary.
    """
    from app.engine import _builds, get_latest_build, get_next_build_id
    from app.models import Build

    latest = get_latest_build(project_id)
    if not latest:
        return {"error": "No existing build found to repair"}

    if isinstance(shots_to_regenerate, list):
        target_shots = [str(s).strip() for s in shots_to_regenerate if str(s).strip()]
    elif isinstance(shots_to_regenerate, str) and shots_to_regenerate:
        target_shots = [s.strip() for s in shots_to_regenerate.split(",") if s.strip()]
    elif shot_id:
        target_shots = [shot_id.strip()]
    else:
        target_shots = ["shot_02", "shot_04"]

    new_build_id = get_next_build_id()
    new_build = Build(
        build_id=new_build_id,
        project_id=project_id,
        repair_of=latest.build_id,
    )
    _builds[new_build_id] = new_build

    try:
        from app.contract import save_contract
        from app.main import engine, generator

        # Configure generator to clean state (repair mode)
        if hasattr(generator, "use_regression_fixtures"):
            generator.use_regression_fixtures = False
        if hasattr(generator, "introduce_regression"):
            generator.introduce_regression = False

        # Apply prompt hardening to contract specifications
        for s in engine.contract.shots:
            if s.id in target_shots:
                s.description = (
                    s.description
                    .replace("red leather jacket", "black coat")
                    .replace("red coat", "black coat")
                    .replace("bare face", "")
                    .replace(", ,", ",")
                )
                if "no glasses" not in s.description and "no eyeglasses" not in s.description:
                    s.description += ", wearing no eyeglasses"
                if "black coat" not in s.description and "black wool coat" not in s.description:
                    s.description += ", wearing a black wool coat"

        save_contract(engine.contract, os.getenv("CINEMA_CONTRACT_PATH", "cinema.yaml"))

        # Dispatch asynchronous build
        asyncio.ensure_future(
            engine.run_build(new_build_id, latest, target_shots)
        )

        return {
            "status": "triggered",
            "new_build_id": new_build_id,
            "shots_regenerated": target_shots,
            "repair_instruction": repair_instruction,
            "baseline_build": latest.build_id,
        }
    except Exception as exc:
        return {"error": f"Failed to trigger regeneration: {exc}"}


def release_build(build_id: str) -> dict[str, Any]:
    """Marks a build as released if all QA gates pass.

    Release is blocked if there are failing/regression tests, unverified tests,
    or if the build is still executing.

    Args:
        build_id: Unique build identifier.

    Returns:
        Release status dictionary.
    """
    from app.engine import get_build
    from app.models import BuildStatus

    build = get_build(build_id)
    if not build:
        return {"error": f"Build {build_id} not found"}

    if build.status in (BuildStatus.QUEUED, BuildStatus.GENERATING, BuildStatus.TESTING):
        return {
            "error": (
                f"Cannot release build {build_id}: Build is in progress ({build.status.value}). "
                "Wait for QA test evaluation to complete."
            )
        }

    failing = [t for t in build.test_results if t.status.value in ("FAIL", "REGRESSION")]
    if failing or build.unknowns > 0 or build.tests_total == 0 or build.tests_passed < build.tests_total:
        return {
            "error": (
                f"Cannot release build {build_id}: {len(failing)} tests failed, {build.unknowns} unknown, "
                f"{build.tests_passed}/{build.tests_total} passed. Quality gate is strictly BLOCKED."
            )
        }

    build.release_ready = True
    build.status = BuildStatus.PASSED
    return {"status": "released", "build_id": build_id}


def query_grafana_metrics(query: str) -> dict[str, Any]:
    """Executes PromQL queries against Grafana Cloud Prometheus via MCP.

    Standard query examples:
      - 'cinema_ci_active_regressions' — count of active regressions.
      - 'cinema_ci_test_pass_ratio' — ratio of passing QA tests.
      - 'cinema_ci_release_ready' — quality gate binary status.
      - 'cinema_ci_builds_total' — cumulative count of builds.

    Args:
        query: PromQL query expression.

    Returns:
        Structured Prometheus query response.
    """
    from app.agent.mcp_grafana import mcp_client
    return mcp_client.call_tool("grafana_prometheus_query", {"query": query})


def query_grafana_logs(query: str) -> dict[str, Any]:
    """Executes LogQL queries against Grafana Cloud Loki via MCP.

    Standard query examples:
      - '{service_name="cinema-ci"} | json | status="REGRESSION"'
      - '{service_name="cinema-ci"} | json | event="cinema_test_result"'

    Args:
        query: LogQL query expression.

    Returns:
        Structured Loki log streams response.
    """
    from app.agent.mcp_grafana import mcp_client
    return mcp_client.call_tool("grafana_loki_query", {"query": query})


def query_grafana_traces(query: str) -> dict[str, Any]:
    """Queries distributed OpenTelemetry traces from Grafana Tempo via MCP.

    Used to discover dynamic runtime reference selections and causal lineage.

    Args:
        query: Trace ID or TraceQL query expression.

    Returns:
        Structured Tempo trace response.
    """
    from app.agent.mcp_grafana import mcp_client
    return mcp_client.call_tool("grafana_tempo_query", {"query": query})


def get_baseline_build_trace(build_id: str) -> dict[str, Any]:
    """Retrieves OpenTelemetry Tempo trace spans for a specific baseline build.

    Discovers dynamic runtime references (e.g. poster consuming shot keyframes).

    Args:
        build_id: Baseline build identifier (e.g. 'build_0016').

    Returns:
        Trace representation containing execution spans.
    """
    from app.agent.mcp_grafana import mcp_client
    from app.engine import get_build
    from app.telemetry import get_tracer

    build = get_build(build_id)
    trace_id = build.trace_id if (build and build.trace_id) else build_id
    with get_tracer().start_as_current_span(
        "execute_tool get_baseline_build_trace",
        attributes={
            "cinema.tool": "get_baseline_build_trace",
            "cinema.mcp_server": "mcp-grafana (official, STDIO)",
            "cinema.baseline_build_id": build_id,
            "cinema.trace_id": trace_id,
        },
    ):
        res = mcp_client.call_tool("grafana_tempo_query", {"traceId": trace_id, "build_id": build_id})
        if isinstance(res, dict) and build and getattr(build, "spans", None):
            if (
                not res.get("spans")
                and not res.get("batches")
                and not res.get("resourceSpans")
                and not res.get("trace")
                and not res.get("services")
            ):
                res["spans"] = build.spans
        return res


def compute_deterministic_impact(
    change_prompt: str,
    baseline_build_id: str = "",
) -> dict[str, Any]:
    """Computes True Blast Radius (Declared ∪ Observed) via ImpactEngine.

    Partitions pipeline assets into REBUILD, REVALIDATE, and REUSE without LLM
    hallucination in graph reachability.

    Args:
        change_prompt: Filmmaker natural language change instruction.
        baseline_build_id: Optional baseline build ID to query runtime trace from.

    Returns:
        Serialized ImpactPlan dictionary.
    """
    from app.contract import load_contract
    from app.engine import get_latest_passed_build
    from app.impact import ImpactEngine
    from app.impact.parser import parse_creative_change_prompt
    from app.telemetry import get_tracer

    contract = load_contract(os.getenv("CINEMA_CONTRACT_PATH", "cinema.yaml"))
    engine = ImpactEngine(contract)

    if not baseline_build_id:
        baseline = get_latest_passed_build(contract.project.id)
        baseline_build_id = baseline.build_id if baseline else "build_0016"

    with get_tracer().start_as_current_span(
        "execute_tool compute_deterministic_impact",
        attributes={
            "cinema.tool": "compute_deterministic_impact",
            "cinema.mcp_server": "mcp-grafana (official, STDIO)",
            "cinema.change_prompt": change_prompt[:240],
            "cinema.baseline_build_id": baseline_build_id,
        },
    ) as span:
        # Step 1: Semantic parsing of creative change prompt
        try:
            loop = asyncio.get_running_loop()
            with concurrent.futures.ThreadPoolExecutor() as pool:
                change_req = pool.submit(lambda: asyncio.run(parse_creative_change_prompt(change_prompt))).result()
        except RuntimeError:
            change_req = asyncio.run(parse_creative_change_prompt(change_prompt))

        # Step 2: Retrieve baseline execution trace
        trace_res = get_baseline_build_trace(baseline_build_id)
        trace_data = trace_res
        if isinstance(trace_res, dict) and "spans" not in trace_res:
            trace_data = trace_res.get("data") or trace_res.get("trace") or trace_res

        # Step 3: Execute deterministic graph impact traversal
        plan = engine.compute_impact(
            change_req,
            baseline_build_id,
            trace_data=trace_data if isinstance(trace_data, dict) else None,
        )
        span.set_attribute("cinema.rebuild", ",".join(plan.rebuild))
        span.set_attribute("cinema.reuse", ",".join(plan.reuse))
        return plan.model_dump()


def get_firing_alerts() -> dict[str, Any]:
    """Retrieves active firing alerts from Grafana Alertmanager via MCP.

    Primary entry point for incident investigation and root-cause analysis.

    Returns:
        Dictionary of active firing alerts.
    """
    from app.agent.mcp_grafana import mcp_client
    return mcp_client.call_tool("grafana_get_alerts", {})


async def analyze_creative_impact(
    change_prompt: str,
    baseline_build_id: str = "",
) -> dict[str, Any]:
    """Orchestrates end-to-end Change Impact Intelligence analysis."""
    return compute_deterministic_impact(change_prompt, baseline_build_id)


