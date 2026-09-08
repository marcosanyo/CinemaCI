"""Cinema CI — Pinned Model Configuration.

Cinema CI standardizes on Gemini 3.8 Flash for multimodal analysis, semantic
change interpretation, and autonomous reliability workflows.
"""

from __future__ import annotations

# Pinned model identity for multimodal reasoning and agent orchestration.
# Downgrading to prior models is strictly prohibited to preserve evaluation fidelity.
GEMINI_MODEL: str = "gemini-3.8-flash"

# Gemini 3.8 Flash is served globally on Vertex AI endpoints.
# This is decoupled from regional video generation endpoints (e.g. Veo).
GEMINI_LOCATION: str = "global"

