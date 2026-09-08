"""Cinema CI — Gemini Dynamic Visual Composition & Poster Reference Selection.

Implements real Gemini 3.8 Flash runtime selection of theatrical poster hero keyframes.
The static manifest (cinema.yaml) does NOT declare any link between Poster and specific shots.
The dependency is established dynamically at build runtime by Gemini evaluating actual
generated keyframes extracted via FFmpeg.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import subprocess
import tempfile
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from app.model_config import GEMINI_MODEL

from dotenv import load_dotenv

load_dotenv()
logger = logging.getLogger(__name__)


class PosterSelectionResult(BaseModel):
    """Structured decision output from Gemini visual poster evaluation."""
    model_config = ConfigDict(extra="ignore")

    selected_reference: str = Field(description="Selected reference URI, e.g. 'shot_01:keyframe:v1'")
    selected_shot_id: str = Field(description="Selected shot ID, e.g. 'shot_01'")
    reason: str = Field(description="Artistic reasoning for choosing this specific shot as the hero visual")
    confidence: float = Field(default=0.92, description="Confidence score of the visual selection")
    candidates: list[str] = Field(default_factory=list, description="Candidate references evaluated")
    visual_candidates_evaluated: int = Field(default=0, description="Number of actual generated keyframe images sent to Gemini")


def _extract_keyframe(video_path: str, output_path: str) -> bool:
    """Extracts one actual frame from a generated shot for multimodal poster selection.

    Tries PyAV first for fast in-process decoding.
    Falls back to FFmpeg subprocess via system PATH or imageio_ffmpeg.

    Args:
        video_path: Path to source MP4 video file.
        output_path: Path to write extracted JPEG keyframe.

    Returns:
        True if extraction succeeded and generated a non-empty image file.
    """
    if not video_path or not os.path.exists(video_path):
        return False

    # 1. Primary: PyAV in-process frame decoding
    try:
        import av
        with av.open(video_path) as container:
            if container.streams.video:
                stream = container.streams.video[0]
                time_base = stream.time_base
                target_pts = int(0.5 / float(time_base)) if time_base else 0
                try:
                    container.seek(target_pts, any_frame=False, backward=True, stream=stream)
                except Exception:
                    pass
                for frame in container.decode(stream):
                    img = frame.to_image()
                    img.save(output_path, "JPEG")
                    if os.path.exists(output_path) and os.path.getsize(output_path) > 0:
                        return True
                    break
    except Exception as av_err:
        logger.debug("PyAV keyframe extraction skipped/failed for %s: %s", video_path, av_err)

    # 2. Secondary: FFmpeg CLI (PATH or imageio_ffmpeg)
    from app.ffmpeg_util import find_ffmpeg
    ffmpeg_bin = find_ffmpeg()
    try:
        subprocess.run(
            [
                ffmpeg_bin, "-y", "-loglevel", "error",
                "-ss", "0.5", "-i", video_path,
                "-frames:v", "1", "-q:v", "2", output_path,
            ],
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            timeout=30,
        )
        return os.path.exists(output_path) and os.path.getsize(output_path) > 0
    except Exception as exc:
        logger.warning("Failed to extract poster-selection keyframe from %s: %s", video_path, exc)
        return False


def _get_genai_client() -> Any:
    """Initializes and returns Google GenAI client based on runtime configuration."""
    from google import genai

    api_key = os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")
    use_vertex = os.getenv("GOOGLE_GENAI_USE_VERTEXAI", "").lower() in ("true", "1")
    project = os.getenv("GOOGLE_CLOUD_PROJECT")

    if use_vertex and project:
        return genai.Client(
            vertexai=True,
            project=project,
            location=os.getenv("GOOGLE_CLOUD_LOCATION", "global"),
        )
    elif api_key:
        return genai.Client(api_key=api_key)
    return genai.Client()


async def select_poster_hero_reference(
    shots: list[Any],
    project_name: str = "The Blue Envelope",
    characters: dict[str, Any] | None = None,
) -> PosterSelectionResult:
    """Invokes Gemini to select a hero reference from actual generated shot keyframes.

    ShotArtifact objects contain `video_path`. In strict mode at least one real extracted
    keyframe must be sent to Gemini; otherwise the build fails rather than pretending
    a visual decision occurred.

    Args:
        shots: List of shot artifacts or shot specs.
        project_name: The title of the production.
        characters: Optional character traits dictionary for aesthetic context.

    Returns:
        PosterSelectionResult detailing the selected shot and artistic reasoning.

    Raises:
        RuntimeError: If strict mode is enabled and keyframe extraction or Gemini fails.
    """
    candidate_refs: list[str] = []
    shot_descriptions: list[dict[str, Any]] = []
    visual_candidates: list[tuple[str, str, bytes]] = []

    with tempfile.TemporaryDirectory(prefix="cinema-poster-select-") as temp_dir:
        for index, s in enumerate(shots):
            s_id = getattr(s, "id", None) or getattr(s, "shot_id", str(s))
            s_desc = getattr(s, "description", "")
            s_chars = getattr(s, "characters", [])
            s_prompt = getattr(s, "prompt", "") or getattr(s, "prompt_used", "")
            video_path = getattr(s, "video_path", "")
            ref_uri = f"{s_id}:keyframe:v1"
            candidate_refs.append(ref_uri)
            shot_descriptions.append({
                "shot_id": s_id,
                "reference_uri": ref_uri,
                "description": s_desc or s_prompt[:240],
                "characters": s_chars,
            })

            keyframe_path = os.path.join(temp_dir, f"{index:02d}_{s_id}.jpg")
            if _extract_keyframe(video_path, keyframe_path):
                with open(keyframe_path, "rb") as handle:
                    visual_candidates.append((s_id, ref_uri, handle.read()))

        mock_mode = (
            os.environ.get("MOCK_MODE", "false").lower() in ("true", "1", "yes")
            or os.environ.get("MOCK_LLM", "false").lower() in ("true", "1", "yes")
        )
        if mock_mode:
            logger.info("MOCK_MODE active: Using deterministic poster reference selection (shot_01:keyframe:v1).")
            return PosterSelectionResult(
                selected_reference="shot_01:keyframe:v1",
                selected_shot_id="shot_01",
                reason="MOCK_MODE deterministic selection: Shot 01 protagonist keyframe selected for theatrical poster composition.",
                confidence=0.96,
                candidates=candidate_refs,
                visual_candidates_evaluated=len(visual_candidates),
            )

        strict_mode = (
            os.environ.get("STRICT_MODE", "true").lower() in ("true", "1")
            or os.environ.get("CINEMA_STRICT_MODE", "0").lower() in ("true", "1")
        )
        if strict_mode and not visual_candidates:
            raise RuntimeError(
                "Strict Mode Violation: Poster selection requires actual generated keyframe images, "
                "but no readable shot video/keyframe was available."
            )

        logger.info(
            "Invoking Gemini (%s) for poster selection across %d candidates (%d real keyframes)",
            GEMINI_MODEL,
            len(candidate_refs),
            len(visual_candidates),
        )

        prompt = f"""You are the Art Director and Key Visual Composition Engine for Cinema CI.
We are producing the official theatrical release poster for the film: '{project_name}'.

The attached images are REAL keyframes extracted from shots generated earlier in this build.
Evaluate the visual composition and dynamically choose ONE hero shot that should become the
primary visual source for the theatrical poster.

Candidate metadata:
{json.dumps(shot_descriptions, indent=2)}

Criteria:
1. Dramatic narrative focal point and iconic character framing.
2. Composition suitable for a theatrical key visual.
3. Emotional resonance and clear story identity.

Return strict JSON:
{{
  "selected_shot_id": "shot_01",
  "selected_reference": "shot_01:keyframe:v1",
  "reason": "Visual reason grounded in the attached keyframe.",
  "confidence": <your own calibrated estimate between 0 and 1>
}}

4. Report your own calibrated confidence between 0 and 1. Do NOT reuse any example value.
"""

        try:
            from google.genai import types

            client = _get_genai_client()
            parts = [types.Part.from_text(text=prompt)]
            for shot_id, ref_uri, image_bytes in visual_candidates:
                parts.append(types.Part.from_text(text=f"Candidate {shot_id} ({ref_uri}):"))
                parts.append(types.Part.from_bytes(data=image_bytes, mime_type="image/jpeg"))
            contents = [types.Content(role="user", parts=parts)]

            def call_gemini():
                return client.models.generate_content(
                    model=GEMINI_MODEL,
                    contents=contents,
                    config=types.GenerateContentConfig(
                        system_instruction=(
                            "You are Cinema CI's Art Director. Judge the attached generated keyframes, "
                            "select one source image for the poster, and output strictly valid JSON."
                        ),
                        response_mime_type="application/json",
                        temperature=0.1,
                    ),
                )

            response = await asyncio.wait_for(asyncio.to_thread(call_gemini), timeout=90.0)
            raw_text = (response.text or "").strip()
            data = json.loads(raw_text)

            sel_shot = data.get("selected_shot_id")
            visual_ids = {shot_id for shot_id, _, _ in visual_candidates}
            if not sel_shot or (visual_ids and sel_shot not in visual_ids):
                raise ValueError(f"Gemini selected unknown or non-visual candidate: {sel_shot}")

            sel_ref = data.get("selected_reference") or f"{sel_shot}:keyframe:v1"
            reason = data.get("reason", f"Gemini visually selected {sel_shot} as the theatrical key visual.")
            conf = float(data.get("confidence", 0.93))

            logger.info(
                "Gemini visual poster selection succeeded: %s (confidence %.2f)",
                sel_ref,
                conf,
            )
            return PosterSelectionResult(
                selected_reference=sel_ref,
                selected_shot_id=sel_shot,
                reason=reason,
                confidence=conf,
                candidates=candidate_refs,
                visual_candidates_evaluated=len(visual_candidates),
            )

        except Exception as exc:
            logger.error("Production/Strict Mode: Real Gemini dynamic poster selection failed: %s", exc)
            raise RuntimeError(
                f"Real Gemini visual poster selection failed: {exc}. "
                "Fake or fallback poster selection is strictly prohibited outside MOCK_MODE."
            ) from exc

