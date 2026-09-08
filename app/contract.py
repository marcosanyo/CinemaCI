"""Cinema CI — Creative Contract parser.

Loads cinema.yaml and produces a validated CinemaContract.
"""

from __future__ import annotations

import pathlib

import yaml

from app.models import (
    CharacterSpec,
    CinemaContract,
    ProjectSpec,
    PropSpec,
    ReleaseSpec,
    ShotPropRule,
    ShotSpec,
)


def load_contract(path: str | pathlib.Path) -> CinemaContract:
    """Load and validate a cinema.yaml contract file."""
    path = pathlib.Path(path)
    with open(path, "r", encoding="utf-8") as f:
        raw = yaml.safe_load(f)

    # Parse project
    project = ProjectSpec(**raw["project"])

    # Parse release
    release = ReleaseSpec(**raw.get("release", {}))

    # Parse characters
    characters: dict[str, CharacterSpec] = {}
    for name, spec in raw.get("characters", {}).items():
        characters[name] = CharacterSpec(
            name=name,
            description=spec.get("description", ""),
            traits=spec.get("traits", {}),
        )

    # Parse props
    props: dict[str, PropSpec] = {}
    for name, spec in raw.get("props", {}).items():
        props[name] = PropSpec(
            name=name,
            description=spec.get("description", ""),
            color=spec.get("color"),
        )

    # Parse shots
    shots: list[ShotSpec] = []
    for shot_raw in raw.get("shots", []):
        shot_props: dict[str, ShotPropRule] = {}
        for prop_name, prop_rule in shot_raw.get("props", {}).items():
            if isinstance(prop_rule, dict):
                shot_props[prop_name] = ShotPropRule(**prop_rule)
            else:
                shot_props[prop_name] = ShotPropRule(present=True)

        shots.append(
            ShotSpec(
                id=shot_raw["id"],
                description=shot_raw.get("description", ""),
                characters=shot_raw.get("characters", []),
                props=shot_props,
                duration_sec=shot_raw.get("duration_sec", 5.0),
            )
        )

    return CinemaContract(
        project=project,
        release=release,
        characters=characters,
        props=props,
        shots=shots,
    )


def save_contract(contract: CinemaContract, path: str | pathlib.Path) -> None:
    """Save a CinemaContract back to YAML format on disk."""
    path = pathlib.Path(path)
    data = {
        "project": contract.project.model_dump(),
        "release": contract.release.model_dump(),
        "characters": {k: v.model_dump() for k, v in contract.characters.items()},
        "props": {k: v.model_dump() for k, v in contract.props.items()},
        "shots": [s.model_dump() for s in contract.shots],
    }
    with open(path, "w", encoding="utf-8") as f:
        yaml.dump(data, f, sort_keys=False, allow_unicode=True)


def contract_snapshot_path(project_id: str) -> str:
    """Shared-store path for the current contract snapshot visible to job workers."""
    return f"contracts/{project_id}/current.yaml"


def publish_contract_snapshot(artifact_store, contract: CinemaContract) -> str:
    """Persist the current contract to the shared artifact store.

    Cloud Run Job workers run on a separate filesystem and cannot see the
    service container's local cinema.yaml. Without this snapshot they would
    generate from the stale baked-in contract (e.g. glasses still on).
    """
    import os
    import tempfile

    fd, tmp = tempfile.mkstemp(suffix=".yaml")
    os.close(fd)
    try:
        save_contract(contract, tmp)
        return artifact_store.put_file(tmp, contract_snapshot_path(contract.project.id))
    finally:
        try:
            os.remove(tmp)
        except OSError:
            pass


def load_shared_contract_snapshot(artifact_store, project_id: str):
    """Return the shared-snapshot contract, or None if absent/unreadable.

    Callers must fall back to the local contract file on None.
    """
    import os
    import tempfile

    path = contract_snapshot_path(project_id)
    try:
        if not artifact_store.exists(path):
            return None
    except Exception:
        return None
    fd, tmp = tempfile.mkstemp(suffix=".yaml")
    os.close(fd)
    try:
        artifact_store.get_file(path, tmp)
        return load_contract(tmp)
    except Exception:
        return None
    finally:
        try:
            os.remove(tmp)
        except OSError:
            pass


# Eyewear phrases, longest first, for single-pass removal (no re-matching).
_EYEWEAR_PHRASES = [
    "stylish thin-rimmed round eyeglasses",
    "thin-rimmed round eyeglasses",
    "thin-rimmed eyeglasses",
    "round eyeglasses",
    "wireframe glasses",
    "eye glasses",
    "eyeglasses",
    "spectacles",
    "sunglasses",
]


def rewrite_description_remove_glasses(description: str, char_name: str | None = None) -> str:
    """Remove eyewear mentions in one pass and append a single explicit statement.

    The previous chained str.replace produced garbled text such as
    "thin-rimmed no no glasses", which generative video models read as
    "glasses present". This yields clean "…with no glasses…" text instead.
    """
    import re

    text = description or ""
    for phrase in _EYEWEAR_PHRASES:
        pat = r"\b" + re.escape(phrase) + r"\b"
        text = re.sub(r"\band\s+" + pat, "", text, flags=re.IGNORECASE)
        text = re.sub(pat, "", text, flags=re.IGNORECASE)
    text = re.sub(r",\s*,", ",", text)
    text = re.sub(r"\s{2,}", " ", text).strip()
    text = re.sub(r"\s+([,.])", r"\1", text)
    if "no glasses" not in text.lower():
        subject = char_name.capitalize() if char_name else "He"
        text = text.rstrip(". ") + (
            f". {subject} wears no glasses; face is bare around the eyes, "
            "eyes fully visible, no eyewear of any kind."
        )
    return text


def apply_change_to_contract(contract: CinemaContract, target: dict[str, Any]) -> CinemaContract:
    """Dynamically applies a creative change request to the contract.

    Operates generically over any entity (character, prop, shot), updating traits
    and descriptions without hardcoded characters or props.
    """
    import re

    entity = str(target.get("entity") or target.get("entity_id") or "").strip()
    prop_name = str(target.get("property") or "").strip().lower()
    new_val = str(target.get("to") or target.get("new_value") or "").strip()
    old_val = str(target.get("from") or target.get("old_value") or "").strip()

    if not entity and not prop_name and not new_val:
        return contract

    # 1. Match Character Entity
    char_key = None
    if entity.startswith("character:"):
        char_key = entity.replace("character:", "").strip()
    else:
        for k, c in contract.characters.items():
            if k.lower() == entity.lower() or c.name.lower() == entity.lower() or k.lower() in entity.lower():
                char_key = k
                break

    is_prop_candidate = entity.startswith("prop:") or any(
        pk.lower() == entity.lower() or p.name.lower() == entity.lower() or pk.lower() in entity.lower()
        for pk, p in contract.props.items()
    )

    if not char_key and not is_prop_candidate and contract.characters:
        if "character" in entity.lower() or len(contract.characters) == 1:
            char_key = list(contract.characters.keys())[0]

    if char_key and char_key in contract.characters and prop_name and new_val:
        char_spec = contract.characters[char_key]
        trait_str = f"{new_val} {prop_name}" if prop_name not in new_val else new_val
        char_spec.traits[prop_name] = trait_str

        is_removal = ("no" in new_val.lower() or "without" in new_val.lower() or new_val.lower() in ("none", "false"))
        if prop_name in ("glasses", "eyeglasses", "eyewear"):
            char_spec.description = rewrite_description_remove_glasses(char_spec.description, char_spec.name)
            for s in contract.shots:
                if char_key in s.characters:
                    s.description = rewrite_description_remove_glasses(s.description, char_spec.name)
        elif is_removal:
            pat = r"\b" + re.escape(prop_name) + r"\b"
            char_spec.description = re.sub(pat, f"no {prop_name}", char_spec.description, flags=re.IGNORECASE)
            for s in contract.shots:
                if char_key in s.characters:
                    s.description = re.sub(pat, f"no {prop_name}", s.description, flags=re.IGNORECASE)
        else:
            colors = ["black", "red", "blue", "yellow", "green", "brown", "white", "gray", "grey", "purple", "orange"]
            if prop_name in ("coat", "jacket", "wardrobe", "outfit", "shirt"):
                for c in colors:
                    char_spec.description = (
                        char_spec.description
                        .replace(f"{c} {prop_name}", f"{new_val} {prop_name}")
                        .replace(f"{c} wool coat", f"{new_val} wool coat")
                    )
                if new_val not in char_spec.description:
                    char_spec.description = char_spec.description.rstrip(". ") + f", wearing a tailored {new_val} {prop_name}."
                for s in contract.shots:
                    if char_key in s.characters:
                        for c in colors:
                            s.description = (
                                s.description
                                .replace(f"{c} wool coat", f"{new_val} wool coat")
                                .replace(f"{c} coat", f"{new_val} wool coat")
                                .replace(f"{c} jacket", f"{new_val} wool coat")
                            )
                        if f"{new_val} wool coat" not in s.description and f"{new_val} coat" not in s.description and new_val not in s.description:
                            s.description = s.description.rstrip(". ") + f", wearing a tailored {new_val} {prop_name}."
            elif old_val:
                char_spec.description = char_spec.description.replace(old_val, new_val)
                for s in contract.shots:
                    if char_key in s.characters:
                        s.description = s.description.replace(old_val, new_val)
            else:
                char_spec.description = char_spec.description.rstrip(". ") + f", with {new_val} {prop_name}."
        return contract

    # 2. Match Prop Entity
    prop_key = None
    if entity.startswith("prop:"):
        prop_key = entity.replace("prop:", "").strip()
    else:
        for k, p in contract.props.items():
            if k.lower() == entity.lower() or p.name.lower() == entity.lower() or k.lower() in entity.lower():
                prop_key = k
                break

    if not prop_key and contract.props:
        if "prop" in entity.lower() or len(contract.props) == 1:
            prop_key = list(contract.props.keys())[0]

    if prop_key and prop_key in contract.props and new_val:
        prop_spec = contract.props[prop_key]
        old_color = prop_spec.color or "blue"
        if prop_name in ("color", ""):
            prop_spec.color = new_val
            colors = ["blue", "yellow", "red", "green", "white", "black", "purple", "orange"]
            if old_color and old_color.lower() not in colors:
                colors.append(old_color.lower())
            for c in colors:
                prop_spec.description = prop_spec.description.replace(c, new_val)
            if new_val not in prop_spec.description:
                prop_spec.description = f"vibrant {new_val} {prop_spec.name}"
            for s in contract.shots:
                if prop_key in s.props:
                    for c in colors:
                        s.description = s.description.replace(f"{c} paper {prop_spec.name}", f"{new_val} paper {prop_spec.name}")
                        s.description = s.description.replace(f"{c} {prop_spec.name}", f"{new_val} {prop_spec.name}")
                    if new_val not in s.description:
                        s.description = s.description.replace(prop_spec.name, f"{new_val} {prop_spec.name}")

    return contract


BASELINE_CONTRACT_YAML = """project:
  id: cafe-envelope
  title: The Blue Envelope
release:
  aspect_ratio: '16:9'
  min_resolution: 1280x720
  target_fps: 24.0
  max_duration_sec: 20.0
  audio_required: false
characters:
  marcus:
    name: marcus
    description: Charismatic African-American man in his late 20s (28 years old) with rich warm dark brown skin, defined jawline, and a clean short fade haircut with a crisp hairline. He wears a tailored charcoal-black heavyweight wool overcoat with structured shoulders and wide notch lapels, over a fitted matte black ribbed turtleneck sweater, and stylish thin-rimmed round eyeglasses.
    traits:
      coat: tailored charcoal-black heavyweight wool overcoat with wide notch lapels over a matte black ribbed turtleneck sweater
      hair: clean short fade haircut with crisp hairline
      glasses: stylish thin-rimmed round eyeglasses
props:
  envelope:
    name: envelope
    description: vibrant minimalist solid matte blue paper envelope, clean uniform surface with a single neat gold wax seal, strictly without any stickers, labels, stamps, or text markings
    color: vibrant matte blue
shots:
- id: shot_01
  description: Marcus, a handsome African-American man in his late 20s with rich dark brown skin, clean short fade haircut, and thin-rimmed round eyeglasses, wearing a tailored charcoal-black heavyweight wool overcoat with wide notch lapels over a matte black ribbed turtleneck sweater, enters the warm, dimly lit cafe from the rainy city street. He approaches a quiet wooden table by the window where a vibrant blue paper envelope is resting, sits down, and gently picks up the envelope with his dark brown hands.
  action: ''
  setting: ''
  camera: ''
  characters:
  - marcus
  props:
    envelope:
      present: true
  duration_sec: 5.0
- id: shot_02
  description: A tight cinematic macro close-up of hands (the youthful hands of an African-American man in his late 20s with rich warm dark brown skin tone and neatly manicured nails) holding the vibrant solid matte blue paper envelope in both hands by the rainy cafe window with natural subtle micro-movements, gently adjusting his grip and slightly tilting the envelope to let the warm cafe light catch the golden wax seal, while keeping the front of the envelope facing the camera without flipping it over. The envelope has a clean, uniform, unmarked royal blue paper surface with a single neat gold wax seal, completely free of any stickers, postal stamps, barcodes, or address labels. The tailored sleeve of a charcoal-black heavyweight wool overcoat and the cuff of a matte black ribbed turtleneck are clearly visible at the dark brown wrists.
  action: ''
  setting: ''
  camera: ''
  characters: []
  props:
    envelope:
      present: true
  duration_sec: 5.0
- id: shot_03
  description: Wearing the exact same tailored charcoal-black heavyweight wool overcoat with wide notch lapels over a matte black ribbed turtleneck sweater and thin-rimmed round eyeglasses, Marcus (a handsome Black man in his late 20s with rich dark brown skin and clean fade haircut) holds the vibrant blue paper envelope firmly in his dark brown hand, stands up from the wooden table, and walks toward the cafe exit, pushing through the glass door into the cool evening air.
  action: ''
  setting: ''
  camera: ''
  characters:
  - marcus
  props:
    envelope:
      present: true
  duration_sec: 5.0
"""


def get_baseline_contract() -> CinemaContract:
    """Returns a pristine baseline CinemaContract with Marcus wearing stylish thin-rimmed eyeglasses."""
    raw = yaml.safe_load(BASELINE_CONTRACT_YAML)
    project = ProjectSpec(**raw["project"])
    release = ReleaseSpec(**raw.get("release", {}))
    characters = {k: CharacterSpec(**v) for k, v in raw.get("characters", {}).items()}
    props = {k: PropSpec(**v) for k, v in raw.get("props", {}).items()}
    shots = []
    for s in raw.get("shots", []):
        shot_props = {
            k: ShotPropRule(**v) if isinstance(v, dict) else ShotPropRule(present=True)
            for k, v in s.get("props", {}).items()
        }
        shots.append(
            ShotSpec(
                id=s["id"],
                description=s.get("description", ""),
                characters=s.get("characters", []),
                props=shot_props,
                duration_sec=s.get("duration_sec", 5.0),
            )
        )
    return CinemaContract(
        project=project,
        release=release,
        characters=characters,
        props=props,
        shots=shots,
    )

