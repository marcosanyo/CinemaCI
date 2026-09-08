"""Cinema CI — Gemini Creative Change Semantic Parser.

Interprets natural language filmmaking instructions (e.g. "Remove Marcus's eyeglasses")
into structured CreativeChangeRequest objects using Vertex AI Gemini 3.8 Flash.
Semantic interpretation is strictly decoupled from graph traversal, which is
executed deterministically by ImpactEngine.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
from typing import Any

from app.impact.models import ChangeType, CreativeChangeRequest
from app.model_config import GEMINI_MODEL

from dotenv import load_dotenv

load_dotenv()
logger = logging.getLogger(__name__)


def _get_genai_client() -> Any:
    """Initializes and returns the Google GenAI client based on environment."""
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


async def parse_creative_change_prompt(prompt: str) -> CreativeChangeRequest:
    """Parses a natural language change request using Gemini 3.8 Flash.

    Args:
        prompt: Filmmaker instruction string.

    Returns:
        Structured CreativeChangeRequest schema.
    """
    prompt_clean = prompt.strip()
    logger.info("Parsing creative change request: '%s' with %s", prompt_clean, GEMINI_MODEL)

    mock_mode = (
        os.environ.get("MOCK_MODE", "false").lower() in ("true", "1", "yes")
        or os.environ.get("MOCK_LLM", "false").lower() in ("true", "1", "yes")
    )
    if mock_mode:
        logger.info("MOCK_MODE is active: Bypassing Gemini LLM and using deterministic rule parser.")
        return _fallback_rule_parser(prompt_clean)

    strict_mode = (
        os.environ.get("STRICT_MODE", "true").lower() in ("true", "1")
        or os.environ.get("CINEMA_STRICT_MODE", "0").lower() in ("true", "1")
    )

    try:
        from google.genai import types

        client = _get_genai_client()
        system_instruction = (
            "You are Cinema CI's Creative Change Semantic Parser. "
            "Convert natural language filmmaking change instructions into structured JSON. "
            "Extract: entity_id (format: character:<name>, prop:<name>, or shot:<id>), "
            "change_type (one of: VISUAL_ATTRIBUTE, NARRATIVE_ACTION, AUDIO_PROPERTY, TEXT_DIALOGUE, PROP_SPEC, CAMERA_DIRECTION), "
            "property (e.g. glasses, coat, hair, color), old_value, new_value, and description."
        )

        user_prompt = (
            f"Parse this filmmaking creative change request into JSON:\n"
            f"Request: \"{prompt_clean}\"\n\n"
            "Return JSON matching this schema:\n"
            "{\n"
            '  "entity_id": "character:marcus",\n'
            '  "change_type": "VISUAL_ATTRIBUTE",\n'
            '  "property": "glasses",\n'
            '  "old_value": "round eyeglasses",\n'
            '  "new_value": "no glasses",\n'
            '  "description": "Remove Marcus\'s eyeglasses"\n'
            "}"
        )

        def call_gemini():
            return client.models.generate_content(
                model=GEMINI_MODEL,
                contents=[user_prompt],
                config=types.GenerateContentConfig(
                    system_instruction=system_instruction,
                    response_mime_type="application/json",
                    temperature=0.0,
                ),
            )

        response = await asyncio.wait_for(asyncio.to_thread(call_gemini), timeout=15.0)
        raw_text = (response.text or "").strip()
        if raw_text.startswith("```json"):
            raw_text = raw_text[7:]
        elif raw_text.startswith("```"):
            raw_text = raw_text[3:]
        if raw_text.endswith("```"):
            raw_text = raw_text[:-3]

        data = json.loads(raw_text.strip())
        change_type_str = data.get("change_type", "VISUAL_ATTRIBUTE")
        try:
            change_type = ChangeType(change_type_str)
        except (ValueError, KeyError):
            change_type = ChangeType.VISUAL_ATTRIBUTE

        entity = data.get("entity_id", "character:marcus")
        if not (entity.startswith("character:") or entity.startswith("prop:") or entity.startswith("shot:")):
            if "marcus" in entity.lower() or "alice" in entity.lower():
                entity = f"character:{entity.lower()}"
            else:
                entity = f"character:{entity}"

        return CreativeChangeRequest(
            raw_prompt=prompt_clean,
            entity_id=entity,
            change_type=change_type,
            property=data.get("property", "coat"),
            old_value=data.get("old_value", ""),
            new_value=data.get("new_value", ""),
            description=data.get("description", prompt_clean),
        )

    except Exception as exc:
        if not mock_mode:
            logger.error("Production/Strict Mode: Gemini semantic parsing failed: %s", exc)
            raise RuntimeError(
                f"Gemini semantic parsing failed for '{prompt_clean}': {exc}. "
                "Fallback and fake behavior are strictly prohibited outside MOCK_MODE."
            ) from exc
        logger.info("MOCK_MODE fallback activated: %s", exc)
        return _fallback_rule_parser(prompt_clean)


def _fallback_rule_parser(prompt: str) -> CreativeChangeRequest:
    """Deterministic fallback parser for offline testing environments."""
    p_lower = prompt.lower()
    char_id = "marcus" if ("marcus" in p_lower or "alice" not in p_lower) else "alice"
    char_name = "Marcus" if char_id == "marcus" else "Alice"

    if any(k in p_lower for k in ("glasses", "eyeglass", "sunglass", "remove")):
        old_val = "round eyeglasses"
        new_val = (
            "no glasses"
            if any(k in p_lower for k in ("no", "remove", "without"))
            else ("sunglasses" if "sunglass" in p_lower else "no glasses")
        )
        return CreativeChangeRequest(
            raw_prompt=prompt,
            entity_id=f"character:{char_id}",
            change_type=ChangeType.VISUAL_ATTRIBUTE,
            property="glasses",
            old_value=old_val,
            new_value=new_val,
            description=f"Remove {char_name}'s eyeglasses (change glasses from {old_val} to {new_val})",
        )

    if "coat" in p_lower or "jacket" in p_lower:
        old_val = "black" if "black" in p_lower else "red"
        new_val = "red" if ("to red" in p_lower or "red" in p_lower) else "black"
        if "yellow" in p_lower:
            old_val, new_val = "black", "yellow"
        elif "black to red" in p_lower:
            old_val, new_val = "black", "red"
        elif "red to black" in p_lower:
            old_val, new_val = "red", "black"

        return CreativeChangeRequest(
            raw_prompt=prompt,
            entity_id=f"character:{char_id}",
            change_type=ChangeType.VISUAL_ATTRIBUTE,
            property="coat",
            old_value=old_val,
            new_value=new_val,
            description=f"Change {char_name}'s coat from {old_val} to {new_val}",
        )

    if "hair" in p_lower:
        return CreativeChangeRequest(
            raw_prompt=prompt,
            entity_id=f"character:{char_id}",
            change_type=ChangeType.VISUAL_ATTRIBUTE,
            property="hair",
            old_value="short fade haircut",
            new_value="dreadlocks" if "dread" in p_lower else "short fade haircut",
            description=f"Change {char_name}'s hair style/color",
        )

    if "envelope" in p_lower or "prop" in p_lower:
        return CreativeChangeRequest(
            raw_prompt=prompt,
            entity_id="prop:envelope",
            change_type=ChangeType.PROP_SPEC,
            property="color",
            old_value="blue",
            new_value="yellow" if "yellow" in p_lower else "red",
            description="Change envelope prop color",
        )

    return CreativeChangeRequest(
        raw_prompt=prompt,
        entity_id=f"character:{char_id}",
        change_type=ChangeType.VISUAL_ATTRIBUTE,
        property="glasses",
        old_value="round eyeglasses",
        new_value="no glasses",
        description=prompt,
    )

