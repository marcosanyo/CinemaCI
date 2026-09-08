"""Cinema CI — Google Veo Video Generator.

Generates cinematic video assets using Google Veo (e.g. veo-3.1-lite-generate-001)
on Vertex AI via the Google GenAI SDK.
"""

from __future__ import annotations

import asyncio
import logging
import os
import time
from typing import Any

from google import genai
from google.genai import types

from app.generator.base import VideoGenerator
from app.models import CharacterSpec, GenerationResult, PropSpec, ShotSpec

logger = logging.getLogger(__name__)


class VeoGenerator(VideoGenerator):
    """Generates videos using Google Veo via the Google GenAI SDK."""

    def __init__(
        self,
        model_name: str | None = None,
        project_id: str | None = None,
        location: str | None = None,
    ) -> None:
        """Initializes the VeoGenerator with Vertex AI or Gemini Developer API credentials.

        Args:
            model_name: The Veo model identifier (default: veo-3.1-lite-generate-001).
            project_id: Google Cloud project ID.
            location: Vertex AI regional endpoint location (default: us-central1).
        """
        self.model_name = (
            model_name
            or os.environ.get("VEO_MODEL")
            or "veo-3.1-lite-generate-001"
        )
        self.project_id = project_id or os.environ.get("GOOGLE_CLOUD_PROJECT") or os.environ.get("PROJECT_ID")
        # Keep Veo's regional endpoint independent from Gemini's global endpoint.
        self.location = location or os.environ.get("VEO_LOCATION") or "us-central1"
        self.introduce_regression = False

        if self.project_id:
            logger.info("Initializing Veo client on Vertex AI (project=%s, location=%s)", self.project_id, self.location)
            self.client = genai.Client(
                vertexai=True,
                project=self.project_id,
                location=self.location,
            )
        elif os.environ.get("GOOGLE_GENAI_USE_VERTEXAI", "").lower() in ("true", "1"):
            self.client = genai.Client(vertexai=True)
        else:
            self.client = genai.Client()

    async def generate(

        self,
        shot_spec: ShotSpec,
        characters: dict[str, CharacterSpec],
        props: dict[str, PropSpec],
        output_path: str,
    ) -> GenerationResult:
        prompt = self._build_prompt(shot_spec, characters, props)
        logger.info(f"Generating video for shot '{shot_spec.id}' with model '{self.model_name}'...")
        logger.info(f"Prompt: {prompt}")

        max_attempts = 2
        last_error = "Unknown error"

        for attempt in range(1, max_attempts + 1):
            start_time = time.time()
            try:
                # Start asynchronous video generation operation
                def start_op():
                    return self.client.models.generate_videos(
                        model=self.model_name,
                        prompt=prompt,
                        config=types.GenerateVideosConfig(
                            aspect_ratio="16:9",
                            person_generation="ALLOW_ADULT",
                            number_of_videos=1,
                        ),
                    )

                logger.info(f"Initiating Veo generate_videos (attempt {attempt}/{max_attempts})...")
                operation = await asyncio.to_thread(start_op)
                op_name = getattr(operation, 'name', 'unknown')
                logger.info(f"Veo video generation operation started: {op_name}")

                # Poll for completion
                poll_interval = 10  # seconds
                max_wait_sec = 600  # 10 minutes timeout
                elapsed = 0

                while not operation.done and elapsed < max_wait_sec:
                    await asyncio.sleep(poll_interval)
                    elapsed = time.time() - start_time
                    logger.info(f"Waiting for Veo video generation for {shot_spec.id}... ({int(elapsed)}s elapsed)")

                    def refresh_op():
                        return self.client.operations.get(operation)

                    operation = await asyncio.to_thread(refresh_op)

                if not operation.done:
                    last_error = f"Veo generation timed out after {int(elapsed)} seconds (op: {op_name})"
                    logger.warning(last_error)
                    continue

                if getattr(operation, "error", None):
                    last_error = f"Veo operation error: {operation.error} (op: {op_name})"
                    logger.warning(last_error)
                    continue

                # Extract generated video
                response = getattr(operation, "response", None) or getattr(operation, "result", None)
                if not response or not getattr(response, "generated_videos", None):
                    # Check for safety or filter reasons
                    rai_count = getattr(response, "rai_media_filtered_count", None)
                    rai_reasons = getattr(response, "rai_media_filtered_reasons", None)
                    filter_info = f" (RAI filtered count: {rai_count}, reasons: {rai_reasons})" if (rai_count or rai_reasons) else ""
                    last_error = f"No generated videos returned in operation response{filter_info} (op: {op_name})"
                    logger.warning(f"Veo attempt {attempt}/{max_attempts} for {shot_spec.id}: {last_error}")
                    if attempt < max_attempts:
                        await asyncio.sleep(5)
                    continue

                generated_video = response.generated_videos[0]
                video_obj = generated_video.video

                os.makedirs(os.path.dirname(os.path.abspath(output_path)), exist_ok=True)

                # Retrieve video data
                video_bytes = getattr(video_obj, "video_bytes", None)

                if video_bytes:
                    with open(output_path, "wb") as f:
                        f.write(video_bytes)
                elif getattr(video_obj, "uri", None) and video_obj.uri.startswith("gs://"):
                    # Download from Google Cloud Storage
                    gcs_uri = video_obj.uri
                    logger.info(f"Downloading generated video from GCS: {gcs_uri}")
                    await asyncio.to_thread(self._download_from_gcs, gcs_uri, output_path)
                else:
                    # Try downloading via files API
                    try:
                        downloaded = await asyncio.to_thread(
                            self.client.files.download, file=video_obj
                        )
                        with open(output_path, "wb") as f:
                            f.write(downloaded)
                    except Exception as dl_err:
                        last_error = f"Failed to retrieve video bytes from result: {dl_err}"
                        logger.warning(last_error)
                        continue

                total_duration = time.time() - start_time
                logger.info(f"Veo video generated successfully for {shot_spec.id} in {total_duration:.1f}s -> {output_path}")

                return GenerationResult(
                    shot_id=shot_spec.id,
                    video_path=output_path,
                    success=True,
                    duration_sec=round(total_duration, 2),
                )

            except Exception as e:
                last_error = f"{type(e).__name__}: {e}"
                logger.error(f"Veo generation attempt {attempt}/{max_attempts} failed for {shot_spec.id}: {last_error}", exc_info=True)
                if attempt < max_attempts:
                    await asyncio.sleep(5)

        return GenerationResult(
            shot_id=shot_spec.id,
            video_path=output_path,
            success=False,
            error=last_error,
            duration_sec=0.0,
        )

    def _download_from_gcs(self, gcs_uri: str, local_path: str) -> None:
        """Download video artifact from GCS URI."""
        from google.cloud import storage
        # parse gs://bucket/path
        parts = gcs_uri.replace("gs://", "").split("/", 1)
        bucket_name = parts[0]
        blob_path = parts[1]

        client = storage.Client(project=self.project_id)
        bucket = client.bucket(bucket_name)
        blob = bucket.blob(blob_path)
        blob.download_to_filename(local_path)

    def _build_prompt(
        self,
        shot_spec: ShotSpec,
        characters: dict[str, CharacterSpec],
        props: dict[str, PropSpec],
    ) -> str:
        """Constructs prompt tailored for cinematic generative video models with seamless continuity."""
        setting = shot_spec.setting.strip() if shot_spec.setting else "Cozy vintage European cafe interior, warm amber tungsten lighting, wooden furniture, rainy window in background."
        prompt_parts = [
            f"Cinematic 16:9 movie scene: {shot_spec.description}",
            f"Setting: {setting}",
        ]

        if shot_spec.camera:
            prompt_parts.append(f"Camera & Style: {shot_spec.camera.strip()}")
        else:
            prompt_parts.append("Style: Realistic cinematic film, 35mm lens, natural lighting, shallow depth of field, high dynamic range, 24fps.")

        if shot_spec.characters:
            for char_id in shot_spec.characters:
                if char_id in characters:
                    c = characters[char_id]
                    desc = c.description
                    is_red_drift = bool(getattr(self, "introduce_regression", False)) and shot_spec.id == "shot_03"
                    if is_red_drift:
                        desc = desc.replace("charcoal-black", "bright red leather").replace("black wool coat", "bright red leather jacket")
                        desc += ". He wears a vibrant bright red leather jacket, strictly no black coat."
                        self.introduce_regression = False
                    prompt_parts.append(
                        f"Character {c.name}: {desc}"
                    )
                    if c.traits:
                        traits_dict = dict(c.traits)
                        if is_red_drift:
                            traits_dict["coat"] = "bright red leather jacket (vibrant red coat)"
                        trait_items = [f"{k}: {v}" for k, v in traits_dict.items()]
                        prompt_parts.append(
                            f"Character {c.name} mandatory traits (must strictly follow): {', '.join(trait_items)}"
                        )

                        # Generic accessory / trait removal (glasses, hat, mask, etc.)
                        for t_key, t_val in traits_dict.items():
                            t_str = str(t_val).lower()
                            if ("no " in t_str or "without " in t_str or t_str.strip() in ("no", "none", "false")):
                                char_name = c.name.capitalize() if c.name else "The character"
                                prompt_parts.append(
                                    f"{t_key.capitalize()} Removal (must strictly follow): {char_name} wears NO {t_key} in this shot. "
                                    f"Their face and appearance are bare and strictly free of {t_key}. "
                                    f"No frames, no lenses, no accessories of that kind."
                                )

                        # Generic Wardrobe Continuity across scenes
                        wardrobe_item = (
                            traits_dict.get("coat")
                            or traits_dict.get("jacket")
                            or traits_dict.get("wardrobe")
                            or traits_dict.get("outfit")
                        )
                        if wardrobe_item:
                            char_name = c.name.capitalize() if c.name else "The character"
                            prompt_parts.append(
                                f"Wardrobe Continuity: {char_name} must wear the exact same {wardrobe_item} across all scenes."
                            )

        if shot_spec.props:
            for prop_id, rule in shot_spec.props.items():
                if rule.present and prop_id in props:
                    p = props[prop_id]
                    desc = f"Key Prop ({p.name}): {p.description}"
                    if p.color:
                        desc += f", color: {p.color}"
                    prompt_parts.append(desc)

        # Generic prop presentation & actor continuity (replaces the old
        # shot_02-specific guards without hardcoding colors or shot ids).
        present_props = [
            props[p_id] for p_id, rule in (shot_spec.props or {}).items()
            if getattr(rule, "present", False) and p_id in props
        ]
        if present_props:
            names = ", ".join(p.name for p in present_props)
            prompt_parts.append(
                f"Prop Presentation: {names} must stay front-facing without flipping or turning over. "
                "Surfaces stay clean and uniform unless the contract specifies otherwise. "
                "Strictly no postal stickers, white address labels, barcode tags, or stamps unless specified."
            )
            if shot_spec.characters:
                prompt_parts.append(
                    "Actor Continuity: Any visible hands or skin belong to the credited character; "
                    "sleeves and wrist cuffs must match their wardrobe."
                )

        return "\n".join(prompt_parts)
