"""Cinema CI — Video Generator Base Interface.

Defines the abstract interface implemented by Veo 3.1 generator and test fixtures.
"""

from __future__ import annotations

import abc

from app.models import CharacterSpec, GenerationResult, PropSpec, ShotSpec


class VideoGenerator(abc.ABC):
    """Abstract base class for cinematic video generators."""

    @abc.abstractmethod
    async def generate(
        self,
        shot_spec: ShotSpec,
        characters: dict[str, CharacterSpec],
        props: dict[str, PropSpec],
        output_path: str,
    ) -> GenerationResult:
        """Generates a video based on the shot specification.

        Args:
            shot_spec: Shot requirements from the Creative Contract.
            characters: Character specifications.
            props: Prop specifications.
            output_path: Target path to store the generated video.

        Returns:
            GenerationResult detailing generated artifact paths and metadata.
        """
        ...

