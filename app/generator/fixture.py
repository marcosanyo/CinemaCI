"""Cinema CI — Fixture Video Generator.

Provides reproducible video generation for local testing, CI test runs,
and deterministic regression demonstrations.
"""

from __future__ import annotations

import os
import shutil

from app.generator.base import VideoGenerator
from app.models import CharacterSpec, GenerationResult, PropSpec, ShotSpec


class FixtureGenerator(VideoGenerator):
    """Generates videos by copying pre-existing fixture files."""

    def __init__(self, fixtures_dir: str = "fixtures/blue-envelope") -> None:
        """Initializes FixtureGenerator with a source fixtures directory."""
        self.fixtures_dir = fixtures_dir
        self.use_regression_fixtures = False

    async def generate(
        self,
        shot_spec: ShotSpec,
        characters: dict[str, CharacterSpec],
        props: dict[str, PropSpec],
        output_path: str,
    ) -> GenerationResult:
        """Copies standard or regression fixture video files to target output path.

        Args:
            shot_spec: Shot definition.
            characters: Character definitions map.
            props: Prop definitions map.
            output_path: Destination video file path.

        Returns:
            GenerationResult recording file copy status.
        """
        shot_id = shot_spec.id

        if self.use_regression_fixtures:
            source_filename = f"{shot_id}_fail.mp4"
            if not os.path.exists(os.path.join(self.fixtures_dir, source_filename)):
                source_filename = f"{shot_id}.mp4"
        else:
            source_filename = f"{shot_id}.mp4"

        source_path = os.path.join(self.fixtures_dir, source_filename)
        if not os.path.exists(source_path):
            source_path = os.path.join(self.fixtures_dir, f"{shot_id}.mp4")

        os.makedirs(os.path.dirname(output_path), exist_ok=True)

        if os.path.exists(source_path):
            shutil.copy2(source_path, output_path)
            return GenerationResult(
                shot_id=shot_id,
                video_path=output_path,
                success=True,
                duration_sec=shot_spec.duration_sec,
            )

        with open(output_path, "wb") as handle:
            handle.write(b"")
        return GenerationResult(
            shot_id=shot_id,
            video_path=output_path,
            success=False,
            error=f"Fixture not found: {source_path}",
            duration_sec=0.0,
        )

