#!/usr/bin/env python3
"""Validate, initialize, audit, and finalize cast image runs.

A run freezes one assignment: the cast, the art-direction contract, one image
spec per picture, the typed references, the output intent and the candidate
budget. Automatic gates cover geometry, colour, alpha and reference integrity.
Style consistency across characters can never be proven automatically, so it is
recorded as a gate that only a human review may pass.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import re
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

SKILL_ROOT = Path(__file__).resolve().parents[1]
REGISTRY_PATH = SKILL_ROOT / "assets" / "characters" / "character-registry.json"
ART_PRESETS_PATH = SKILL_ROOT / "references" / "art-presets.json"
RUNS_ROOT = Path("artifacts") / "cast-image-studio"

ASSIGNMENT_SCHEMA_VERSION = 2
MANIFEST_SCHEMA_VERSION = 2
QA_CONTRACT_VERSION = 2
REGISTRY_SCHEMA_VERSION = 2
ART_CONTRACT_VERSION = 1
TEXT_STYLE_SCHEMA_VERSION = 1

MAX_CAST = 6
MAX_REFERENCES = 12
MAX_IMAGE_CANDIDATES = 8
MAX_PROVIDER_CANDIDATES = 3
MAX_PARALLELISM = 5

DEFAULT_ART_PRESET = "manga"
DEFAULT_TEXT_STYLE = "01_speech-balloon"
TEXT_STYLES_PATH = SKILL_ROOT / "references" / "text-styles.json"
TEXT_TEMPLATE_ROOT = Path("assets") / "text-style-templates"

REPRESENTATIONS = ("physical", "avatar", "offscreen", "absent")
REFERENCE_ROLES = (
    "identity", "style", "pose_action", "composition", "costume", "background", "typography", "proportion",
    "lettering",
)
REGISTER_BANDS = {
    "chibi": (2.1, 3.6),
    "compact": (3.6, 6.0),
    "mature": (6.0, 9.0),
}
PROVIDERS = ("codex", "openai", "nano-banana", "seedream")

# Frame layout. `whole-canvas` draws every panel of the comic inside one
# provider picture, which is what keeps the line weight and contrast identical
# across panels; `panel-strip` draws one panel per picture and composes them
# afterwards.
FRAME_MODES = ("whole-canvas", "panel-strip")
LAYOUT_PANEL_COUNT = {
    "single": 1,
    "top-bottom": 2,
    "left-right": 2,
    "2x2": 4,
    "1x3": 3,
    "1x4": 4,
    "2x3": 6,
    "3x3": 9,
}
DELIVERIES = ("speech", "thought", "caption", "sfx")
RESERVED_SPEAKERS = ("narrator", "device")

AUTOMATIC_GATES = (
    "geometry", "colour_mode", "alpha_policy", "reference_integrity", "identity_required_elements",
)
HUMAN_GATES = (
    "style_consistency", "register_consistency", "anatomy_contact", "cast_accuracy",
    "text_accuracy", "pose_and_story",
)
REQUIRED_REVIEW_GATES = HUMAN_GATES


class RunError(RuntimeError):
    """A frozen contract was violated."""


# --------------------------------------------------------------------------- helpers


def now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def read_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RunError(f"Cannot read JSON {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise RunError(f"Expected a JSON object: {path}")
    return value


def write_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    handle_fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(handle_fd, "w", encoding="utf-8") as handle:
            json.dump(value, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
        os.replace(temporary, path)
    except Exception:
        Path(temporary).unlink(missing_ok=True)
        raise


def text(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise RunError(f"{label} must be a non-empty string")
    return value.strip()


def positive_int(value: Any, label: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < 1:
        raise RunError(f"{label} must be a positive integer")
    return value


def require_fields(value: Any, fields: set[str], label: str) -> None:
    if not isinstance(value, dict):
        raise RunError(f"{label} must be an object")
    missing = sorted(fields - set(value))
    if missing:
        raise RunError(f"{label} is missing required fields: {', '.join(missing)}")


def require_only_fields(value: dict[str, Any], allowed: set[str], label: str) -> None:
    extra = sorted(set(value) - allowed)
    if extra:
        raise RunError(f"{label} has unsupported fields: {', '.join(extra)}")


def string_list(value: Any, label: str) -> list[str]:
    if not isinstance(value, list) or not value:
        raise RunError(f"{label} must be a non-empty list of strings")
    result: list[str] = []
    for index, item in enumerate(value):
        if not isinstance(item, str) or not item.strip():
            raise RunError(f"{label}[{index}] must be a non-empty string")
        result.append(item.strip())
    return result


def canonical_aspect_ratio(value: Any, label: str) -> str:
    if not isinstance(value, str):
        raise RunError(f"{label} must use positive integers as W:H")
    match = re.fullmatch(r"([1-9][0-9]*):([1-9][0-9]*)", value.strip())
    if match is None:
        raise RunError(f"{label} must use positive integers as W:H")
    width, height = (int(item) for item in match.groups())
    divisor = math.gcd(width, height)
    return f"{width // divisor}:{height // divisor}"


def normalise_key(value: str) -> str:
    return re.sub(r"[^a-z0-9\u4e00-\u9fff]+", "", value.lower())


# --------------------------------------------------------------------------- registry


def load_registry() -> dict[str, dict[str, Any]]:
    """Load the character registry, verifying schema, ids, paths and hashes."""
    value = read_json(REGISTRY_PATH)
    if value.get("schema_version") != REGISTRY_SCHEMA_VERSION:
        raise RunError(f"Character registry schema_version must be {REGISTRY_SCHEMA_VERSION}")
    entries = value.get("characters")
    if not isinstance(entries, list) or not entries:
        raise RunError("Character registry must list characters")
    characters: dict[str, dict[str, Any]] = {}
    keys: dict[str, str] = {}
    for index, entry in enumerate(entries):
        label = f"registry.characters[{index}]"
        require_fields(
            entry,
            {"id", "display_name", "aliases", "asset", "primary_reference", "identity_lock",
             "prompt_block", "negative", "drawn_ratio", "register", "proportion_policy", "draw_note", "personality"},
            label,
        )
        identifier = text(entry["id"], f"{label}.id")
        if not re.fullmatch(r"[a-z][a-z0-9_]*", identifier):
            raise RunError(f"{label}.id must be lowercase letters, digits or underscores")
        if identifier in characters:
            raise RunError(f"Duplicate character id: {identifier}")
        asset = entry["asset"]
        require_fields(asset, {"path", "sha256", "media_type", "bytes", "width", "height"}, f"{label}.asset")
        path = (SKILL_ROOT / text(asset["path"], f"{label}.asset.path")).resolve()
        if not path.is_file():
            raise RunError(f"{label}.asset.path does not exist: {asset['path']}")
        if sha256(path) != asset["sha256"]:
            raise RunError(f"{label}.asset.sha256 does not match {asset['path']}")
        if entry["register"] not in REGISTER_BANDS:
            raise RunError(f"{label}.register must be one of {', '.join(REGISTER_BANDS)}")
        if entry["proportion_policy"] not in {"as-drawn", "redraw", "mature"}:
            raise RunError(f"{label}.proportion_policy is invalid")
        ratio = entry["drawn_ratio"]
        if not isinstance(ratio, (int, float)) or isinstance(ratio, bool) or ratio <= 1.0:
            raise RunError(f"{label}.drawn_ratio must be a number greater than 1.0")
        entry = dict(entry)
        entry["resolved_path"] = str(path)
        own_keys = {normalise_key(identifier), normalise_key(str(entry["display_name"]))}
        characters[identifier] = entry
        for candidate in [identifier, entry["display_name"], *entry.get("aliases", [])]:
            key = normalise_key(str(candidate))
            if key in own_keys:
                keys.setdefault(key, identifier)
                continue
            owner = keys.get(key)
            if owner is not None and owner != identifier:
                raise RunError(f"ambiguous lookup key {candidate!r}: {owner} and {identifier}")
            keys[key] = identifier
    return characters


def resolve_character(token: Any, characters: dict[str, dict[str, Any]], label: str) -> str:
    """Resolve an id, display name or alias to one registry id."""
    key = normalise_key(text(token, label))
    identifier = None
    if key in {normalise_key(item) for item in characters}:
        identifier = next(item for item in characters if normalise_key(item) == key)
    else:
        for candidate, entry in characters.items():
            if key in {normalise_key(str(name)) for name in [candidate, entry["display_name"], *entry.get("aliases", [])]}:
                identifier = candidate
                break
    if identifier is None:
        known = ", ".join(f"{entry['display_name']} ({candidate})" for candidate, entry in characters.items())
        raise RunError(f"{label} names an unregistered character {token!r}; registered: {known}")
    return identifier


def art_presets() -> dict[str, Any]:
    value = read_json(ART_PRESETS_PATH)
    if value.get("schema_version") != 1:
        raise RunError("Art preset catalogue schema_version must be 1")
    presets = value.get("presets")
    if not isinstance(presets, dict) or not presets:
        raise RunError("Art preset catalogue must define presets")
    if value.get("default") not in presets:
        raise RunError("Art preset catalogue default must name one preset")
    return value


def text_styles() -> dict[str, Any]:
    value = read_json(TEXT_STYLES_PATH)
    if value.get("schema_version") != TEXT_STYLE_SCHEMA_VERSION:
        raise RunError(f"Text style catalogue schema_version must be {TEXT_STYLE_SCHEMA_VERSION}")
    templates = value.get("templates")
    if not isinstance(templates, dict) or not templates:
        raise RunError("Text style catalogue must define templates")
    if value.get("default") not in templates:
        raise RunError("Text style catalogue default must name one template")
    resolved: dict[str, Any] = {}
    for name, entry in templates.items():
        if not isinstance(entry, dict):
            raise RunError(f"Text style {name} must be an object")
        require_fields(entry, {"label", "reference"}, f"text_styles.{name}")
        reference = Path(text(entry["reference"], f"text_styles.{name}.reference"))
        if not reference.is_absolute():
            reference = SKILL_ROOT / reference
        reference = reference.resolve()
        if not reference.is_file():
            raise RunError(f"Text style {name} reference image is missing: {reference}")
        clean = dict(entry)
        clean["reference"] = str(reference)
        resolved[name] = clean
    catalogue = dict(value)
    catalogue["templates"] = resolved
    return catalogue


def text_style_entry(name: str) -> dict[str, Any]:
    catalogue = text_styles()
    if name not in catalogue["templates"]:
        raise RunError(f"Unknown text style {name!r}; choose one of {', '.join(catalogue['templates'])}")
    return catalogue["templates"][name]


def text_style_fragment(name: str) -> str:
    """The lettering treatment text a template contributes to the prompt."""
    template = SKILL_ROOT / TEXT_TEMPLATE_ROOT / name / "template.md"
    if not template.is_file():
        raise RunError(f"Text style {name} has no template file: {template}")
    body = template.read_text(encoding="utf-8")
    if "Prompt fragment:" not in body:
        raise RunError(f"Text style template {name} has no 'Prompt fragment:' section")
    return body.split("Prompt fragment:")[-1].strip()


def text_style_reference(name: str) -> str:
    return str(Path(text_style_entry(name)["reference"]).resolve())


def default_run_dir(run_name: str) -> Path:
    return (RUNS_ROOT / run_name).resolve()


# --------------------------------------------------------------------------- art contract
def normalise_art(value: Any, characters: dict[str, dict[str, Any]], cast_ids: list[str], label: str) -> dict[str, Any]:
    require_fields(value, {"preset", "register"}, label)
    catalogue = art_presets()
    preset_name = text(value["preset"], f"{label}.preset")
    if preset_name not in catalogue["presets"]:
        raise RunError(f"{label}.preset must be one of {', '.join(catalogue['presets'])}")
    preset = catalogue["presets"][preset_name]
    declared = value["register"]
    require_fields(declared, {"mode"}, f"{label}.register")
    mode = text(declared["mode"], f"{label}.register.mode")
    resolved: dict[str, Any] = {"mode": mode}
    resolved_register: dict[str, Any] = {"mode": mode}
    if mode == "locked":
        require_fields(declared, {"mode", "name", "head_ratio", "acceptance_range", "reason"}, f"{label}.register")
        name = text(declared["name"], f"{label}.register.name")
        if name not in REGISTER_BANDS:
            raise RunError(f"{label}.register.name must be one of {', '.join(REGISTER_BANDS)}")
        ratio = declared["head_ratio"]
        if not isinstance(ratio, (int, float)) or isinstance(ratio, bool) or ratio <= 1.0:
            raise RunError(f"{label}.register.head_ratio must be a number greater than 1.0")
        low, high = REGISTER_BANDS[name]
        if not low <= float(ratio) <= high:
            raise RunError(f"{label}.register.head_ratio must sit inside the {name} band {low}-{high}")
        span = declared["acceptance_range"]
        if not isinstance(span, list) or len(span) != 2:
            raise RunError(f"{label}.register.acceptance_range must hold exactly two numbers")
        bounds: list[float] = []
        for index, item in enumerate(span):
            if not isinstance(item, (int, float)) or isinstance(item, bool):
                raise RunError(f"{label}.register.acceptance_range[{index}] must be a number")
            bounds.append(float(item))
        low_bound, high_bound = bounds
        if not low_bound < ratio < high_bound:
            raise RunError(f"{label}.register.acceptance_range must contain head_ratio")
        if abs((low_bound + high_bound) / 2 - float(ratio)) > 0.01:
            raise RunError(f"{label}.register.acceptance_range must be centred on head_ratio")
        resolved_register = {
            "mode": mode,
            "name": name,
            "head_ratio": float(ratio),
            "acceptance_range": [low_bound, high_bound],
            "reason": text(declared["reason"], f"{label}.register.reason"),
        }
    elif mode == "follow_cast":
        require_fields(declared, {"mode", "of"}, f"{label}.register")
        follower = resolve_character(declared["of"], characters, f"{label}.register.of")
        if follower not in cast_ids:
            raise RunError(f"{label}.register.of must name a character in this image's cast")
        entry = characters[follower]
        follower_band = entry["register"]
        limits = REGISTER_BANDS[follower_band]
        centre = round(min(max(entry["drawn_ratio"], limits[0] + 0.05), limits[1] - 0.05), 2)
        resolved_register = {
            "mode": mode,
            "name": follower_band,
            "follow": follower,
            "head_ratio": centre,
            "acceptance_range": [round(centre - 0.15, 3), round(centre + 0.15, 3)],
            "reason": text(declared.get("reason", f"Follow {follower}'s own drawn register."),
                           f"{label}.register.reason"),
        }
    elif mode == "mixed":
        require_fields(declared, {"mode", "members", "relative_height"}, f"{label}.register")
        members = declared["members"]
        if not isinstance(members, dict) or not members:
            raise RunError(f"{label}.register.members must map at least one cast member to a register")
        resolved_members: dict[str, str] = {}
        for token, band_name in members.items():
            identifier = resolve_character(token, characters, f"{label}.register.members.{token}")
            if identifier not in cast_ids:
                raise RunError(f"{label}.register.members names {identifier}, which is not in this image's cast")
            if band_name not in REGISTER_BANDS:
                raise RunError(f"{label}.register.members.{token} must be one of {', '.join(REGISTER_BANDS)}")
            resolved_members[identifier] = band_name
        resolved_register = {
            "mode": mode,
            "members": resolved_members,
            "relative_height": text(declared["relative_height"], f"{label}.register.relative_height"),
            "head_ratio": None,
            "acceptance_range": None,
        }
    else:
        raise RunError(f"{label}.register.mode must be locked, follow_cast or mixed")
    style = value.get("style")
    require_fields(style, {"mode"}, f"{label}.style")
    style_mode = text(style["mode"], f"{label}.style.mode")
    if style_mode == "preset":
        contract = dict(preset["contract"])
        resolved["style"] = {"mode": "preset", "name": preset_name}
    elif style_mode == "custom":
        require_fields(style, {"mode", "contract"}, f"{label}.style")
        raw_contract = style["contract"]
        require_fields(raw_contract, {"line", "shading", "highlights", "palette", "finish"}, f"{label}.style.contract")
        contract = {key: text(raw_contract[key], f"{label}.style.contract.{key}")
                    for key in ("line", "shading", "highlights", "palette", "finish")}
        resolved["style"] = {"mode": "custom", "name": preset_name}
    else:
        raise RunError(f"{label}.style.mode must be preset or custom")
    for key in ("line", "shading", "highlights", "palette", "finish"):
        resolved[key] = contract[key]
    extras = value.get("extras")
    if extras is not None:
        resolved["extras"] = string_list(extras, f"{label}.extras")
    resolved["preset"] = preset_name
    resolved["register"] = resolved_register
    return resolved


def register_for(
    identifier: str, art: dict[str, Any], characters: dict[str, dict[str, Any]]
) -> dict[str, Any]:
    """Return the register a character is drawn in and how its scale is handled."""
    entry = characters[identifier]
    register = art.get("register")
    if not isinstance(register, dict):
        raise RunError("The normalised art contract is missing its register; re-validate the assignment")
    if register["mode"] in {"locked", "follow_cast"}:
        name = register["name"]
        centre = register["head_ratio"]
        span = register["acceptance_range"]
    else:
        name = register["members"].get(identifier)
        if name is None:
            name = entry["register"]
        band = REGISTER_BANDS[name]
        centre = round(min(max(entry["drawn_ratio"], band[0] + 0.05), band[1] - 0.05), 2)
        span = [round(centre - 0.15, 3), round(centre + 0.15, 3)]
    band = REGISTER_BANDS[name]
    policy = entry["proportion_policy"]
    same_band = entry["register"] == name
    if same_band:
        instruction = (
            f"{entry['display_name']} is already drawn in the {name} register; keep the design as it is and let "
            "the frozen head ratio decide only the overall scale."
        )
    elif policy == "mature":
        instruction = (
            f"Redraw {entry['display_name']} at the {name} register without changing apparent age: keep her adult "
            "face construction and body shape, shorten or lengthen proportions only as the register requires, and "
            "never turn her into a child."
        )
    elif policy == "as-drawn":
        instruction = (
            f"{entry['display_name']}'s own sheet is close to the {name} register; keep the design and adjust only "
            "scale and limb length to reach the frozen head ratio."
        )
    else:
        instruction = (
            f"Keep {entry['display_name']}'s identity and redraw her scale at the {name} register: shorten the "
            f"torso and limbs, enlarge the head, and simplify drapery rather than shrinking the whole figure."
        )
    return {
        "id": identifier,
        "display_name": entry["display_name"],
        "register": name,
        "band": list(band),
        "head_ratio": centre,
        "acceptance_range": span,
        "drawn_ratio": entry["drawn_ratio"],
        "proportion_policy": policy,
        "scale_instruction": instruction,
    }


# --------------------------------------------------------------------------- assignment
def validate_approval(assignment: dict[str, Any]) -> dict[str, Any]:
    approval = assignment.get("confirmation")
    require_fields(approval, {"confirmed", "confirmed_at"}, "confirmation")
    if approval["confirmed"] is not True:
        raise RunError("confirmation.confirmed must be true; the plan must be confirmed before freezing")
    text(approval["confirmed_at"], "confirmation.confirmed_at")
    return approval


def normalise_selection_detail(value: Any) -> dict[str, Any] | None:
    """Record which proposed concept was chosen, and any user change to it."""
    if value is None:
        return None
    label = "selection_detail"
    if not isinstance(value, dict):
        raise RunError(f"{label} must be an object")
    require_fields(value, {"proposal_id", "title"}, label)
    require_only_fields(value, {"proposal_id", "title", "rating", "frame", "adjustments", "reply", "revision"}, label)
    detail: dict[str, Any] = {
        "proposal_id": text(value["proposal_id"], f"{label}.proposal_id"),
        "title": text(value["title"], f"{label}.title"),
    }
    for key in ("rating", "frame", "reply"):
        if value.get(key) is not None:
            detail[key] = text(value[key], f"{label}.{key}")
    if value.get("revision") is not None:
        revision = value["revision"]
        if not isinstance(revision, int) or isinstance(revision, bool) or revision < 1:
            raise RunError(f"{label}.revision must be a positive integer")
        detail["revision"] = revision
    adjustments = value.get("adjustments")
    if adjustments is not None:
        if not isinstance(adjustments, list):
            raise RunError(f"{label}.adjustments must be a list of strings")
        detail["adjustments"] = [text(item, f"{label}.adjustments[{index}]")
                                 for index, item in enumerate(adjustments)]
    return detail


def normalise_cast(
    image: dict[str, Any],
    characters: dict[str, dict[str, Any]],
    label: str,
    frame: dict[str, Any] | None = None,
) -> tuple[list[dict[str, Any]], list[str]]:
    raw = image.get("cast")
    if not isinstance(raw, list) or not raw:
        raise RunError(f"{label}.cast must name at least one character")
    if len(raw) > MAX_CAST:
        raise RunError(f"{label}.cast may name at most {MAX_CAST} characters")
    panel_count = frame["panel_count"] if frame else None
    cast: list[dict[str, Any]] = []
    seen: set[str] = set()
    order: list[str] = []
    for index, member in enumerate(raw):
        member_label = f"{label}.cast[{index}]"
        require_fields(member, {"character", "representation", "panels"}, member_label)
        require_only_fields(member, {"character", "representation", "panels", "staging", "reason"}, member_label)
        identifier = resolve_character(member["character"], characters, f"{member_label}.character")
        if identifier in seen:
            raise RunError(f"{label}.cast declares {identifier} twice")
        seen.add(identifier)
        order.append(identifier)
        representation = text(member["representation"], f"{member_label}.representation")
        if representation not in REPRESENTATIONS:
            raise RunError(f"{member_label}.representation must be one of {', '.join(REPRESENTATIONS)}")
        panels = member["panels"]
        if not isinstance(panels, list):
            raise RunError(f"{member_label}.panels must be a list")
        clean_panels: list[int] = []
        for item in panels:
            number = positive_int(item, f"{member_label}.panels")
            if panel_count is not None and number > panel_count and representation != "absent":
                raise RunError(
                    f"{member_label}.panels names panel {number} but the frozen layout has "
                    f"{panel_count} panel(s)"
                )
            clean_panels.append(number)
        if representation == "absent":
            if clean_panels:
                raise RunError(f"{member_label} is absent and must not claim panels")
        elif not clean_panels:
            raise RunError(f"{member_label} must claim at least one panel")
        staging = member.get("staging")
        if representation in {"physical", "avatar"}:
            staging = text(staging, f"{member_label}.staging")
        elif staging is not None:
            raise RunError(f"{member_label}.staging must be null when the character is {representation}")
        cast.append({
            "character": identifier,
            "display_name": characters[identifier]["display_name"],
            "representation": representation,
            "panels": sorted(set(clean_panels)),
            "staging": staging,
            "reason": text(member.get("reason", ""), f"{member_label}.reason") if member.get("reason") is not None else None,
        })
    return cast, order


def normalise_references(
    image: dict[str, Any],
    assignment_path: Path,
    characters: dict[str, dict[str, Any]],
    cast: list[dict[str, Any]],
    label: str,
    skill_root: Path | None = None,
) -> list[dict[str, Any]]:
    raw = image.get("references")
    if raw is None:
        raw = []
    if not isinstance(raw, list):
        raise RunError(f"{label}.references must be a list")
    in_frame = [member["character"] for member in cast if member["representation"] in {"physical", "avatar"}]
    declared = {member["character"] for member in cast}
    normalised: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    seen_paths: set[str] = set()
    seen_characters: set[str] = set()
    for index, item in enumerate(raw, start=1):
        item_label = f"{label}.references[{index - 1}]"
        require_fields(item, {"id", "path", "roles", "instruction"}, item_label)
        require_only_fields(
            item,
            {"id", "path", "roles", "instruction", "character", "sha256", "source", "format",
             "width", "height", "colorspace"},
            item_label,
        )
        reference_id = text(item["id"], f"{item_label}.id")
        if not re.fullmatch(r"[a-z0-9]+(?:[-_][a-z0-9]+)*", reference_id):
            raise RunError(f"{item_label}.id must use lowercase letters, digits, hyphens or underscores")
        if reference_id in seen_ids:
            raise RunError(f"Duplicate reference id: {reference_id}")
        seen_ids.add(reference_id)
        path = Path(text(item["path"], f"{item_label}.path"))
        if not path.is_absolute():
            candidate = (assignment_path.parent / path).resolve()
            if not candidate.is_file() and skill_root is not None:
                fallback = (skill_root / path).resolve()
                if fallback.is_file():
                    candidate = fallback
            path = candidate
        else:
            path = path.resolve()
        if not path.is_file():
            raise RunError(f"Reference image does not exist: {path}")
        resolved = str(path)
        if resolved in seen_paths:
            raise RunError(f"Duplicate reference path: {path}")
        seen_paths.add(resolved)
        roles = string_list(item["roles"], f"{item_label}.roles")
        if len(set(roles)) != len(roles) or not set(roles) <= set(REFERENCE_ROLES):
            raise RunError(f"{item_label}.roles contains an invalid or duplicate role")
        instruction = text(item["instruction"], f"{item_label}.instruction")
        character_id = item.get("character")
        if character_id is not None:
            character_id = resolve_character(character_id, characters, f"{item_label}.character")
            if character_id not in declared:
                raise RunError(f"{item_label}.character must be part of this image's cast")
            if "identity" not in roles:
                raise RunError(f"{item_label} is a character reference and must carry the identity role")
            if reference_id != character_id:
                raise RunError(f"{item_label}.id must be {character_id} for a character reference")
            if character_id in seen_characters:
                raise RunError(f"{label} loads two references for {character_id}")
            seen_characters.add(character_id)
            expected = characters[character_id]["resolved_path"]
            if resolved != expected:
                raise RunError(
                    f"{item_label}.path must be the registered sheet for {character_id}: "
                    f"{characters[character_id]['asset']['path']}"
                )
        normalised.append({
            "id": reference_id,
            "path": resolved,
            "roles": roles,
            "instruction": instruction,
            "character": character_id,
            "source": "registered" if character_id else "external",
            "sha256": sha256(path),
        })
    if len(normalised) > MAX_REFERENCES:
        raise RunError(f"{label}.references may hold at most {MAX_REFERENCES} images")
    missing = [item for item in in_frame if item not in seen_characters]
    if missing:
        names = ", ".join(characters[item]["display_name"] for item in missing)
        raise RunError(
            f"{label} draws {names} in frame but loads no reference; add one identity reference per in-frame character"
        )
    extra = sorted(seen_characters - set(in_frame))
    if extra:
        names = ", ".join(characters[item]["display_name"] for item in extra)
        raise RunError(f"{label} loads references for {names}, which are not in frame; drop them or change the cast")
    return normalised


def _validate_typography_reference(
    references: list[dict[str, Any]],
    lettering: dict[str, Any] | None,
    label: str,
) -> None:
    """The lettering reference must be exactly the declared style's own template."""
    marked = [item for item in references if "lettering" in item["roles"] or "typography" in item["roles"]]
    if lettering is None:
        if marked:
            raise RunError(f"{label} loads a lettering reference but the image declares no lettering")
        return
    if len(marked) != 1:
        raise RunError(
            f"{label} must load exactly one lettering reference: the template image of text style "
            f"{lettering['text_style']}"
        )
    item = marked[0]
    if sorted(item["roles"]) != ["lettering", "typography"]:
        raise RunError(f"{label} lettering reference must carry exactly the lettering and typography roles")
    expected = text_style_reference(lettering["text_style"])
    if Path(item["path"]).resolve() != Path(expected).resolve():
        raise RunError(
            f"{label} lettering reference must be the registered template of {lettering['text_style']}: "
            f"{text_style_entry(lettering['text_style'])['reference']}"
        )


def normalise_output(value: Any, label: str) -> dict[str, Any]:
    require_fields(value, {"format", "aspect_ratio", "alpha", "resolution"}, label)
    output_format = text(value["format"], f"{label}.format").lower()
    if output_format not in {"png", "jpeg", "webp"}:
        raise RunError(f"{label}.format must be png, jpeg or webp")
    alpha = value["alpha"]
    if not isinstance(alpha, bool):
        raise RunError(f"{label}.alpha must be true or false")
    resolution = value["resolution"]
    require_fields(resolution, {"mode", "width", "height"}, f"{label}.resolution")
    mode = text(resolution["mode"], f"{label}.resolution.mode")
    if mode == "provider-native":
        if resolution["width"] is not None or resolution["height"] is not None:
            raise RunError(f"{label}.resolution must leave width and height null in provider-native mode")
        width = height = None
    elif mode == "exact":
        width = positive_int(resolution["width"], f"{label}.resolution.width")
        height = positive_int(resolution["height"], f"{label}.resolution.height")
    else:
        raise RunError(f"{label}.resolution.mode must be provider-native or exact")
    return {
        "format": output_format,
        "aspect_ratio": canonical_aspect_ratio(value["aspect_ratio"], f"{label}.aspect_ratio"),
        "alpha": alpha,
        "resolution": {"mode": mode, "width": width, "height": height},
    }


def normalise_frame(value: Any, label: str) -> dict[str, Any]:
    """How the panels of one comic are laid out and how many panels there are."""
    require_fields(value, {"mode", "panel_count", "layout"}, label)
    require_only_fields(value, {"mode", "panel_count", "layout", "reading_direction", "gutters"},
                        label)
    mode = text(value["mode"], f"{label}.mode")
    if mode not in FRAME_MODES:
        raise RunError(f"{label}.mode must be one of {', '.join(FRAME_MODES)}")
    layout = text(value["layout"], f"{label}.layout")
    if layout not in LAYOUT_PANEL_COUNT:
        raise RunError(f"{label}.layout must be one of {', '.join(LAYOUT_PANEL_COUNT)}")
    count = positive_int(value["panel_count"], f"{label}.panel_count")
    if count != LAYOUT_PANEL_COUNT[layout]:
        raise RunError(f"{label}.layout {layout} needs panel_count {LAYOUT_PANEL_COUNT[layout]}, not {count}")
    direction = text(value.get("reading_direction", "left to right, then top to bottom"),
                     f"{label}.reading_direction")
    gutters = text(
        value.get("gutters", "clean even white gutters between panels, with a thin dark panel border"),
        f"{label}.gutters",
    )
    return {
        "mode": mode,
        "panel_count": count,
        "layout": layout,
        "reading_direction": direction,
        "gutters": gutters,
    }


def normalise_panels(value: Any, frame: dict[str, Any], label: str) -> list[dict[str, Any]]:
    if not isinstance(value, list) or not value:
        raise RunError(f"{label} must be a non-empty list of panels")
    count = frame["panel_count"]
    if len(value) != count:
        raise RunError(f"{label} must hold exactly {count} panels for layout {frame['layout']}")
    panels: list[dict[str, Any]] = []
    for index, item in enumerate(value):
        panel_label = f"{label}[{index}]"
        require_fields(item, {"panel", "shot", "action"}, panel_label)
        require_only_fields(item, {"panel", "shot", "action", "expression", "props", "transition"},
                            panel_label)
        number = positive_int(item["panel"], f"{panel_label}.panel")
        if number != index + 1:
            raise RunError(f"{label} must be ordered 1..{count}; entry {index} claims panel {number}")
        props = item.get("props", [])
        if not isinstance(props, list):
            raise RunError(f"{panel_label}.props must be a list")
        transition = item.get("transition")
        transition = transition.strip() if isinstance(transition, str) else ""
        panels.append({
            "panel": number,
            "shot": text(item["shot"], f"{panel_label}.shot"),
            "action": text(item["action"], f"{panel_label}.action"),
            "expression": text(item.get("expression", "as the action requires"), f"{panel_label}.expression"),
            "props": [text(prop, f"{panel_label}.props") for prop in props],
            "transition": transition,
        })
    return panels


def normalise_lettering(
    value: Any,
    frame: dict[str, Any],
    cast: list[dict[str, Any]],
    characters: dict[str, dict[str, Any]],
    label: str,
) -> dict[str, Any]:
    """The comic's exact visible text, its lettering treatment and its speakers."""
    if value is None:
        return None
    require_fields(value, {"text_style", "core_text"}, label)
    require_only_fields(value, {"text_style", "core_text", "language", "style_reason"}, label)
    style = text(value["text_style"], f"{label}.text_style")
    text_style_entry(style)
    raw = value["core_text"]
    if not isinstance(raw, list) or not raw:
        raise RunError(f"{label}.core_text must be a non-empty list of exact strings")
    declared = {member["character"]: member for member in cast}
    lookup: dict[str, str] = {}
    for member in cast:
        entry = characters[member["character"]]
        lookup[normalise_key(member["character"])] = member["character"]
        lookup.setdefault(normalise_key(entry["display_name"]), member["character"])
    count = frame["panel_count"]
    lines: list[dict[str, Any]] = []
    for index, item in enumerate(raw):
        line_label = f"{label}.core_text[{index}]"
        require_fields(item, {"index", "text", "panel", "speaker", "delivery"}, line_label)
        require_only_fields(item, {"index", "text", "panel", "speaker", "delivery"}, line_label)
        number = item["index"]
        if not isinstance(number, int) or isinstance(number, bool) or number != index:
            raise RunError(f"{label}.core_text indexes must run 0..{len(raw) - 1} in order")
        panel = positive_int(item["panel"], f"{line_label}.panel")
        if panel > count:
            raise RunError(f"{line_label}.panel {panel} is outside the frozen {count}-panel layout")
        delivery = text(item["delivery"], f"{line_label}.delivery")
        if delivery not in DELIVERIES:
            raise RunError(f"{line_label}.delivery must be one of {', '.join(DELIVERIES)}")
        raw_speaker = text(item["speaker"], f"{line_label}.speaker")
        key = normalise_key(raw_speaker)
        if key in lookup:
            speaker = lookup[key]
        elif key in RESERVED_SPEAKERS:
            speaker = key
        else:
            raise RunError(
                f"{line_label}.speaker {raw_speaker!r} is neither a character in this image's cast "
                f"nor one of {', '.join(RESERVED_SPEAKERS)}"
            )
        if delivery == "caption" and speaker not in {"narrator", "device"} | set(declared):
            raise RunError(f"{line_label} is a caption and must be spoken by the narrator")
        if speaker in declared and panel not in declared[speaker]["panels"]:
            raise RunError(
                f"{line_label}.speaker {speaker} has a line in panel {panel} but the cast does not "
                f"place that character in panel {panel}"
            )
        if delivery == "sfx" and speaker not in RESERVED_SPEAKERS and speaker not in declared:
            raise RunError(f"{line_label} is a sound effect and needs no character speaker")
        lines.append({
            "index": number,
            "text": text(item["text"], f"{line_label}.text"),
            "panel": panel,
            "speaker": speaker,
            "delivery": delivery,
        })
    covered = {line["panel"] for line in lines}
    missing = sorted(set(range(1, count + 1)) - covered)
    if missing:
        raise RunError(f"{label} gives no text to panel(s) {missing}; every panel needs its own line or caption")
    return {
        "text_style": style,
        "language": text(value.get("language", "zh-Hans"), f"{label}.language"),
        "style_reason": text(value.get("style_reason", "the default dialogue treatment"),
                             f"{label}.style_reason"),
        "core_text": lines,
    }


def normalise_text(value: Any, label: str) -> dict[str, Any] | None:
    if value is None:
        return None
    require_fields(value, {"language", "content", "placement"}, label)
    content = value["content"]
    if not isinstance(content, list) or not content:
        raise RunError(f"{label}.content must be a non-empty list of exact strings")
    lines: list[str] = []
    for index, item in enumerate(content):
        require_fields(item, {"index", "text", "speaker", "placement"}, f"{label}.content[{index}]")
        index_value = item["index"]
        if not isinstance(index_value, int) or isinstance(index_value, bool) or index_value < 0:
            raise RunError(f"{label}.content[{index}].index must be a non-negative integer")
        lines.append({
            "index": index_value,
            "text": text(item["text"], f"{label}.content[{index}].text"),
            "speaker": text(item["speaker"], f"{label}.content[{index}].speaker"),
            "placement": text(item["placement"], f"{label}.content[{index}].placement"),
        })
    expected = list(range(len(lines)))
    if [line["index"] for line in lines] != expected:
        raise RunError(f"{label}.content indexes must run 0..{len(lines) - 1} in order")
    characters = text(value.get("language"), f"{label}.language")
    return {
        "language": characters,
        "content": lines,
        "placement": text(value["placement"], f"{label}.placement"),
        "style": text(value.get("style", "hand-lettered comic lettering"), f"{label}.style"),
    }


def normalise_image(
    image: Any,
    assignment_path: Path,
    characters: dict[str, dict[str, Any]],
    label: str,
    skill_root: Path | None = None,
) -> dict[str, Any]:
    require_fields(
        image,
        {"name", "framing", "cast", "art", "background", "output"},
        label,
    )
    name = text(image["name"], f"{label}.name")
    if not re.fullmatch(r"[a-z0-9]+(?:_[a-z0-9]+)*", name):
        raise RunError(f"{label}.name must be a lowercase snake_case identifier")
    raw_comic = image.get("comic")
    if raw_comic is None:
        raise RunError(
            f"{label}.comic is required: this skill draws finished comics, so every image "
            "declares its frame mode, layout and panel count"
        )
    frame = normalise_frame(raw_comic, f"{label}.comic")
    panels = normalise_panels(image.get("panels"), frame, f"{label}.panels")
    for field in ("shot", "subject"):
        if field not in image:
            raise RunError(f"{label}.{field} is required, even with panels: it states the picture's own angle")
    cast, order = normalise_cast(image, characters, label, frame)
    art = normalise_art(image["art"], characters, order, f"{label}.art")
    references = normalise_references(image, assignment_path, characters, cast, label, skill_root)
    lettering = normalise_lettering(image.get("lettering"), frame, cast, characters, f"{label}.lettering")
    _validate_typography_reference(references, lettering, f"{label}.references")
    background = image["background"]
    require_fields(background, {"mode", "description"}, f"{label}.background")
    background_mode = text(background["mode"], f"{label}.background.mode")
    if background_mode not in {"solid", "scene", "transparent"}:
        raise RunError(f"{label}.background.mode must be solid, scene or transparent")
    background_colour = background.get("color")
    if background_colour is not None:
        if not re.fullmatch(r"#[0-9a-fA-F]{6}", text(background_colour, f"{label}.background.color")):
            raise RunError(f"{label}.background.color must be a #RRGGBB value")
        background_colour = background_colour.upper()
        if background_mode == "transparent":
            raise RunError(f"{label}.background.color is meaningless on a transparent background")
    output = normalise_output(image["output"], f"{label}.output")
    if background_mode == "transparent" and not output["alpha"]:
        raise RunError(f"{label} uses a transparent background and must set output.alpha true")
    if background_mode != "transparent" and output["alpha"]:
        raise RunError(f"{label} sets output.alpha true without a transparent background")
    registers = [register_for(member["character"], art, characters) for member in cast
                 if member["representation"] in {"physical", "avatar"}]
    result: dict[str, Any] = {
        "id": name,
        "name": name,
        "title": text(image.get("title", name), f"{label}.title"),
        "source_beat": image.get("source_beat"),
        "framing": text(image["framing"], f"{label}.framing"),
        "shot": text(image["shot"], f"{label}.shot"),
        "subject": text(image["subject"], f"{label}.subject"),
        "expression": text(image.get("expression", "as the action requires"), f"{label}.expression"),
        "action": text(image["action"], f"{label}.action") if image.get("action") is not None
        else text(image["subject"], f"{label}.action"),
        "interaction": image.get("interaction"),
        "composition": image.get("composition"),
        "props": image.get("props", []),
        "comic": frame,
        "panels": panels,
        "cast": cast,
        "art": art,
        "registers": registers,
        "background": {
            "mode": background_mode,
            "description": text(background["description"], f"{label}.background.description"),
            "color": background_colour,
        },
        "lettering": lettering,
        "text": normalise_text(image.get("text"), f"{label}.text"),
        "references": references,
        "output": output,
        "qa_contract_version": QA_CONTRACT_VERSION,
    }
    if not isinstance(result["props"], list):
        raise RunError(f"{label}.props must be a list")
    return result


def normalise_budget(value: Any, image_count: int, label: str) -> dict[str, Any]:
    require_fields(
        value,
        {"per_image_candidates", "per_provider_candidates", "run_candidates", "confirmed_over_24"},
        label,
    )
    per_image = positive_int(value["per_image_candidates"], f"{label}.per_image_candidates")
    if per_image > MAX_IMAGE_CANDIDATES:
        raise RunError(f"{label}.per_image_candidates may not exceed {MAX_IMAGE_CANDIDATES}")
    per_provider = positive_int(value["per_provider_candidates"], f"{label}.per_provider_candidates")
    if per_provider > MAX_PROVIDER_CANDIDATES:
        raise RunError(f"{label}.per_provider_candidates may not exceed {MAX_PROVIDER_CANDIDATES}")
    run_candidates = positive_int(value["run_candidates"], f"{label}.run_candidates")
    estimated = image_count * per_image
    if run_candidates < estimated:
        raise RunError(f"{label}.run_candidates must cover the estimated maximum {estimated}")
    over_twenty_four = estimated > 24
    if bool(value["confirmed_over_24"]) != over_twenty_four:
        raise RunError(f"{label}.confirmed_over_24 must be {str(over_twenty_four).lower()} for {estimated} candidates")
    if over_twenty_four and value.get("approval_note") is None:
        raise RunError(f"{label} exceeds 24 candidates and needs an approval_note")
    return {
        "per_image_candidates": per_image,
        "per_provider_candidates": per_provider,
        "run_candidates": run_candidates,
        "confirmed_over_24": over_twenty_four,
        "estimated_maximum": estimated,
        "approval_note": value.get("approval_note"),
    }


def normalise_execution(value: Any, label: str) -> dict[str, Any]:
    require_fields(value, {"mode", "requested_parallelism", "max_parallelism", "commit_strategy"}, label)
    mode = text(value["mode"], f"{label}.mode")
    if mode not in {"sequential", "parallel"}:
        raise RunError(f"{label}.mode must be sequential or parallel")
    requested = value["requested_parallelism"]
    if not isinstance(requested, int) or isinstance(requested, bool) or not 1 <= requested <= MAX_PARALLELISM:
        raise RunError(f"{label}.requested_parallelism must be an integer from 1 to {MAX_PARALLELISM}")
    if value["max_parallelism"] != MAX_PARALLELISM:
        raise RunError(f"{label}.max_parallelism must be {MAX_PARALLELISM}")
    strategy = text(value["commit_strategy"], f"{label}.commit_strategy")
    if strategy != "coordinator-serial":
        raise RunError(f"{label}.commit_strategy must be coordinator-serial")
    return {
        "mode": mode,
        "requested_parallelism": requested,
        "max_parallelism": MAX_PARALLELISM,
        "commit_strategy": strategy,
    }


def normalise_input(value: Any, label: str) -> dict[str, Any]:
    require_fields(value, {"kind"}, label)
    kind = text(value["kind"], f"{label}.kind")
    if kind == "material":
        material_text = value.get("text")
        material_path = value.get("path")
        if bool(material_text) == bool(material_path):
            raise RunError(f"{label} must carry exactly one of text or path")
        data: dict[str, Any] = {"kind": kind}
        if material_text is not None:
            data["text"] = text(material_text, f"{label}.text")
        else:
            path = Path(text(material_path, f"{label}.path"))
            if not path.is_file():
                raise RunError(f"{label}.path does not exist: {path}")
            data["path"] = str(path.resolve())
        data["language"] = text(value.get("language", "zh-Hans"), f"{label}.language")
        if value.get("theme") is not None:
            data["theme"] = text(value["theme"], f"{label}.theme")
        return data
    if kind == "brief":
        data = {"kind": kind, "brief": text(value.get("brief"), f"{label}.brief")}
        data["language"] = text(value.get("language", "zh-Hans"), f"{label}.language")
        return data
    raise RunError(f"{label}.kind must be material or brief")


def validate_assignment(assignment_path: Path) -> dict[str, Any]:
    assignment = read_json(assignment_path)
    require_fields(
        assignment,
        {"schema_version", "confirmation", "run_name", "image_count", "input", "images", "execution", "budget"},
        "assignment",
    )
    if assignment["schema_version"] != ASSIGNMENT_SCHEMA_VERSION:
        raise RunError(f"schema_version must be {ASSIGNMENT_SCHEMA_VERSION}")
    require_only_fields(
        assignment,
        {"schema_version", "confirmation", "run_name", "image_count", "input", "images", "execution", "budget",
         "selection", "selection_detail", "cast_markdown", "output_dir", "notes", "skill_root"},
        "assignment",
    )
    skill_root: Path = SKILL_ROOT
    if assignment.get("skill_root") is not None:
        skill_root = Path(text(assignment["skill_root"], "skill_root"))
        if not skill_root.is_dir():
            raise RunError(f"skill_root is not a directory: {skill_root}")
    validate_approval(assignment)
    run_name = text(assignment["run_name"], "run_name")
    if not re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", run_name):
        raise RunError("run_name must be a kebab-case identifier")
    images = assignment["images"]
    if not isinstance(images, list) or not images:
        raise RunError("images must be a non-empty list")
    if assignment["image_count"] != len(images):
        raise RunError("image_count must equal the number of images")
    characters = load_registry()
    seen: set[str] = set()
    normalised: list[dict[str, Any]] = []
    for index, image in enumerate(images):
        item = normalise_image(image, assignment_path, characters, f"images[{index}]", skill_root)
        if item["id"] in seen:
            raise RunError(f"Duplicate image name: {item['id']}")
        seen.add(item["id"])
        normalised.append(item)
    budget = normalise_budget(assignment["budget"], len(normalised), "budget")
    execution = normalise_execution(assignment["execution"], "execution")
    result = {
        "schema_version": ASSIGNMENT_SCHEMA_VERSION,
        "confirmation": validate_approval(assignment),
        "run_name": run_name,
        "image_count": len(normalised),
        "input": normalise_input(assignment["input"], "input"),
        "selection": assignment.get("selection"),
        "selection_detail": normalise_selection_detail(assignment.get("selection_detail")),
        "art_contract_version": ART_CONTRACT_VERSION,
        "cast_markdown": assignment.get("cast_markdown"),
        "notes": assignment.get("notes"),
        "images": normalised,
        "execution": execution,
        "budget": budget,
    }
    result["skill_root"] = str(skill_root.resolve())
    output_dir = assignment.get("output_dir")
    result["output_dir"] = str(Path(output_dir).resolve()) if output_dir else str(default_run_dir(run_name))
    result["registry_sha256"] = sha256(REGISTRY_PATH)
    result["art_presets_sha256"] = sha256(ART_PRESETS_PATH)
    return result


# --------------------------------------------------------------------------- run state
def initialise_run(frozen: dict[str, Any], assignment_path: Path, effective_parallelism: int | None) -> dict[str, Any]:
    run_dir = Path(frozen["output_dir"])
    if run_dir.exists():
        raise RunError(f"Run directory already exists: {run_dir}")
    run_dir.mkdir(parents=True)
    for name in ("inputs", "inputs/references", "staging", "attempts", "review", "final"):
        (run_dir / name).mkdir()
    assignment_copy = run_dir / "assignment.json"
    write_json(assignment_copy, frozen)
    frozen_references: dict[str, str] = {}
    for image in frozen["images"]:
        for reference in image["references"]:
            digest = reference["sha256"]
            suffix = Path(reference["path"]).suffix.lower()
            target = run_dir / "inputs" / "references" / f"{digest[:16]}{suffix}"
            if not target.exists():
                target.write_bytes(Path(reference["path"]).read_bytes())
            if sha256(target) != digest:
                raise RunError(f"Frozen reference copy does not match: {reference['path']}")
            frozen_references[reference["path"]] = str(target)
    for image in frozen["images"]:
        for reference in image["references"]:
            reference["source_path"] = reference["path"]
            reference["path"] = frozen_references[reference.pop("path")]
        (run_dir / "staging" / image["id"]).mkdir()
        (run_dir / "attempts" / image["id"]).mkdir()
    parallelism = frozen["execution"]["requested_parallelism"] if effective_parallelism is None else effective_parallelism
    if not isinstance(parallelism, int) or not 1 <= parallelism <= MAX_PARALLELISM:
        raise RunError(f"effective parallelism must be an integer from 1 to {MAX_PARALLELISM}")
    ready = [image["id"] for image in frozen["images"]]
    manifest = {
        "schema_version": MANIFEST_SCHEMA_VERSION,
        "status": "in_progress",
        "run_name": frozen["run_name"],
        "assignment_sha256": sha256(assignment_copy),
        "registry_sha256": frozen["registry_sha256"],
        "art_contract_version": ART_CONTRACT_VERSION,
        "provider_order": list(PROVIDERS),
        "candidate_count": 0,
        "budget": frozen["budget"],
        "execution": {**frozen["execution"], "effective_parallelism": parallelism,
                      "initial_ready_image_count": len(ready)},
        "created_at": now(),
        "updated_at": now(),
        "images": {
            image["id"]: {
                "status": "pending",
                "attempts": [],
                "provider_errors": [],
                "final_path": None,
                "final_sha256": None,
                "final_automatic": None,
                "final_review": None,
            }
            for image in frozen["images"]
        },
    }
    write_json(run_dir / "manifest.json", manifest)
    return {
        "ok": True,
        "run_dir": str(run_dir),
        "images": ready,
        "budget": frozen["budget"],
        "execution": manifest["execution"],
        "next": "Build each prompt with build-prompt.py, then generate with the configured provider.",
    }


def load_run(run_dir: Path) -> tuple[Path, dict[str, Any], dict[str, Any]]:
    root = run_dir.resolve()
    assignment = read_json(root / "assignment.json")
    manifest = read_json(root / "manifest.json")
    if sha256(root / "assignment.json") != manifest["assignment_sha256"]:
        raise RunError("The frozen assignment was modified after initialization")
    if assignment.get("schema_version") != ASSIGNMENT_SCHEMA_VERSION:
        raise RunError(f"Frozen assignment schema_version must be {ASSIGNMENT_SCHEMA_VERSION}")
    return root, assignment, manifest


def image_spec(assignment: dict[str, Any], image_id: str) -> dict[str, Any]:
    image = next((item for item in assignment["images"] if item["id"] == image_id), None)
    if image is None:
        known = ", ".join(item["id"] for item in assignment["images"])
        raise RunError(f"Unknown image id {image_id!r}; frozen images: {known}")
    return image


def validate_automatic(value: Any, image: dict[str, Any], label: str) -> dict[str, Any]:
    gates = {"geometry", "colour_mode", "alpha_policy"}
    require_fields(value, gates | {"verdict", "candidate_sha256", "metrics"}, label)
    if value["verdict"] not in {"PASS", "FAIL"}:
        raise RunError(f"{label}.verdict must be PASS or FAIL")
    for gate in gates:
        if value[gate] not in {"PASS", "FAIL"}:
            raise RunError(f"{label}.{gate} must be PASS or FAIL")
    digest = text(value["candidate_sha256"], f"{label}.candidate_sha256")
    if not re.fullmatch(r"[0-9a-f]{64}", digest):
        raise RunError(f"{label}.candidate_sha256 must be a lowercase SHA-256")
    return value


def validate_review(value: Any, image: dict[str, Any], label: str) -> dict[str, Any]:
    require_fields(value, {"verdict", "candidate_sha256", "gates", "defects"}, label)
    require_only_fields(
        value,
        {"verdict", "candidate_sha256", "gates", "defects", "style_consistency_note",
         "register_evidence", "targeted_retry", "reviewer"},
        label,
    )
    if value["verdict"] not in {"PASS", "FAIL"}:
        raise RunError(f"{label}.verdict must be PASS or FAIL")
    gates = value["gates"]
    if not isinstance(gates, dict):
        raise RunError(f"{label}.gates must be an object")
    for gate in REQUIRED_REVIEW_GATES:
        if gates.get(gate) not in {"PASS", "FAIL"}:
            raise RunError(f"{label}.gates.{gate} must be PASS or FAIL")
    extra = sorted(set(gates) - set(REQUIRED_REVIEW_GATES))
    if extra:
        raise RunError(f"{label}.gates has unknown gates: {', '.join(extra)}")
    if gates.get("style_consistency") == "PASS":
        note = value.get("style_consistency_note")
        if not isinstance(note, str) or len(note.strip()) < 20:
            raise RunError(
                f"{label}.style_consistency may only pass alongside a style_consistency_note of at least "
                "20 characters describing what was compared across characters"
            )
    defects = value["defects"]
    if not isinstance(defects, list):
        raise RunError(f"{label}.defects must be a list")
    if value["verdict"] == "PASS":
        failed = sorted(gate for gate in REQUIRED_REVIEW_GATES if gates[gate] != "PASS")
        if failed:
            raise RunError(f"{label}.verdict is PASS but these gates are not: {', '.join(failed)}")
        automatic = None
    return value


def record_candidate(args: argparse.Namespace) -> dict[str, Any]:
    run_dir, assignment, manifest = load_run(Path(args.run_dir))
    image = image_spec(assignment, args.image)
    state = manifest["images"][image["id"]]
    candidate = Path(args.candidate).resolve()
    if not candidate.is_file():
        raise RunError(f"Candidate does not exist: {candidate}")
    automatic = validate_automatic(read_json(Path(args.automatic_json).resolve()), image, "automatic")
    review = validate_review(read_json(Path(args.review).resolve()), image, "review")
    digest = sha256(candidate)
    if automatic["candidate_sha256"] != digest:
        raise RunError("automatic.candidate_sha256 does not match the candidate file")
    if review["candidate_sha256"] != digest:
        raise RunError("review.candidate_sha256 does not match the candidate file")
    if automatic["verdict"] != "PASS":
        raise RunError("The candidate failed an automatic gate and may never be promoted; fix the cause and retry")
    prompt_path = Path(args.prompt_file).resolve()
    if not prompt_path.is_file():
        raise RunError(f"Prompt file does not exist: {prompt_path}")
    number = len(state["attempts"]) + 1
    record = {
        "number": number,
        "provider": text(args.provider, "provider"),
        "model": text(args.model, "model"),
        "candidate": str(candidate),
        "candidate_sha256": digest,
        "candidate_bytes": candidate.stat().st_size,
        "prompt_file": str(prompt_path),
        "prompt_sha256": sha256(prompt_path),
        "automatic": automatic,
        "review": review,
        "recorded_at": now(),
    }
    if record["provider"] not in PROVIDERS:
        raise RunError(f"provider must be one of {', '.join(PROVIDERS)}")
    state["attempts"].append(record)
    manifest["candidate_count"] += 1
    if manifest["candidate_count"] > manifest["budget"]["run_candidates"]:
        raise RunError("The run candidate budget is exhausted; the assignment must be revised before more attempts")
    state["status"] = "candidate-ready" if review["verdict"] == "PASS" else "retry"
    manifest["updated_at"] = now()
    write_json(run_dir / "manifest.json", manifest)
    return {
        "ok": True,
        "image": image["id"],
        "attempt": number,
        "candidate_sha256": digest,
        "automatic": automatic["verdict"],
        "review": review["verdict"],
        "awaiting_review": automatic["verdict"] == "PASS" and review["verdict"] != "PASS",
        "next": "promote --candidate <candidate> once a review passes" if review["verdict"] == "PASS" else "repair by root cause",
    }


def promote(args: argparse.Namespace) -> dict[str, Any]:
    run_dir, assignment, manifest = load_run(Path(args.run_dir))
    image = image_spec(assignment, args.image)
    state = manifest["images"][image["id"]]
    candidate = Path(args.candidate).resolve()
    digest = sha256(candidate) if candidate.is_file() else None
    record = next((item for item in state["attempts"] if item["candidate_sha256"] == digest), None)
    if record is None:
        raise RunError("Only a recorded candidate may be promoted")
    if record["automatic"]["verdict"] != "PASS" or record["review"]["verdict"] != "PASS":
        raise RunError("Both the automatic gates and the human review must pass before promotion")
    suffix = Path(record["candidate"]).suffix.lower() or ".png"
    destination = run_dir / "final" / f"{image['id']}{suffix}"
    if destination.exists():
        raise RunError(f"A final image already exists: {destination}")
    destination.write_bytes(Path(record["candidate"]).read_bytes())
    state["status"] = "final"
    state["final_path"] = str(destination)
    state["final_sha256"] = sha256(destination)
    manifest["updated_at"] = now()
    write_json(run_dir / "manifest.json", manifest)
    return {"ok": True, "image": image["id"], "final_path": str(destination), "sha256": state["final_sha256"]}


def record_error(args: argparse.Namespace) -> dict[str, Any]:
    run_dir, assignment, manifest = load_run(Path(args.run_dir))
    image = image_spec(assignment, args.image)
    state = manifest["images"][image["id"]]
    entry = {
        "provider": text(args.provider, "provider"),
        "model": text(args.model, "model"),
        "category": text(args.category, "category"),
        "details": text(args.details, "details"),
        "recorded_at": now(),
    }
    if entry["category"] not in {"authentication", "rate_limit", "timeout", "service", "safety"}:
        raise RunError("category must be authentication, rate_limit, timeout, service or safety")
    state["provider_errors"].append(entry)
    if entry["category"] == "safety":
        manifest["status"] = "halted"
        for other in manifest["images"].values():
            if other["status"] in {"pending", "candidate-ready", "retry"}:
                other["status"] = "quarantined"
    manifest["updated_at"] = now()
    write_json(run_dir / "manifest.json", manifest)
    return {"ok": True, "image": image["id"], "category": entry["category"], "run_status": manifest["status"]}


def finalize(args: argparse.Namespace) -> dict[str, Any]:
    run_dir, assignment, manifest = load_run(Path(args.run_dir))
    missing = [item for item in assignment["images"] if manifest["images"][item["id"]]["status"] != "final"]
    if missing and not args.allow_partial:
        names = ", ".join(item["id"] for item in missing)
        raise RunError(f"These images have no final file: {names}; promote one or pass --allow-partial")
    if manifest["status"] == "halted":
        raise RunError("The run was halted by a recorded error and may not be finalized as success")
    manifest["status"] = "finalized" if not missing else "finalized-partial"
    manifest["finalized_at"] = now()
    manifest["open_images"] = [item["id"] for item in missing]
    manifest["updated_at"] = now()
    write_json(run_dir / "manifest.json", manifest)
    return {
        "ok": True,
        "run_dir": str(run_dir),
        "status": manifest["status"],
        "finals": {image_id: state["final_path"] for image_id, state in manifest["images"].items() if state["final_path"]},
        "open_images": manifest["open_images"],
        "candidate_count": manifest["candidate_count"],
    }


def status(args: argparse.Namespace) -> dict[str, Any]:
    run_dir, assignment, manifest = load_run(Path(args.run_dir))
    images: dict[str, Any] = {}
    for image in assignment["images"]:
        state = manifest["images"][image["id"]]
        cost = image["registers"]
        images[image["id"]] = {
            "status": state["status"],
            "attempts": len(state["attempts"]),
            "candidate_ready": [item["number"] for item in state["attempts"] if item["review"]["verdict"] == "PASS"],
            "registers": [f"{item['display_name']}={item['register']}" for item in cost],
            "final": state["final_path"],
        }
    return {
        "ok": True,
        "run_dir": str(run_dir),
        "status": manifest["status"],
        "candidate_count": manifest["candidate_count"],
        "budget": manifest["budget"],
        "images": images,
    }


# --------------------------------------------------------------------------- cli
def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)

    probe = commands.add_parser("probe-registry", help="List the registered characters")
    probe.set_defaults(func=lambda args: {
        "ok": True,
        "registry": str(REGISTRY_PATH),
        "characters": [
            {
                "id": entry["id"],
                "display_name": entry["display_name"],
                "aliases": entry["aliases"],
                "register": entry["register"],
                "drawn_ratio": entry["drawn_ratio"],
                "asset": entry["asset"]["path"],
            }
            for entry in load_registry().values()
        ],
    })

    validate = commands.add_parser("validate-assignment", help="Validate a confirmed assignment")
    validate.add_argument("--assignment", required=True)
    validate.set_defaults(func=lambda args: {
        "ok": True,
        "valid": True,
        "run_name": (frozen := validate_assignment(Path(args.assignment).resolve()))["run_name"],
        "image_count": frozen["image_count"],
        "estimated_maximum": frozen["budget"]["estimated_maximum"],
        "run_dir": frozen["output_dir"],
    })

    init = commands.add_parser("init", help="Create a non-overwriting run directory")
    init.add_argument("--assignment", required=True)
    init.add_argument("--effective-parallelism", type=int)
    init.set_defaults(func=lambda args: initialise_run(
        validate_assignment(Path(args.assignment).resolve()),
        Path(args.assignment).resolve(),
        args.effective_parallelism,
    ))

    candidate = commands.add_parser("record-candidate", help="Store one candidate and its QA")
    candidate.add_argument("--run-dir", required=True)
    candidate.add_argument("--image", required=True)
    candidate.add_argument("--provider", required=True)
    candidate.add_argument("--model", required=True)
    candidate.add_argument("--candidate", required=True)
    candidate.add_argument("--prompt-file", required=True)
    candidate.add_argument("--automatic-json", required=True)
    candidate.add_argument("--review", required=True)
    candidate.set_defaults(func=record_candidate)

    promote_parser = commands.add_parser("promote", help="Copy one fully-passing candidate into final")
    promote_parser.add_argument("--run-dir", required=True)
    promote_parser.add_argument("--image", required=True)
    promote_parser.add_argument("--candidate", required=True)
    promote_parser.set_defaults(func=promote)

    error = commands.add_parser("record-error", help="Record a provider error without spending budget")
    error.add_argument("--run-dir", required=True)
    error.add_argument("--image", required=True)
    error.add_argument("--provider", required=True)
    error.add_argument("--model", required=True)
    error.add_argument("--category", required=True)
    error.add_argument("--details", required=True)
    error.set_defaults(func=record_error)

    final = commands.add_parser("finalize", help="Close a run and record its open images")
    final.add_argument("--run-dir", required=True)
    final.add_argument("--allow-partial", action="store_true")
    final.set_defaults(func=finalize)

    state = commands.add_parser("status", help="Print a compact run summary")
    state.add_argument("--run-dir", required=True)
    state.set_defaults(func=status)

    args = parser.parse_args()
    try:
        result = args.func(args)
    except (RunError, OSError) as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 2
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
