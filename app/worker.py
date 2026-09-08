"""Cinema CI — Cloud Run Job Build Worker Entrypoint.

Executed inside Cloud Run Job containers (`cinema-ci-build-worker`) to run
long-running video generation, quality gate tests, and final film packaging
independently of the FastAPI HTTP service.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import sys

from dotenv import load_dotenv

load_dotenv()
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
logger = logging.getLogger("cinema-ci-worker")


async def main_async():
    parser = argparse.ArgumentParser(description="Cinema CI Build Worker")
    parser.add_argument("--build-id", default=os.getenv("BUILD_ID", ""))
    parser.add_argument("--project-id", default=os.getenv("PROJECT_ID", "blue-envelope"))
    parser.add_argument("--baseline-id", default=os.getenv("BASELINE_BUILD_ID", ""))
    parser.add_argument("--contract-path", default=os.getenv("CINEMA_CONTRACT_PATH", "cinema.yaml"))
    parser.add_argument("--generator", default=os.getenv("GENERATOR_TYPE", "veo"))
    args = parser.parse_args()

    build_id = args.build_id
    if not build_id:
        logger.error("BUILD_ID is required to run Cinema CI Build Worker.")
        sys.exit(1)

    logger.info("=" * 60)
    logger.info("CINEMA CI — CLOUD RUN JOB BUILD WORKER")
    logger.info("Target Build ID: %s", build_id)
    logger.info("Project ID: %s", args.project_id)
    logger.info("Baseline ID: %s", args.baseline_id or "none")
    logger.info("=" * 60)

    from app.contract import load_contract
    from app.engine import BuildEngine
    from app.generator.fixture import FixtureGenerator
    from app.generator.veo import VeoGenerator
    from app.store import create_artifact_store, create_metadata_store
    from app.telemetry import setup_telemetry, flush_telemetry

    try:
        setup_telemetry()
        logger.info("Worker OpenTelemetry and Grafana telemetry initialized successfully.")
    except Exception as tel_err:
        logger.warning("Worker telemetry initialization warning: %s", tel_err)

    artifact_store = create_artifact_store()
    metadata_store = create_metadata_store()
    # Prefer the shared contract snapshot published by the service container.
    # The worker runs on a separate filesystem and must NOT use the stale
    # baked-in cinema.yaml after a creative change was applied.
    contract = None
    try:
        from app.contract import load_shared_contract_snapshot
        contract = load_shared_contract_snapshot(artifact_store, args.project_id)
        if contract is not None:
            logger.info("Worker loaded shared contract snapshot for project %s.", args.project_id)
    except Exception as snap_err:
        logger.warning("Worker shared contract snapshot unavailable: %s", snap_err)
    if contract is None:
        contract = load_contract(args.contract_path)

    strict_mode = os.getenv("STRICT_MODE", "false").lower() in ("true", "1")
    if args.generator == "veo" or strict_mode:
        generator = VeoGenerator()
    else:
        generator = FixtureGenerator(fixtures_dir="fixtures/blue-envelope")

    scratch_dir = f"/tmp/cinema-ci/{build_id}"
    os.makedirs(scratch_dir, exist_ok=True)

    engine = BuildEngine(
        contract=contract,
        generator=generator,
        storage_path=scratch_dir,
        artifact_store=artifact_store,
        metadata_store=metadata_store,
    )

    build = metadata_store.get_build(build_id)
    impact_plan = build.impact_plan if build else None

    # Load impact plan from environment variable if available
    if os.getenv("IMPACT_PLAN"):
        try:
            env_plan = json.loads(os.getenv("IMPACT_PLAN"))
            if env_plan:
                impact_plan = env_plan
                logger.info("Worker loaded impact_plan from environment variable.")
        except Exception as e:
            logger.warning("Failed to parse IMPACT_PLAN from environment: %s", e)

    baseline_id = args.baseline_id or os.getenv("BASELINE_BUILD_ID")
    if not baseline_id and impact_plan:
        baseline_id = impact_plan.get("baseline_build_id")

    baseline_build = metadata_store.get_build(baseline_id) if baseline_id else None

    shots_to_regen = None
    if os.getenv("SHOTS_TO_REGENERATE"):
        try:
            shots_to_regen = json.loads(os.getenv("SHOTS_TO_REGENERATE", "[]"))
        except Exception:
            logger.warning("Ignoring invalid SHOTS_TO_REGENERATE JSON")

    if not shots_to_regen and impact_plan:
        rebuild_list = impact_plan.get("rebuild") or impact_plan.get("rebuild_assets")
        if rebuild_list:
            shots_to_regen = rebuild_list

    logger.info(
        "Build execution configuration: build_id=%s, baseline_id=%s, incremental=%s, shots_to_regenerate=%s",
        build_id,
        baseline_build.build_id if baseline_build else "none",
        bool(impact_plan or shots_to_regen),
        shots_to_regen,
    )

    try:
        completed_build = await engine.run_build(
            build_id=build_id,
            baseline_build=baseline_build,
            shots_to_regenerate=shots_to_regen,
            impact_plan=impact_plan,
        )
        logger.info("Build %s completed with status: %s", build_id, completed_build.status.value)
        logger.info(
            "Quality Gate: %s/%s passed",
            completed_build.tests_passed,
            completed_build.tests_total,
        )
        logger.info(
            "Artifact operations: %s rebuilt, %s reused, %s avoided (%s%% artifact operations avoided)",
            completed_build.operations_rebuilt,
            completed_build.operations_reused,
            completed_build.operations_avoided,
            completed_build.savings_percent,
        )
    except Exception as exc:
        logger.error("Build worker failed for build %s: %s", build_id, exc, exc_info=True)
        sys.exit(1)
    finally:
        flush_telemetry()


def main():
    asyncio.run(main_async())


if __name__ == "__main__":
    main()
