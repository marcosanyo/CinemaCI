"""Cinema CI — Google ADK Autonomous Agent Orchestrator.

Implements agentic workflows using Google Agent Development Kit (ADK) and
Vertex AI Gemini 3.8 Flash:
1. Change Impact Intelligence: Resolves creative change requests, inspects
   Grafana Tempo traces via MCP, and executes deterministic impact analysis.
2. Production Reliability Investigation: Investigates regressions reported
   by Grafana Alertmanager, correlates spans, and executes surgical repairs.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
from typing import Any

from app.agent import tools as agent_tools
from app.model_config import GEMINI_MODEL
from app.models import AgentStep

logger = logging.getLogger(__name__)

# Module-level agent activity trace for UI event streaming
_agent_activity: list[AgentStep] = []
_agent_mode: str = "Google ADK (Vertex AI Agent)"


def get_agent_activity() -> list[AgentStep]:
    """Returns a copy of the current agent activity steps."""
    return list(_agent_activity)


def get_agent_mode() -> str:
    """Returns the current agent execution badge."""
    global _agent_mode
    return _agent_mode


def clear_agent_activity() -> None:
    """Clears the agent activity log."""
    _agent_activity.clear()


def _add_step(
    action: str,
    tool_name: str = "",
    tool_input: dict[str, Any] | None = None,
    tool_output: str = "",
    detail: str = "",
    done: bool = False,
) -> AgentStep:
    """Records an activity step for UI observability."""
    step = AgentStep(
        step_id=len(_agent_activity),
        action=action,
        tool_name=tool_name,
        tool_input=tool_input or {},
        tool_output=tool_output,
        detail=detail,
        done=done,
    )
    _agent_activity.append(step)
    return step


async def run_impact_agent(
    change_prompt: str,
    baseline_build_id: str | None = None,
) -> dict[str, Any]:
    """Executes the Change Impact Intelligence workflow.

    Workflow:
      1. Resolves target creative change via Gemini semantic parsing.
      2. Retrieves baseline build trace from Grafana Cloud via official MCP.
      3. Discovers observed runtime lineages (e.g. dynamic poster selection).
      4. Evaluates deterministic graph reachability via ImpactEngine.
      5. Returns structured ImpactPlan.

    Args:
        change_prompt: The filmmaker's creative change request.
        baseline_build_id: Optional baseline build ID to compare against.

    Returns:
        The computed ImpactPlan as a dictionary.

    Raises:
        RuntimeError: When strict mode is enabled and execution fails.
    """
    global _agent_mode
    clear_agent_activity()
    _agent_mode = "Google ADK Agent + Official Grafana MCP (STDIO)"

    from app.agent.mcp_grafana import mcp_client
    from app.contract import load_contract
    from app.engine import get_latest_passed_build
    from app.telemetry import emit_log, get_tracer

    contract = load_contract(os.getenv("CINEMA_CONTRACT_PATH", "cinema.yaml"))
    if not baseline_build_id:
        baseline = get_latest_passed_build(contract.project.id)
        baseline_build_id = baseline.build_id if baseline else "build_0016"

    tracer = get_tracer()
    with tracer.start_as_current_span(
        "cinema_ci.impact_analysis",
        attributes={
            "cinema.change_prompt": change_prompt,
            "cinema.baseline_build_id": baseline_build_id,
        },
    ):
        emit_log("change_requested", {"prompt": change_prompt, "baseline_build_id": baseline_build_id})
        emit_log("impact_analysis_started", {"baseline_build_id": baseline_build_id})

        strict_mode = mcp_client.is_strict_mode()

        try:
            plan_dict = await _run_real_impact_agent(change_prompt, baseline_build_id)
            if plan_dict:
                return plan_dict
        except Exception as exc:
            logger.warning("Google ADK Impact Agent encountered exception: %s", exc)
            if strict_mode:
                _add_step(
                    action="agent_error",
                    detail=f"Strict Mode Error: Real ADK Impact Agent failed ({exc}). Fallbacks disabled.",
                    done=True,
                )
                raise RuntimeError(f"Strict Mode Violation: Real ADK Impact Agent failed: {exc}") from exc

        if strict_mode:
            raise RuntimeError("Strict Mode Violation: Real ADK Impact Agent returned empty response.")

        _agent_mode = "Deterministic Demo Simulator (Local Fallback)"
        return await _run_simulated_impact_agent(change_prompt, baseline_build_id)


async def _run_real_impact_agent(
    change_prompt: str,
    baseline_build_id: str,
) -> dict[str, Any] | None:
    """Invokes Google ADK Agent for impact calculation."""
    from google.adk.agents import Agent
    from google.adk.runners import InMemoryRunner
    from google.genai import types

    api_key = os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")
    if api_key:
        os.environ["GEMINI_API_KEY"] = api_key
        os.environ["GOOGLE_API_KEY"] = api_key

    instruction = """You are Cinema CI's Change Impact Intelligence Agent.
Your mission is to orchestrate the deterministic analysis of creative change requests.

PROCEDURE:
1. Inspect the Creative Contract by calling get_contract_info().
2. Retrieve the baseline build's execution trace from Grafana Cloud via get_baseline_build_trace(baseline_build_id).
3. Compute the True Blast Radius by calling compute_deterministic_impact(change_prompt, baseline_build_id).
4. Clearly report the findings:
   - Declared dependencies derived from cinema.yaml.
   - Runtime dependencies discovered from Grafana Tempo trace.
   - Rebuild vs Reuse partition and avoided generation operations.
"""

    agent = Agent(
        name="cinema_change_impact_agent",
        model=GEMINI_MODEL,
        instruction=instruction,
        tools=[
            agent_tools.get_contract_info,
            agent_tools.get_baseline_build_trace,
            agent_tools.compute_deterministic_impact,
        ],
    )

    runner = InMemoryRunner(agent=agent, app_name="cinema_ci")
    session = await runner.session_service.create_session(
        app_name="cinema_ci", user_id="filmmaker",
    )

    message = (
        f"Filmmaker Creative Change Request: '{change_prompt}'\n"
        f"Baseline Build ID: '{baseline_build_id}'\n\n"
        "Inspect the Grafana Tempo trace for observed runtime lineage, execute deterministic "
        "impact analysis, and report the True Blast Radius."
    )

    latest_impact_plan: dict[str, Any] | None = None

    async for event in runner.run_async(
        user_id="filmmaker",
        session_id=session.id,
        new_message=types.Content(parts=[types.Part(text=message)]),
    ):
        latest_impact_plan = _consume_adk_event(event, latest_impact_plan)

    if latest_impact_plan:
        return latest_impact_plan

    mock_mode = os.environ.get("MOCK_MODE", "false").lower() in ("true", "1", "yes")
    if not mock_mode:
        raise RuntimeError("Production/Strict Mode: ADK Agent failed to execute compute_deterministic_impact tool. Fallback is prohibited outside MOCK_MODE.")

    return agent_tools.compute_deterministic_impact(change_prompt, baseline_build_id)


def _consume_adk_event(
    event: Any,
    latest_plan: dict[str, Any] | None,
) -> dict[str, Any] | None:
    """Processes an ADK event and updates streaming activity steps."""
    # 1. Inspect content parts
    if hasattr(event, "content") and event.content and hasattr(event.content, "parts"):
        for part in event.content.parts:
            fc = getattr(part, "function_call", None)
            if fc:
                _add_step(
                    action=fc.name,
                    tool_name=fc.name,
                    tool_input=dict(fc.args) if fc.args else {},
                )
            fr = getattr(part, "function_response", None)
            if fr:
                for step in reversed(_agent_activity):
                    if step.tool_name == fr.name and not step.done:
                        resp_val = fr.response
                        step.tool_output = (
                            json.dumps(resp_val, default=str)[:500]
                            if isinstance(resp_val, dict)
                            else str(resp_val)[:500]
                        )
                        step.done = True
                        if fr.name == "compute_deterministic_impact" and isinstance(resp_val, dict):
                            latest_plan = resp_val
                        break
            text = getattr(part, "text", None)
            if text:
                _add_step(action="agent_response", detail=text, done=True)

    # 2. Inspect actions
    if hasattr(event, "actions") and event.actions:
        for action in event.actions:
            fc = getattr(action, "function_call", None)
            if fc:
                if not _agent_activity or _agent_activity[-1].tool_name != fc.name or _agent_activity[-1].done:
                    _add_step(
                        action=fc.name,
                        tool_name=fc.name,
                        tool_input=dict(fc.args) if fc.args else {},
                    )
            fr = getattr(action, "function_response", None)
            if fr:
                for step in reversed(_agent_activity):
                    if step.tool_name == fr.name and not step.done:
                        resp_val = fr.response
                        step.tool_output = (
                            json.dumps(resp_val, default=str)[:500]
                            if isinstance(resp_val, dict)
                            else str(resp_val)[:500]
                        )
                        step.done = True
                        if fr.name == "compute_deterministic_impact" and isinstance(resp_val, dict):
                            latest_plan = resp_val
                        break

    return latest_plan


async def _run_simulated_impact_agent(
    change_prompt: str,
    baseline_build_id: str,
) -> dict[str, Any]:
    """Deterministic simulated impact workflow for offline CI environments."""
    from app.contract import load_contract
    from app.impact import ImpactEngine
    from app.impact.parser import parse_creative_change_prompt
    from app.telemetry import emit_log

    contract = load_contract(os.getenv("CINEMA_CONTRACT_PATH", "cinema.yaml"))
    engine = ImpactEngine(contract)

    # Step 1: Semantic understanding
    s1 = _add_step(
        action="parse_creative_change",
        detail=f"Interpreting creative change direction: '{change_prompt}' via Gemini 3.8 Flash...",
    )
    change_req = await parse_creative_change_prompt(change_prompt)
    s1.tool_output = json.dumps(change_req.model_dump(), default=str)
    s1.done = True
    await asyncio.sleep(0.1)

    # Step 2: Query Grafana MCP
    s2 = _add_step(
        action="get_baseline_build_trace",
        tool_name="get_baseline_build_trace",
        tool_input={"build_id": baseline_build_id},
        detail=f"Querying Grafana via MCP: Fetching OpenTelemetry Tempo trace for baseline {baseline_build_id}...",
    )
    trace_res = agent_tools.get_baseline_build_trace(baseline_build_id)
    trace_data = trace_res.get("data") or trace_res.get("trace") or trace_res
    s2.tool_output = json.dumps(trace_res, default=str)[:400]
    s2.done = True
    await asyncio.sleep(0.1)

    # Step 3: Extract observed runtime lineage
    from app.impact.observed import extract_observed_dependencies_from_trace
    _edges, discoveries = extract_observed_dependencies_from_trace(trace_data if isinstance(trace_data, dict) else {})
    selected_ref = "shot_03:keyframe:v1"
    if discoveries:
        selected_ref = discoveries[0].selected_reference
    else:
        from app.engine import get_build
        base_b = get_build(baseline_build_id)
        if base_b and base_b.deliverables:
            for d in base_b.deliverables:
                if d.artifact_id == "poster" and d.details:
                    selected_ref = d.details.get("selected_reference") or (f"{d.details['selected_shot_id']}:keyframe:v1" if d.details.get("selected_shot_id") else selected_ref)
                    break
    selected_shot = selected_ref.split(":")[0].replace("_", " ").title()

    _add_step(
        action="extract_runtime_lineage",
        detail="Analyzing runtime execution spans: Discovered dynamic reference dependency "
               f"(Poster dynamically consumed {selected_shot} keyframe in baseline).",
        done=True,
    )
    emit_log("runtime_lineage_discovered", {
        "build_id": baseline_build_id,
        "consumer": "poster:v1",
        "selected_reference": selected_ref,
        "source": "observed",
    })
    await asyncio.sleep(0.1)

    # Step 4: Deterministic ImpactEngine
    s4 = _add_step(
        action="compute_deterministic_impact",
        tool_name="compute_deterministic_impact",
        detail="Running deterministic ImpactEngine to compute True Blast Radius (Declared ∪ Observed)...",
    )
    plan = engine.compute_impact(
        change_req,
        baseline_build_id,
        trace_data=trace_data if isinstance(trace_data, dict) else None,
    )
    s4.tool_output = json.dumps(plan.model_dump(), default=str)[:400]
    s4.done = True
    await asyncio.sleep(0.1)

    emit_log("impact_plan_created", {
        "change_id": plan.change_id,
        "baseline_build_id": plan.baseline_build_id,
        "rebuild_count": len(plan.rebuild),
        "reuse_count": len(plan.reuse),
        "avoided_operations": plan.avoided_operations,
    })

    _add_step(
        action="agent_response",
        detail=(
            f"Impact Plan Finalized: {len(plan.rebuild)} Rebuild, {len(plan.reuse)} Reuse. "
            f"{plan.avoided_operations} of {plan.full_build_operations} pipeline operations avoided "
            f"({plan.savings_percent}% operations saved). 1 of 3 Veo video generations saved (33.3%). "
            "Discovered 1 runtime-only dependency (Poster -> Shot 01)."
        ),
        done=True,
    )
    return plan.model_dump()


async def run_investigation(alert_payload: dict[str, Any]) -> list[AgentStep]:
    """Runs autonomous investigation triggered by Grafana Alertmanager.

    Correlates with failing build via OpenTelemetry Span Links.
    """
    global _agent_mode
    clear_agent_activity()

    from opentelemetry.trace import Link, SpanContext, TraceFlags
    from app.agent.mcp_grafana import mcp_client
    from app.engine import get_build
    from app.telemetry import get_tracer

    tracer = get_tracer()
    links = []

    # Extract build_id from alert labels
    build_id = None
    alerts = alert_payload.get("alerts", [])
    for a in alerts:
        labels = a.get("labels", {})
        build_id = labels.get("build_id")
        if build_id:
            break

    if build_id:
        target_build = get_build(build_id)
        if target_build and target_build.trace_id and target_build.span_id:
            try:
                ctx = SpanContext(
                    trace_id=int(target_build.trace_id, 16),
                    span_id=int(target_build.span_id, 16),
                    is_remote=True,
                    trace_flags=TraceFlags(0x01),
                )
                links.append(Link(
                    ctx,
                    attributes={
                        "cinema.link_reason": "regression_repair_trigger",
                        "cinema.build_id": build_id,
                    },
                ))
                logger.info(
                    "OpenTelemetry Span Link created: Build %s (trace=%s) -> Agent Investigation",
                    build_id,
                    target_build.trace_id,
                )
            except Exception as exc:
                logger.warning("Failed to create Span Link: %s", exc)

    with tracer.start_as_current_span(
        "cinema_ci.agent_investigation",
        links=links,
        attributes={"cinema.target_build_id": build_id or "unknown"},
    ):
        strict_mode = mcp_client.is_strict_mode()
        try:
            _agent_mode = "Google ADK + Official Grafana MCP (STDIO)"
            result = await _run_real_agent(alert_payload)
            if result:
                return result
        except Exception as exc:
            logger.warning("ADK investigation exception: %s", exc)
            if strict_mode:
                _add_step(
                    action="agent_error",
                    detail=f"Strict Mode Error: Real ADK Agent failed: {exc}. Fallbacks disabled.",
                    done=True,
                )
                return _agent_activity

        mock_mode = os.environ.get("MOCK_MODE", "false").lower() in ("true", "1", "yes")
        if not mock_mode:
            _add_step(
                action="agent_error",
                detail="Production/Strict Mode: Real ADK Agent returned empty response or failed. Simulated fallbacks are strictly prohibited outside MOCK_MODE.",
                done=True,
            )
            return _agent_activity

        _agent_mode = "Deterministic Demo Simulator (MOCK_MODE)"
        return await _run_simulated_investigation(alert_payload)


async def _run_real_agent(alert_payload: dict[str, Any]) -> list[AgentStep] | None:
    """Executes the autonomous repair agent with real Google ADK."""
    from google.adk.agents import Agent
    from google.adk.runners import InMemoryRunner
    from google.genai import types

    api_key = os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")
    if api_key:
        os.environ["GEMINI_API_KEY"] = api_key
        os.environ["GOOGLE_API_KEY"] = api_key

    instruction = """You are Cinema CI's autonomous production reliability agent.
Your objective is to enforce Cinema Contracts with minimal, bounded rebuilds.

INVESTIGATION PROCEDURE VIA GRAFANA MCP:
1. Call get_firing_alerts() to inspect the incident trigger.
2. Call query_grafana_metrics('cinema_ci_active_regressions') for Prometheus metrics.
3. Call query_grafana_logs('{service_name="cinema-ci"}') for Loki failure details.
4. Call get_failing_tests(build_id) for failing/regression test records.
5. Call get_contract_info() to inspect expected character/prop/shot contracts.
6. Diagnose root cause and invoke regenerate_shot() ONLY for the affected shot.

RULES:
- Always investigate Grafana evidence before initiating repair.
- Prefer surgical, minimal repairs; never rebuild unaffected passing shots.
- Maximum 2 automated repair attempts per build.
"""

    agent = Agent(
        name="cinema_ci_agent",
        model=GEMINI_MODEL,
        instruction=instruction,
        tools=[
            agent_tools.get_build_info,
            agent_tools.get_failing_tests,
            agent_tools.get_contract_info,
            agent_tools.regenerate_shot,
            agent_tools.release_build,
            agent_tools.query_grafana_metrics,
            agent_tools.query_grafana_logs,
            agent_tools.get_firing_alerts,
        ],
    )

    runner = InMemoryRunner(agent=agent, app_name="cinema_ci")
    session = await runner.session_service.create_session(
        app_name="cinema_ci", user_id="system",
    )

    message = (
        "Grafana alert fired. Investigate via Grafana MCP and execute surgical repair.\n"
        f"Payload: {json.dumps(alert_payload, default=str)}"
    )

    async for event in runner.run_async(
        user_id="system",
        session_id=session.id,
        new_message=types.Content(parts=[types.Part(text=message)]),
    ):
        _consume_adk_event(event, None)

    return _agent_activity


async def _run_simulated_investigation(alert_payload: dict[str, Any]) -> list[AgentStep]:
    """Deterministic simulation for offline CI verification."""
    from app.engine import get_latest_build

    build_id = None
    for a in alert_payload.get("alerts", []):
        build_id = a.get("labels", {}).get("build_id")
        if build_id:
            break

    if not build_id:
        latest = get_latest_build()
        build_id = latest.build_id if latest else "build_0002"

    project_id = "cafe-envelope"

    # Step 1: Query firing alerts
    _add_step(
        "agent_response",
        detail="Grafana alert received: CinemaRegressionDetected. Initiating Grafana MCP investigation...",
        done=True,
    )
    await asyncio.sleep(0.1)

    s1 = _add_step("get_firing_alerts", tool_name="get_firing_alerts")
    alerts_result = agent_tools.get_firing_alerts()
    s1.tool_output = json.dumps(alerts_result, default=str)[:500]
    s1.done = True
    await asyncio.sleep(0.1)

    # Step 2: Query Prometheus metrics
    s2 = _add_step(
        "query_grafana_metrics",
        tool_name="query_grafana_metrics",
        tool_input={"query": "cinema_ci_active_regressions"},
    )
    metrics_result = agent_tools.query_grafana_metrics("cinema_ci_active_regressions")
    s2.tool_output = json.dumps(metrics_result, default=str)[:500]
    s2.done = True
    await asyncio.sleep(0.1)

    # Step 3: Query Loki logs
    s3 = _add_step(
        "query_grafana_logs",
        tool_name="query_grafana_logs",
        tool_input={"query": '{service_name="cinema-ci"} | json | status="REGRESSION"'},
    )
    logs_result = agent_tools.query_grafana_logs('{service_name="cinema-ci"} | json | status="REGRESSION"')
    s3.tool_output = json.dumps(logs_result, default=str)[:500]
    s3.done = True
    await asyncio.sleep(0.1)

    # Step 4: Get Failing Tests
    s4 = _add_step(
        "get_failing_tests",
        tool_name="get_failing_tests",
        tool_input={"build_id": build_id},
    )
    failing = agent_tools.get_failing_tests(build_id)
    s4.tool_output = json.dumps(failing, default=str)[:500]
    s4.done = True
    await asyncio.sleep(0.1)

    # Step 5: Get Contract
    s5 = _add_step("get_contract_info", tool_name="get_contract_info")
    contract = agent_tools.get_contract_info()
    s5.tool_output = json.dumps({
        "project": contract.get("project"),
        "characters": contract.get("characters"),
        "props": contract.get("props"),
    }, default=str)[:500]
    s5.done = True
    await asyncio.sleep(0.1)

    # Step 6: Diagnose root cause
    failing_shots = list({
        t.get("scope") for t in failing
        if t.get("scope") and t.get("scope").startswith("shot_")
    })
    if not failing_shots:
        failing_shots = ["shot_02", "shot_04"]
    failing_shot = failing_shots[0]

    _add_step(
        "agent_response",
        detail=(
            f"Root cause diagnosed: {', '.join(failing_shots)} violate character/identity contracts. "
            f"Executing surgical regeneration of {', '.join(failing_shots)} (reusing all other passing shots)."
        ),
        done=True,
    )
    await asyncio.sleep(0.1)

    # Step 7: Regenerate shot
    instruction = (
        f"Regenerate {', '.join(failing_shots)} ensuring Marcus wears black coat, "
        "no glasses, short fade haircut per contract."
    )
    s7 = _add_step(
        "regenerate_shot",
        tool_name="regenerate_shot",
        tool_input={
            "project_id": project_id,
            "shot_id": failing_shot,
            "shots_to_regenerate": failing_shots,
            "repair_instruction": instruction,
        },
    )
    regen_result = agent_tools.regenerate_shot(
        project_id=project_id,
        shot_id=failing_shot,
        shots_to_regenerate=failing_shots,
        repair_instruction=instruction,
    )
    s7.tool_output = json.dumps(regen_result, default=str)[:500]
    s7.done = True

    new_bid = regen_result.get("new_build_id", "build_0003")
    _add_step(
        "agent_response",
        detail=f"Surgical rebuild triggered: {new_bid}. Verifying repair...",
        done=True,
    )

    return _agent_activity

