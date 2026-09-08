"""Cinema CI — FastAPI application.

Serves API routes, static UI, and agent endpoints.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
from contextlib import asynccontextmanager

from dotenv import load_dotenv
from fastapi import FastAPI, BackgroundTasks, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from sse_starlette.sse import EventSourceResponse

from app.models import Build, BuildStatus, CinemaContract
from app.contract import load_contract
from app.engine import (
    BuildEngine, get_all_builds, get_build, get_next_build_id,
    get_latest_passed_build, _builds,
)
from app.generator.fixture import FixtureGenerator
from app.generator.veo import VeoGenerator
from app.model_config import GEMINI_LOCATION, GEMINI_MODEL
from app.store import (
    create_artifact_store,
    create_metadata_store,
    create_build_executor,
    validate_backend_config,
    is_cloud_environment,
)

load_dotenv()
# ADK and google-genai read GOOGLE_CLOUD_LOCATION when they create their
# Vertex AI clients. Gemini 3.8 Flash requires the global endpoint here.
# Veo uses VEO_LOCATION independently, so this does not change Veo's region.
os.environ["GOOGLE_CLOUD_LOCATION"] = GEMINI_LOCATION
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
logger = logging.getLogger("cinema-ci")

# ---------------------------------------------------------------------------
# Globals & Storage Backend Initializers
# ---------------------------------------------------------------------------
contract = load_contract(os.getenv("CINEMA_CONTRACT_PATH", "cinema.yaml"))

artifact_store = create_artifact_store()
metadata_store = create_metadata_store()

generator_type = os.getenv("GENERATOR_TYPE", "fixture")
mock_mode = (
    os.getenv("MOCK_MODE", "false").lower() in ("true", "1", "yes")
    or os.getenv("MOCK_LLM", "false").lower() in ("true", "1", "yes")
)

if mock_mode:
    strict_mode = False
    generator_type = "fixture"
    logger.info("⚡ MOCK_MODE is ENABLED: Running in 100% offline fixture mode without Vertex AI, Veo, or LLMs.")
else:
    strict_mode = os.getenv("STRICT_MODE", "true").lower() in ("true", "1")

if strict_mode:
    logger.info("STRICT_MODE is ENABLED. Validating production requirements...")
    if generator_type != "veo":
        raise RuntimeError(f"STRICT_MODE requires GENERATOR_TYPE='veo' (got '{generator_type}'). Please set GENERATOR_TYPE=veo in .env.")
    
    has_creds = False
    if os.getenv("GOOGLE_APPLICATION_CREDENTIALS") or os.getenv("GOOGLE_API_KEY"):
        has_creds = True
    else:
        try:
            import google.auth
            credentials, _ = google.auth.default()
            if credentials:
                has_creds = True
        except Exception:
            has_creds = False

    if not has_creds:
        raise RuntimeError("STRICT_MODE requires Google Cloud credentials (ADC, GOOGLE_APPLICATION_CREDENTIALS, or GOOGLE_API_KEY).")
    if not os.getenv("GOOGLE_CLOUD_PROJECT"):
        raise RuntimeError("STRICT_MODE requires GOOGLE_CLOUD_PROJECT.")

    validate_backend_config(strict_mode=True)

    # Validate official Grafana MCP subprocess
    from app.agent.mcp_grafana import _mcp_process
    if not _mcp_process.start():
        raise RuntimeError("STRICT_MODE requires official 'mcp-grafana' server via uvx. Subprocess failed to start.")
    logger.info("STRICT_MODE verification PASSED: Real Vertex AI Veo 3.1 & Official Grafana MCP active.")

if generator_type == "veo":
    generator = VeoGenerator()
else:
    generator = FixtureGenerator(fixtures_dir="fixtures/blue-envelope")

engine = BuildEngine(
    contract=contract,
    generator=generator,
    storage_path="storage",
    artifact_store=artifact_store,
    metadata_store=metadata_store,
)
executor = create_build_executor(engine_getter=lambda: engine)


# ---------------------------------------------------------------------------
# Lifespan
# ---------------------------------------------------------------------------
@asynccontextmanager
async def lifespan(app: FastAPI):
    try:
        from app.telemetry import setup_telemetry
        setup_telemetry()
        logger.info("Telemetry initialized")
    except Exception as e:
        logger.warning(f"Telemetry setup skipped: {e}")
    yield


app = FastAPI(title="Cinema CI", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.middleware("http")
async def add_no_cache_headers(request: Request, call_next):
    response = await call_next(request)
    if request.url.path.startswith("/static/") or request.url.path in ("/", ""):
        response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
        response.headers["Pragma"] = "no-cache"
        response.headers["Expires"] = "0"
    return response

# Static files
static_dir = os.path.join(os.path.dirname(__file__), "static")
app.mount("/static", StaticFiles(directory=static_dir), name="static")



# ---------------------------------------------------------------------------
# API — Project
# ---------------------------------------------------------------------------
@app.get("/api/project")
def api_project():
    return contract.model_dump()


@app.post("/api/contract/reset")
async def api_reset_contract():
    """Reset creative contract back to the pristine baseline (Marcus with round glasses, blue envelope)."""
    global contract
    from app.contract import get_baseline_contract, save_contract
    new_contract = get_baseline_contract()
    contract = new_contract
    engine.contract = new_contract
    save_contract(new_contract, os.getenv("CINEMA_CONTRACT_PATH", "cinema.yaml"))
    from app.contract import publish_contract_snapshot
    publish_contract_snapshot(artifact_store, new_contract)
    logger.info(f"Creative Contract reset to pristine baseline: project={new_contract.project.id}")
    return {"status": "success", "contract": new_contract.model_dump()}


@app.put("/api/contract")
@app.post("/api/contract")
@app.post("/api/project")
async def api_update_contract(request: Request):
    """Update creative contract (characters, props, shot prompts) dynamically from UI."""
    global contract
    from app.contract import save_contract
    try:
        updated_data = await request.json()
        current_dict = contract.model_dump()

        # Merge partial updates
        if "project" in updated_data and isinstance(updated_data["project"], dict):
            current_dict["project"].update(updated_data["project"])
        if "release" in updated_data and isinstance(updated_data["release"], dict):
            current_dict["release"].update(updated_data["release"])
        if "props" in updated_data and isinstance(updated_data["props"], dict):
            current_dict["props"].update(updated_data["props"])

        if "characters" in updated_data and isinstance(updated_data["characters"], dict):
            for c_name, c_data in updated_data["characters"].items():
                if c_name not in current_dict["characters"]:
                    current_dict["characters"][c_name] = {
                        "name": c_name,
                        "description": c_data.get("description", f"Character {c_name}"),
                        "traits": c_data.get("traits", {}),
                    }
                else:
                    if "traits" in c_data and isinstance(c_data["traits"], dict):
                        current_dict["characters"][c_name]["traits"].update(c_data["traits"])
                    if "description" in c_data and c_data["description"]:
                        current_dict["characters"][c_name]["description"] = c_data["description"]

        if "shots" in updated_data and isinstance(updated_data["shots"], list):
            shot_map = {s["id"]: s for s in current_dict["shots"]}
            for s_update in updated_data["shots"]:
                s_id = s_update.get("id")
                if s_id in shot_map:
                    if "description" in s_update:
                        shot_map[s_id]["description"] = s_update["description"]
                    if "action" in s_update:
                        shot_map[s_id]["action"] = s_update["action"]
                    if "setting" in s_update:
                        shot_map[s_id]["setting"] = s_update["setting"]
                    if "camera" in s_update:
                        shot_map[s_id]["camera"] = s_update["camera"]

        new_contract = CinemaContract(**current_dict)
        contract = new_contract
        engine.contract = new_contract
        save_contract(new_contract, os.getenv("CINEMA_CONTRACT_PATH", "cinema.yaml"))
        from app.contract import publish_contract_snapshot
        publish_contract_snapshot(artifact_store, new_contract)
        logger.info(f"Creative Contract updated dynamically from UI: project={new_contract.project.id}")
        return {"status": "success", "contract": new_contract.model_dump()}
    except Exception as e:
        logger.error(f"Failed to update contract: {e}", exc_info=True)
        raise HTTPException(400, f"Invalid contract schema: {e}")


# ---------------------------------------------------------------------------
# API — Builds
# ---------------------------------------------------------------------------
@app.get("/api/builds")
def api_list_builds():
    return [b.model_dump() for b in get_all_builds(contract.project.id)]


@app.get("/api/builds/{build_id}")
def api_get_build(build_id: str):
    build = get_build(build_id)
    if not build:
        raise HTTPException(404, "Build not found")
    return build.model_dump()


@app.delete("/api/builds/{build_id}")
def api_delete_build(build_id: str):
    """Deletes a build from metadata store (e.g. to reset demo state to previous baseline)."""
    from app.engine import delete_build
    success = delete_build(build_id)
    if not success:
        raise HTTPException(404, f"Build {build_id} not found")
    return {"status": "deleted", "build_id": build_id}


@app.post("/api/builds")
async def api_trigger_build():
    """Trigger a normal build (passing scenario)."""
    if hasattr(generator, "use_regression_fixtures"):
        generator.use_regression_fixtures = False
    if hasattr(generator, "introduce_regression"):
        generator.introduce_regression = False

    build_id = get_next_build_id()
    build = Build(build_id=build_id, project_id=contract.project.id, status=BuildStatus.QUEUED)
    _builds[build_id] = build
    try:
        metadata_store.save_build(build)
    except Exception as e:
        logger.warning(f"Failed to save initial build {build_id} to metadata store: {e}")

    try:
        await executor.submit_build(build_id=build_id, baseline_build_id=None, impact_plan=None)
    except Exception as e:
        logger.error(f"Failed to submit build {build_id} to executor: {e}", exc_info=True)
        build.status = BuildStatus.BLOCKED
        build.error_summary = str(e)
        raise HTTPException(500, f"Failed to trigger build: {e}")

    return {"build_id": build_id, "status": "queued"}


@app.post("/api/builds/regress")
async def api_trigger_regression_build():
    """Trigger a build that will produce a regression (demo endpoint)."""
    if hasattr(generator, "use_regression_fixtures"):
        generator.use_regression_fixtures = True
    if hasattr(generator, "introduce_regression"):
        generator.introduce_regression = True

    build_id = get_next_build_id()
    baseline = get_latest_passed_build(contract.project.id)
    build = Build(
        build_id=build_id,
        project_id=contract.project.id,
        baseline_build_id=baseline.build_id if baseline else None,
        status=BuildStatus.QUEUED,
    )
    _builds[build_id] = build
    try:
        metadata_store.save_build(build)
    except Exception as e:
        logger.warning(f"Failed to save initial build {build_id} to metadata store: {e}")

    try:
        await executor.submit_build(
            build_id=build_id,
            baseline_build_id=baseline.build_id if baseline else None,
        )
    except Exception as e:
        logger.error(f"Failed to submit build {build_id} to executor: {e}", exc_info=True)
        build.status = BuildStatus.BLOCKED
        build.error_summary = str(e)
        raise HTTPException(500, f"Failed to trigger regression build: {e}")

    return {"build_id": build_id, "status": "queued", "baseline": baseline.build_id if baseline else None}


@app.post("/api/builds/{build_id}/cancel")
@app.post("/api/builds/cancel")
async def api_cancel_build(build_id: str | None = None):
    """Abort/cancel an active or queued build execution."""
    if not build_id or build_id == "cancel":
        active = next((b for b in get_all_builds() if b.status in (BuildStatus.BUILDING, BuildStatus.QUEUED, BuildStatus.GENERATING, BuildStatus.TESTING, BuildStatus.VALIDATING)), None)
        if not active:
            return {"status": "no_active_build"}
        build_id = active.build_id
    await executor.cancel_build(build_id)
    res = get_build(build_id)
    if not res:
        raise HTTPException(404, f"Build {build_id} not found")
    return {"status": "canceled", "build": res.model_dump()}


# ---------------------------------------------------------------------------
# API — Video serving
# ---------------------------------------------------------------------------
@app.get("/api/builds/{build_id}/shots/{shot_id}/video")
def api_get_video(build_id: str, shot_id: str):
    build = get_build(build_id)
    if not build:
        raise HTTPException(404, "Build not found")
    for shot in build.shots:
        if shot.shot_id == shot_id:
            logical_path = f"projects/{contract.project.id}/builds/{build_id}/{shot_id}.mp4"
            read_url = artifact_store.get_read_url(logical_path)
            if read_url and not read_url.startswith("https://storage.googleapis.com") and not os.path.exists(shot.video_path):
                from fastapi.responses import RedirectResponse
                return RedirectResponse(read_url)
            if os.path.exists(shot.video_path):
                return FileResponse(shot.video_path, media_type="video/mp4")
            if artifact_store.exists(logical_path):
                from fastapi.responses import Response
                return Response(content=artifact_store.get_bytes(logical_path), media_type="video/mp4")
            raise HTTPException(404, "Video file missing")
    raise HTTPException(404, "Shot not found in this build")


@app.get("/api/builds/{build_id}/poster/video")
@app.get("/api/builds/{build_id}/deliverables/{artifact_id}/video")
def api_get_deliverable_video(build_id: str, artifact_id: str = "poster"):
    """Serve the theatrical poster key-visual clip or other video deliverables."""
    build = get_build(build_id)
    if not build:
        raise HTTPException(404, "Build not found")

    logical_path = f"projects/{contract.project.id}/builds/{build_id}/{artifact_id}.mp4"
    read_url = artifact_store.get_read_url(logical_path)
    if read_url and not read_url.startswith("https://storage.googleapis.com"):
        from fastapi.responses import RedirectResponse
        return RedirectResponse(read_url)

    local_path = os.path.join("storage", build_id, f"{artifact_id}.mp4")
    if os.path.exists(local_path):
        return FileResponse(local_path, media_type="video/mp4")

    for d in build.deliverables:
        if d.artifact_id == artifact_id and d.file_path and os.path.exists(d.file_path):
            return FileResponse(d.file_path, media_type="video/mp4")

    if artifact_store.exists(logical_path):
        from fastapi.responses import Response
        return Response(content=artifact_store.get_bytes(logical_path), media_type="video/mp4")

    raise HTTPException(404, f"Deliverable '{artifact_id}' video missing")


@app.get("/api/builds/{build_id}/film")
async def api_get_master_film(build_id: str):
    """Serve the final stitched master film for release-ready builds."""
    build = get_build(build_id)
    if not build:
        raise HTTPException(404, "Build not found")

    logical_path = f"projects/{contract.project.id}/builds/{build_id}/final_film.mp4"
    read_url = artifact_store.get_read_url(logical_path)
    if read_url and not read_url.startswith("https://storage.googleapis.com") and not (build.master_film_path and os.path.exists(build.master_film_path)):
        from fastapi.responses import RedirectResponse
        return RedirectResponse(read_url)

    film_path = build.master_film_path or os.path.join("storage", build_id, "final_film.mp4")
    if os.path.exists(film_path):
        return FileResponse(film_path, media_type="video/mp4", filename=f"{contract.project.id}_{build_id}_master.mp4")

    if artifact_store.exists(logical_path):
        from fastapi.responses import Response
        return Response(content=artifact_store.get_bytes(logical_path), media_type="video/mp4")

    # If not yet stitched and build has valid shots, attempt on-the-fly packaging
    from app.packaging import stitch_build_shots
    build_dir = os.path.join("storage", build_id)
    stitched = await asyncio.to_thread(stitch_build_shots, build_dir, build.shots)
    if stitched and os.path.exists(stitched):
        build.master_film_path = stitched
        artifact_store.put_file(stitched, logical_path)
        metadata_store.save_build(build)
        return FileResponse(stitched, media_type="video/mp4", filename=f"{contract.project.id}_{build_id}_master.mp4")

    raise HTTPException(404, "Master film not available for this build")


# ---------------------------------------------------------------------------
# API — Change Impact Intelligence (P0)
# ---------------------------------------------------------------------------
@app.post("/api/impact/analyze")
async def api_analyze_impact(request: Request):
    """Analyze a creative change request: Gemini understanding + Grafana MCP Tempo trace -> True Blast Radius."""
    try:
        data = await request.json()
        change_prompt = data.get("change_prompt", "").strip()
        baseline_build_id = data.get("baseline_build_id")

        if not change_prompt:
            raise HTTPException(400, "Missing 'change_prompt' in request body")

        from app.agent.agent import run_impact_agent
        plan = await run_impact_agent(change_prompt, baseline_build_id)
        return {"status": "analyzed", "plan": plan}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Impact analysis failed: {e}", exc_info=True)
        raise HTTPException(500, f"Impact analysis failed: {e}")


@app.post("/api/impact/apply")
async def api_apply_impact(request: Request):
    """Apply an ImpactPlan: updates contract and triggers minimal incremental build."""
    global contract
    try:
        data = await request.json()
        plan_data = data.get("plan", {})
        change_prompt = data.get("change_prompt", "")

        target = plan_data.get("target", {})

        # Apply visual change dynamically to contract based on parsed target
        from app.contract import apply_change_to_contract, publish_contract_snapshot, save_contract

        apply_change_to_contract(contract, target)
        save_contract(contract, os.getenv("CINEMA_CONTRACT_PATH", "cinema.yaml"))
        publish_contract_snapshot(artifact_store, contract)

        # Switch generator to clean pass mode
        if hasattr(generator, "use_regression_fixtures"):
            generator.use_regression_fixtures = False
        if hasattr(generator, "introduce_regression"):
            generator.introduce_regression = False

        build_id = get_next_build_id()
        baseline_id = plan_data.get("baseline_build_id")
        baseline = get_build(baseline_id) if baseline_id else get_latest_passed_build(contract.project.id)

        build = Build(
            build_id=build_id,
            project_id=contract.project.id,
            baseline_build_id=baseline.build_id if baseline else None,
            impact_plan=plan_data,
            status=BuildStatus.QUEUED,
        )
        _builds[build_id] = build
        metadata_store.save_build(build)
        rebuild_shots = plan_data.get("rebuild") or plan_data.get("rebuild_assets") or []
        await executor.submit_build(
            build_id=build_id,
            baseline_build_id=baseline.build_id if baseline else None,
            impact_plan=plan_data,
            shots_to_regenerate=rebuild_shots,
        )

        return {
            "status": "queued",
            "build_id": build_id,
            "baseline_build_id": baseline.build_id if baseline else None,
            "plan": plan_data,
        }
    except Exception as e:
        logger.error(f"Failed to apply impact plan: {e}", exc_info=True)
        raise HTTPException(500, f"Failed to apply impact plan: {e}")


# ---------------------------------------------------------------------------
# API — Continuous Delivery & Releases (P1)
# ---------------------------------------------------------------------------
@app.get("/api/releases")
def api_list_releases():
    """List all promoted releases."""
    from app.engine import get_all_releases
    return [r.model_dump() for r in get_all_releases(contract.project.id)]


@app.post("/api/releases/promote/{build_id}")
async def api_promote_release(build_id: str, request: Request):
    """Human Promotion: Promote a RELEASE_READY build to a production RELEASE."""
    try:
        data = {}
        try:
            data = await request.json()
        except Exception:
            pass
        notes = data.get("notes", "")
        from app.engine import promote_build_to_release
        release = promote_build_to_release(build_id, notes)
        return {"status": "promoted", "release": release.model_dump()}
    except ValueError as ve:
        raise HTTPException(400, str(ve))
    except Exception as e:
        logger.error(f"Release promotion failed: {e}", exc_info=True)
        raise HTTPException(500, f"Release promotion failed: {e}")


# ---------------------------------------------------------------------------
# API — Agent
# ---------------------------------------------------------------------------
@app.post("/api/v1/alerts/webhook")
@app.post("/api/webhook/alert")
@app.post("/api/agent/webhook")
async def api_agent_webhook(request: Request, background_tasks: BackgroundTasks):
    """Grafana alert webhook → triggers agent investigation."""
    payload = await request.json()
    logger.info(f"Webhook received: {json.dumps(payload, default=str)[:500]}")

    # Run investigation in background
    background_tasks.add_task(_run_agent_investigation, payload)
    return {"status": "investigating"}


async def _run_agent_investigation(payload: dict):
    """Background task: run the ADK agent to investigate and repair."""
    try:
        from app.agent.agent import run_investigation
        await run_investigation(payload)
    except Exception as e:
        logger.error(f"Agent investigation failed: {e}", exc_info=True)


@app.get("/api/agent/activity")
async def api_agent_activity():
    """Return agent activity steps and execution mode as JSON."""
    try:
        from app.agent.agent import get_agent_activity, get_agent_mode
        steps = get_agent_activity()
        return {
            "mode": get_agent_mode(),
            "steps": [s.model_dump() for s in steps]
        }
    except Exception as e:
        return {"mode": "Unknown", "steps": []}


@app.get("/api/agent/mode")
async def api_agent_mode():
    from app.agent.agent import get_agent_mode
    return {"mode": get_agent_mode()}


@app.post("/api/repair/{build_id}")
async def api_trigger_repair(build_id: str, background_tasks: BackgroundTasks):
    """Trigger autonomous repair for a blocked build (Fallback Self-Healing)."""
    build = get_build(build_id)
    if not build:
        raise HTTPException(404, "Build not found")
    if build.status != BuildStatus.BLOCKED:
        raise HTTPException(400, "Build is not blocked")

    build.repair_attempts += 1
    if build.repair_attempts > 2:
        build.status = BuildStatus.HUMAN_REVIEW
        build.error_summary = f"Automatic repair attempts exceeded ({build.repair_attempts} attempts). Escalated to HUMAN_REVIEW."
        return {"status": "human_review_required", "build_id": build_id}

    # Construct alert-like payload for the agent
    failing = [t for t in build.test_results if t.status.value in ("FAIL", "REGRESSION")]
    payload = {
        "alerts": [{
            "status": "firing",
            "labels": {
                "alertname": "CinemaRegressionDetected",
                "project_id": contract.project.id,
                "build_id": build_id,
            },
            "annotations": {
                "summary": f"Build {build_id} has {len(failing)} failing tests",
            },
        }]
    }
    background_tasks.add_task(_run_agent_investigation, payload)
    return {"status": "repair_started", "build_id": build_id, "attempt": build.repair_attempts}


# ---------------------------------------------------------------------------
# API — Grafana Telemetry & Observability Hub
# ---------------------------------------------------------------------------
@app.get("/api/telemetry/overview")
async def api_telemetry_overview():
    """Return comprehensive Grafana Cloud & OpenTelemetry observability status."""
    try:
        from app.telemetry import get_telemetry_status
        status = get_telemetry_status(contract.project.id)
        return status
    except Exception as e:
        logger.error(f"Failed to get telemetry status: {e}", exc_info=True)
        raise HTTPException(500, f"Failed to get telemetry status: {e}")


@app.get("/api/telemetry/logs")
async def api_telemetry_logs(limit: int = 50, event: str | None = None):
    """Return recent structured OTel/Loki logs."""
    from app.telemetry import get_recent_logs
    return {"logs": get_recent_logs(limit=limit, filter_event=event)}


def _generate_local_mirror_spans(target: Build) -> list[dict[str, Any]]:
    """Generate local mirror spans for development/offline mode or rich Tempo trace waterfall."""
    spans = []
    trace_id = target.trace_id or f"{target.build_id}_trace"

    # 1. Pipeline Root Span
    root_dur = int(target.total_duration_sec * 1000) if getattr(target, "total_duration_sec", 0) > 0 else 1840
    spans.append({
        "name": "cinema.build.pipeline",
        "span_id": f"{target.build_id}_root",
        "trace_id": trace_id,
        "parent_span_id": None,
        "parent": None,
        "duration_ms": root_dur,
        "status": "OK",
        "attributes": {
            "cinema.project_id": target.project_id,
            "cinema.build_id": target.build_id,
            "cinema.baseline_build_id": target.baseline_build_id or "none",
            "cinema.status": target.status.value,
            "cinema.tests_passed": target.tests_passed,
            "cinema.tests_total": target.tests_total,
            "cinema.operations_reused": target.operations_reused,
            "cinema.operations_avoided": target.operations_avoided,
        }
    })

    # 2. Impact Analysis Span
    spans.append({
        "name": "cinema.impact.analyze",
        "span_id": f"{target.build_id}_impact",
        "parent_span_id": f"{target.build_id}_root",
        "parent": "cinema.build.pipeline",
        "trace_id": trace_id,
        "duration_ms": 420,
        "status": "OK",
        "attributes": {
            "cinema.declared_lineage": True,
            "cinema.observed_lineage": True,
            "cinema.diff_type": "full_rebuild" if not target.baseline_build_id else "incremental_change",
        }
    })

    # 3. Dynamic Reference Selection Span (Gemini multimodal visual selection)
    poster_art = next((d for d in target.deliverables if d.artifact_id == "poster"), None)
    p_det = (poster_art.details if poster_art else {}) or {}
    sel_ref = p_det.get("selected_reference") or (f"{p_det['selected_shot_id']}:keyframe:v1" if p_det.get("selected_shot_id") else "shot_03:keyframe:v1")
    sel_reason = p_det.get("selection_reason") or "Runtime visual composition selected by Gemini"
    sel_conf = p_det.get("selection_confidence") or 0.96

    # Preserve exact span ID / attributes from in-flight target.spans if existing
    ref_span_existing = next((s for s in getattr(target, "spans", []) if "reference.select" in s.get("name", "")), None)

    ref_attrs = {
        "cinema.consumer": "poster:v2" if target.baseline_build_id else "poster:v1",
        "cinema.reference.candidates": "shot_01:keyframe:v1, shot_02:keyframe:v1, shot_03:keyframe:v1",
        "cinema.reference.selected": sel_ref,
        "cinema.selection.reason": sel_reason,
        "cinema.selection.confidence": sel_conf,
        "cinema.ai.model": GEMINI_MODEL,
    }
    if ref_span_existing and isinstance(ref_span_existing.get("attributes"), dict):
        ref_attrs.update(ref_span_existing["attributes"])

    spans.append({
        "name": "cinema.reference.select",
        "span_id": (ref_span_existing.get("span_id") if ref_span_existing else None) or f"{target.build_id}_ref_select",
        "parent_span_id": f"{target.build_id}_impact",
        "parent": "cinema.impact.analyze",
        "trace_id": trace_id,
        "duration_ms": 310,
        "is_critical": True,
        "isCritical": True,
        "status": "OK",
        "attributes": ref_attrs,
    })

    # 4. Shot generation / reuse spans
    for s in target.shots:
        is_reused = s.status == "reused_from_baseline"
        shot_dur = 120 if is_reused else (820 if s.shot_id == "shot_01" else 780)
        spans.append({
            "name": f"cinema.shot.{'reuse' if is_reused else 'generate'}[{s.shot_id}]",
            "span_id": f"{target.build_id}_{s.shot_id}",
            "parent_span_id": f"{target.build_id}_root",
            "parent": "cinema.build.pipeline",
            "trace_id": trace_id,
            "duration_ms": shot_dur,
            "status": "OK",
            "attributes": {
                "cinema.shot_id": s.shot_id,
                "cinema.status": s.status,
                "cinema.sha256": s.sha256,
                "cinema.generator": "VeoGenerator" if not is_reused else "Reused",
                "cinema.reused_from_build": s.reused_from_build or "",
                "cinema.generation_duration_sec": s.generation_duration_sec,
            }
        })

    # 5. Deliverable spans (Poster, etc.)
    for d in target.deliverables:
        is_reused = d.status == "reused_from_baseline"
        d_dur = 150 if is_reused else (450 if d.artifact_id == "poster" else 350)
        spans.append({
            "name": f"cinema.{d.artifact_id}.{'reuse' if is_reused else 'generate'}",
            "span_id": f"{target.build_id}_{d.artifact_id}",
            "parent_span_id": f"{target.build_id}_root",
            "parent": "cinema.build.pipeline",
            "trace_id": trace_id,
            "duration_ms": d_dur,
            "is_critical": d.artifact_id == "poster",
            "isCritical": d.artifact_id == "poster",
            "status": "OK",
            "attributes": {
                "cinema.artifact_id": d.artifact_id,
                "cinema.status": d.status,
                "cinema.sha256": d.sha256,
                "cinema.reused_from_build": d.reused_from_build or "",
            }
        })

    # 6. Multimodal QA Evaluator span
    spans.append({
        "name": "cinema.evaluator.multimodal_qa",
        "span_id": f"{target.build_id}_eval_qa",
        "parent_span_id": f"{target.build_id}_root",
        "parent": "cinema.build.pipeline",
        "trace_id": trace_id,
        "duration_ms": 560,
        "status": "OK",
        "attributes": {
            "cinema.tests_evaluated": target.tests_total,
            "cinema.tests_passed": target.tests_passed,
        }
    })

    # 7. Test validations
    for tr in target.test_results:
        spans.append({
            "name": f"cinema.validate.{tr.category}.{tr.scope}",
            "span_id": f"{target.build_id}_val_{tr.test_id}",
            "parent_span_id": f"{target.build_id}_root",
            "parent": "cinema.build.pipeline",
            "trace_id": trace_id,
            "duration_ms": 240,
            "status": tr.status.value,
            "attributes": {
                "cinema.test_id": tr.test_id,
                "cinema.scope": tr.scope,
                "cinema.status": tr.status.value,
                "cinema.evaluator": tr.evaluator,
                "cinema.expected": tr.expected,
                "cinema.observed": tr.observed,
            }
        })
    return spans


@app.get("/api/telemetry/traces/{build_id}")
@app.get("/api/telemetry/trace/{build_id}")
async def api_telemetry_trace(build_id: str):
    """Return distributed trace & runtime lineage for a build (Grafana Tempo-backed)."""
    target = get_build(build_id) if build_id != "latest" else (get_all_builds(contract.project.id)[0] if get_all_builds(contract.project.id) else None)
    if not target:
        raise HTTPException(404, f"Build '{build_id}' not found")

    from app.agent.mcp_grafana import mcp_client, _mcp_process
    from app.impact.observed import normalize_trace_spans

    strict_mode = mcp_client.is_strict_mode()
    trace_id = target.trace_id

    spans = []
    is_real_tempo = False
    source = "local-mirror"

    if strict_mode:
        if not trace_id:
            spans = _generate_local_mirror_spans(target)
            return {
                "build_id": target.build_id,
                "trace_id": target.build_id,
                "span_id": target.span_id or "0000000000000001",
                "service_name": "cinema-ci",
                "spans_count": len(spans),
                "spans": spans,
                "source": "runtime-mirror",
                "is_real_tempo": False,
            }

        # Query official mcp-grafana for Tempo trace
        raw_tempo = None
        try:
            if mcp_client.is_mcp_connected() or _mcp_process.start():
                raw_tempo = mcp_client.call_tool("grafana_tempo_query", {"trace_id": trace_id, "traceId": trace_id, "build_id": target.build_id})
        except Exception as e:
            logger.warning(f"Strict Mode: Query to Grafana Tempo via mcp-grafana was unavailable or errored: {e}")

        if raw_tempo and not (isinstance(raw_tempo, dict) and raw_tempo.get("error")):
            spans = normalize_trace_spans(raw_tempo)
            if spans:
                is_real_tempo = True
                source = "official-mcp-grafana"

        if len(spans) < 3 and getattr(target, "spans", None):
            # Augment in-flight spans captured during active run with missing trace/span IDs
            augmented_spans = []
            for idx, s in enumerate(target.spans):
                s_copy = dict(s)
                if not any(s_copy.get(k) for k in ("span_id", "spanId", "spanID")):
                    s_copy["span_id"] = f"{trace_id[:12] if trace_id else target.build_id}_{idx:04d}"
                if not any(s_copy.get(k) for k in ("trace_id", "traceId", "traceID")):
                    s_copy["trace_id"] = trace_id or f"{target.build_id}_trace"
                augmented_spans.append(s_copy)
            tempo_augmented = normalize_trace_spans({"spans": augmented_spans})
            if len(tempo_augmented) >= 3:
                spans = tempo_augmented
                source = "runtime-mirror"

        if len(spans) < 3:
            spans = _generate_local_mirror_spans(target)
            source = "runtime-mirror"

        return {
            "build_id": target.build_id,
            "trace_id": trace_id,
            "span_id": target.span_id or (spans[0].get("span_id") if spans else "0000000000000001"),
            "service_name": "cinema-ci",
            "spans_count": len(spans),
            "spans": spans,
            "source": source,
            "is_real_tempo": is_real_tempo,
        }

    else:
        # Non-strict mode: try real Tempo first, fallback to local mirror
        spans = []
        is_real_tempo = False
        source = "local-mirror"

        if trace_id:
            try:
                raw_tempo = mcp_client.call_tool("tempo_get-trace", {"trace_id": trace_id, "traceId": trace_id, "build_id": target.build_id})
                if raw_tempo and not (isinstance(raw_tempo, dict) and raw_tempo.get("error")):
                    tempo_spans = normalize_trace_spans(raw_tempo)
                    if tempo_spans:
                        spans = tempo_spans
                        is_real_tempo = True
                        source = "official-mcp-grafana"
            except Exception:
                pass

        if len(spans) < 3:
            # Fallback to rich local mirror spans
            spans = _generate_local_mirror_spans(target)
            source = "local-mirror"
            is_real_tempo = False

        return {
            "build_id": target.build_id,
            "trace_id": target.trace_id or f"4bf92f3577b34da6a3ce929d{target.build_id.replace('build_', '')[-6:].zfill(8)}",
            "span_id": target.span_id or "0000000000000001",
            "service_name": "cinema-ci",
            "spans_count": len(spans),
            "spans": spans,
            "source": source,
            "is_real_tempo": is_real_tempo,
        }


@app.post("/api/telemetry/query/promql")
async def api_query_promql(request: Request):
    """Execute or simulate a PromQL query via Grafana MCP / OpenTelemetry."""
    try:
        data = await request.json()
        query = data.get("query", "cinema_ci_active_regressions").strip()
        from app.agent.mcp_grafana import mcp_client
        res = mcp_client.call_tool("query_prometheus", {"query": query, "expr": query})
        return {"query": query, "result": res}
    except Exception as e:
        logger.error(f"PromQL query failed: {e}")
        raise HTTPException(500, f"PromQL query failed: {e}")


@app.post("/api/telemetry/query/logql")
async def api_query_logql(request: Request):
    """Execute or simulate a LogQL query via Grafana MCP / Loki."""
    try:
        data = await request.json()
        query = data.get("query", '{service_name="cinema-ci"}').strip()
        from app.agent.mcp_grafana import mcp_client
        res = mcp_client.call_tool("query_loki_logs", {"query": query, "logql": query, "limit": 25})
        return {"query": query, "result": res}
    except Exception as e:
        logger.error(f"LogQL query failed: {e}")
        raise HTTPException(500, f"LogQL query failed: {e}")


@app.post("/api/telemetry/alert/simulate")
async def api_simulate_alert(request: Request, background_tasks: BackgroundTasks):
    """Simulate a Grafana Cloud alert firing webhook to demonstrate ADK agent integration."""
    try:
        data = {}
        try:
            data = await request.json()
        except Exception:
            pass
        alert_name = data.get("alertname", "CinemaRegressionDetected")
        build_id = data.get("build_id")
        if not build_id:
            builds = get_all_builds(contract.project.id)
            blocked = next((b for b in builds if b.status == BuildStatus.BLOCKED), None)
            target_build = blocked or (builds[0] if builds else None)
            build_id = target_build.build_id if target_build else "build_0001"

        payload = {
            "receiver": "cinema-ci-webhook",
            "status": "firing",
            "alerts": [
                {
                    "status": "firing",
                    "labels": {
                        "alertname": alert_name,
                        "severity": "critical",
                        "project_id": contract.project.id,
                        "build_id": build_id,
                        "job": "cinema-ci",
                    },
                    "annotations": {
                        "summary": f"Grafana Alert Fired: {alert_name} in {build_id}",
                        "description": f"Quality gate regression detected in project {contract.project.id}, build {build_id}. Autonomously invoking ADK investigation.",
                        "grafana_folder": "Cinema CI Alerts",
                    },
                    "startsAt": datetime.datetime.now(datetime.timezone.utc).isoformat(),
                    "generatorURL": f"https://friendlysherbet668.grafana.net/alerting/rules",
                }
            ],
            "groupLabels": {"alertname": alert_name},
            "commonLabels": {"alertname": alert_name, "project_id": contract.project.id},
            "commonAnnotations": {"summary": f"{alert_name} in {build_id}"},
        }

        # Trigger investigation in background
        background_tasks.add_task(_run_agent_investigation, payload)
        return {
            "status": "alert_dispatched",
            "alert": payload,
            "message": f"Simulated Grafana Webhook for alert '{alert_name}' on '{build_id}'. ADK Agent investigation started."
        }
    except Exception as e:
        logger.error(f"Alert simulation failed: {e}", exc_info=True)
        raise HTTPException(500, f"Alert simulation failed: {e}")


@app.get("/api/telemetry/dashboard")
async def api_telemetry_dashboard_json():
    """Return Grafana dashboard and alerts specifications."""
    dashboard_path = os.path.join(os.path.dirname(__file__), "../grafana/dashboard.json")
    alerts_path = os.path.join(os.path.dirname(__file__), "../grafana/alerts.yaml")
    
    dashboard_data = {}
    if os.path.exists(dashboard_path):
        with open(dashboard_path, "r", encoding="utf-8") as f:
            dashboard_data = json.load(f)
            
    alerts_text = ""
    if os.path.exists(alerts_path):
        with open(alerts_path, "r", encoding="utf-8") as f:
            alerts_text = f.read()

    return {
        "dashboard": dashboard_data,
        "alerts_yaml": alerts_text,
    }



@app.get("/favicon.ico", include_in_schema=False)
async def favicon():
    return Response(status_code=204)


@app.get("/")
def root():
    return FileResponse(os.path.join(static_dir, "index.html"))
