"""Cinema CI — Local In-Process Build Executor.

Executes build pipelines asynchronously in the local process via asyncio tasks.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Callable

from app.store.executor_base import BuildExecutor

logger = logging.getLogger(__name__)


class LocalBuildExecutor(BuildExecutor):
    """Executes builds in-process using asyncio tasks."""

    def __init__(self, engine_getter: Callable[[], Any]) -> None:
        self._engine_getter = engine_getter
        self._active_tasks: dict[str, asyncio.Task] = {}

    async def submit_build(
        self,
        build_id: str,
        baseline_build_id: str | None = None,
        impact_plan: dict[str, Any] | None = None,
        shots_to_regenerate: list[str] | None = None,
    ) -> str:
        engine = self._engine_getter()
        from app.engine import get_build, get_latest_passed_build

        baseline = get_build(baseline_build_id) if baseline_build_id else None
        if not baseline and (impact_plan or shots_to_regenerate):
            baseline = get_latest_passed_build(engine.contract.project.id)

        async def _run_wrapper():
            try:
                await engine.run_build(
                    build_id=build_id,
                    baseline_build=baseline,
                    shots_to_regenerate=shots_to_regenerate,
                    impact_plan=impact_plan,
                )
            except Exception as e:
                logger.error(f"Local build {build_id} task failed: {e}", exc_info=True)
            finally:
                self._active_tasks.pop(build_id, None)

        task = asyncio.create_task(_run_wrapper())
        self._active_tasks[build_id] = task
        logger.info(f"LocalBuildExecutor spawned task for build: {build_id}")
        return build_id

    async def cancel_build(self, build_id: str) -> bool:
        from app.engine import cancel_build as engine_cancel
        engine_cancel(build_id)
        task = self._active_tasks.pop(build_id, None)
        if task and not task.done():
            task.cancel()
            logger.info(f"Canceled asyncio task for build {build_id}")
            return True
        return False
