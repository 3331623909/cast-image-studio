#!/usr/bin/env python3
"""Build the cast-image-studio character registry from the existing Whale-chan library.

Run once while creating the skill. It reads the previously authored registry
(the seven supplied character sheets), enriches every entry with the fields the
cast runner needs, rebuilds the asset paths under ``assets/characters/``, adds
Whale-chan as an ordinary registered character, and copies the master images.

Usage:
    python build-cast-registry.py [--source <character-library.json>]   # one-time build
    python build-cast-registry.py --check                               # read-only verification
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import sys
from pathlib import Path

SKILL_ROOT = Path(__file__).resolve().parents[1]

# This tool rebuilds the registry from the two sibling whalechan skills, so it has to find them
# without hard-coding one machine's home directory. It looks next to itself first (the normal
# `~/.dsh/skills/<name>` layout), then honours these two environment variables as an escape hatch
# for other layouts:
#   CAST_STUDIO_COMIC_SKILL   -> the whalechan-image-comic skill directory
#   CAST_STUDIO_CHARACTER_SKILL -> the whalechan-image-character skill directory
SKILLS_ROOT = SKILL_ROOT.parent
COMIC_SKILL = Path(
    os.environ.get("CAST_STUDIO_COMIC_SKILL") or SKILLS_ROOT / "whalechan-image-comic"
).resolve()
CHARACTER_SKILL = Path(
    os.environ.get("CAST_STUDIO_CHARACTER_SKILL") or SKILLS_ROOT / "whalechan-image-character"
).resolve()

DEFAULT_SOURCE = COMIC_SKILL / "assets" / "character-library" / "character-library.json"
OLD_MASTER_ROOT = COMIC_SKILL / "assets" / "character-library"
WHALE_CHAN_MASTER = (
    CHARACTER_SKILL
    / "assets"
    / "reference-images"
    / "semi-chibi"
    / "0092_enduring_release_delay_rendered_isolated.webp"
)

RATIO_AUTHORITY = {
    "note": (
        "drawn_ratio is the character's own design ratio, recorded and used only to plan "
        "relative height inside a cast. It is never a QA target: the frozen register is the "
        "only proportion target, and every character is redrawn at that register. A cast that "
        "mixes registers records one register per character and states the intended relative "
        "height in the scene instead of pretending one register fits all."
    ),
    "source": "note-graded from the single supplied sheet's pixel landmarks, or the bundled semi-chibi master for Whale-chan",
    "confidence_low": "sheet was cluttered or the chin/sole landmarks were partially hidden",
    "confidence_high": "clean full-body sheet with an unobstructed chin and sole line",
}

REGISTERS = {
    "mature": "standard adult anime register: roughly 6-8 heads, full-length limbs, adult face construction",
    "compact": "compact register: roughly 4.5-6 heads, shorter limbs, simplified but still adult-shaped face",
    "chibi": "chibi-adjacent register: roughly 2.5-3.5 heads, very large head, short rounded body, small feet",
}

BRIEFS = {
    "c01": {
        "value": "iridescent star sparkles; a midriff star cutout on the bodice; a cat tail that must read as a tail",
        "draw_note": (
            "Long hair and cat tail make her silhouette wide; keep the four-point prismatic stars as flat "
            "graphic shapes rather than glow, and keep the heterochromia legible at any size."
        ),
    },
    "c02": {
        "value": "curved dragon horns; small dragon wings; a thick scaled tail with a fin tip; the small blue droplet companion",
        "draw_note": (
            "She is the tallest of the supplied characters: long loose hair, a floor-length gown and a long "
            "tail. At a compact register, shorten the gown and tighten the hair mass rather than shrinking only "
            "the head. She is the only white-and-silver character in the library, so she anchors that palette."
        ),
    },
    "c03": {
        "value": "star-tipped ribbons and blue tassels; a white hexagonal handbag with a star emblem; a layered indigo-and-white skirt",
        "draw_note": (
            "Layered skirt plus mantle make her the most heavily dressed character; at a compact register keep "
            "the mantle's cloud pattern and the skirt's layers readable instead of flattening them. "
            "Her palette is the closest to Whale-chan's, so keep her ornaments distinct, not recoloured."
        ),
    },
    "c04": {
        "value": "the prismatic rainbow beam through the raised lens; the K monogram; staff lines and piano keys printed on the dress",
        "draw_note": (
            "Music-note and staff-line patterning is the character's whole reading; keep the print as line art, "
            "not as readable text, and keep the flute in hand or clearly in frame. "
            "Her monochrome black-and-white scheme is the strongest contrast in the library."
        ),
    },
    "c05": {
        "value": "a daisy hair ornament; a book held against her chest; orange-and-black sash layers; black-and-orange hems",
        "draw_note": (
            "The daisy motif must stay a daisy at every size, and the book must not be dropped: it is half her "
            "silhouette. Orange hair plus black vest plus white dress is her exact reading; do not warm the "
            "dress or cool her hair."
        ),
    },
    "c06": {
        "value": "bat-wing hair ribbons; a small black crown; an open fanged grin; an oversized double-bladed battle axe with an X-shaped head",
        "draw_note": (
            "The axe is oversized on purpose: keep it longer than she is tall even at a compact register, and "
            "keep the grin open with visible fangs. She is the only character carrying a weapon, so the axe alone "
            "must identify her in a crowd."
        ),
    },
    "c07": {
        "value": "a white beret with the MINIMAX waveform mark; a cross-body tote with a clapperboard; a handheld audio recorder",
        "draw_note": (
            "The waveform mark must be drawn as a graphic, never as letters. Her shorts-and-sneakers build makes "
            "her the most compact of the supplied characters, so she fits a chibi register with the least "
            "redesign."
        ),
    },
}

WHALE_CHAN = {
    "id": "whalechan",
    "display_name": "Whale-chan",
    "aliases": ["Whale-chan", "鲸鱼娘", "小鲸鱼", "DeepSeek Whale-chan", "whale chan"],
    "kind": "canonical",
    "look": None,
    "design": (
        "ageless humanoid girl, broad round face, large expressive eyes with a blue gradient, tiny nose, small "
        "mouth, rosy cheeks, deep-ocean-blue hair mass fading to cyan curled ends, paired side whale-fin ears, "
        "one forward-curving ahoge, one coherent naturally attached whale tail, two arms and two legs"
    ),
    "outfit": (
        "canonical navy-and-white ornate maid outfit: white frilled headpiece, navy neck bow with a blue gem, "
        "dark-navy sleeves and bodice, white frilled collar and apron with a small blue whale emblem, muted-gold "
        "piping, white frilled hem and socks, dark-blue strap shoes"
    ),
    "value": "paired whale-fin ears; the forward-curving ahoge; a naturally attached whale tail; the whale emblem on the apron",
    "palette": ["navy", "ocean blue", "cyan", "white", "warm pale skin", "muted gold"],
    "drawn_ratio": 2.8,
    "confidence": "high",
    "register": "chibi",
    "ratio_note": (
        "The bundled semi-chibi reference measures 2.8 heads; her canonical design spans 2.1-4.0 heads across the "
        "five bundled forms. 2.8 is the recorded master value, not a requirement."
    ),
    "prompt_block": (
        "REGISTERED CHARACTER whalechan (Whale-chan, also called 鲸鱼娘): ageless humanoid girl with a broad round "
        "face, large expressive eyes with a blue gradient, tiny nose, small mouth, rosy cheeks, deep-ocean-blue "
        "hair mass fading to cyan curled ends, paired side whale-fin ears, one forward-curving ahoge, one "
        "coherent naturally attached whale tail, two arms and two legs. Outfit: canonical navy-and-white ornate "
        "maid outfit with white frilled headpiece, navy neck bow with a blue gem, dark-navy sleeves and bodice, "
        "white frilled collar and apron with a small blue whale emblem, muted-gold piping, white frilled hem and "
        "socks, dark-blue strap shoes. Keep the palette navy, ocean blue, cyan, white, warm pale skin and muted "
        "gold."
    ),
    "negative": (
        "Do not remove or restyle the whale-fin ears, the ahoge or the whale tail; do not turn her into a mermaid, "
        "a whale-bodied creature or a child; do not drop the whale emblem from the apron."
    ),
    "draw_note": (
        "Her large head and short limbs set the compact end of the library. When she shares a frame with mature "
        "characters, the frame must either state one register for everyone or state the intended relative height; "
        "never let her default semi-chibi ratio silently decide the rest of the cast."
    ),
    "proportion_policy": "mature",
    "name_note": "Whale-chan is the project's canonical character. She is one registered character among others here: she appears only when the cast names her.",
}

NEW_MASTER_ROOT = "assets/characters"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def copy_master(source: Path, destination: Path) -> None:
    """Copy a master image unless the destination is already a complete copy.

    Re-running the builder must be idempotent: it must never truncate a master that is already on disk,
    and a partial destination must not be left behind if the copy is interrupted.
    """
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.is_file() and destination.stat().st_size == source.stat().st_size:
        return
    temporary = destination.with_name(destination.name + ".incoming")
    shutil.copy2(source, temporary)
    temporary.replace(destination)


def slug(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")


def normalise_key(value: str) -> str:
    return re.sub(r"[^a-z0-9\u4e00-\u9fff]+", "", value.lower())


def check_registry() -> int:
    """Verify the shipped registry without writing anything. Read-only."""
    path = SKILL_ROOT / "assets" / "characters" / "character-registry.json"
    problems: list[str] = []
    if not path.exists():
        print(json.dumps({"ok": False, "error": f"registry missing: {path}"}, ensure_ascii=False, indent=2))
        return 2
    registry = json.loads(path.read_text(encoding="utf-8"))
    characters = registry.get("characters")
    if not isinstance(characters, list) or not characters:
        print(json.dumps({"ok": False, "error": "registry.characters must be a non-empty list"}, ensure_ascii=False, indent=2))
        return 2
    required = ("id", "display_name", "aliases", "asset", "identity_lock", "prompt_block", "negative")
    seen: set[str] = set()
    keys: set[str] = set()
    for entry in characters:
        identifier = entry.get("id", "<missing id>")
        if identifier in seen:
            problems.append(f"duplicate id: {identifier}")
        seen.add(identifier)
        for field in required:
            if not entry.get(field):
                problems.append(f"{identifier}: missing or empty {field}")
        for alias in entry.get("aliases") or []:
            keys.add(normalise_key(alias))
        keys.add(normalise_key(entry.get("display_name", "")))
        asset = entry.get("asset") or {}
        relative = asset.get("path")
        if not relative:
            problems.append(f"{identifier}: asset.path missing")
            continue
        absolute = (SKILL_ROOT / relative).resolve()
        if not str(absolute).startswith(str(SKILL_ROOT.resolve())):
            problems.append(f"{identifier}: asset.path escapes the skill root: {relative}")
            continue
        if not absolute.exists():
            problems.append(f"{identifier}: master image missing: {relative}")
            continue
        if asset.get("sha256") and sha256(absolute) != asset["sha256"]:
            problems.append(f"{identifier}: sha256 mismatch for {relative}")
        if asset.get("bytes") is not None and absolute.stat().st_size != asset["bytes"]:
            problems.append(f"{identifier}: byte size mismatch for {relative}")
        if entry.get("primary_reference") and entry["primary_reference"] != relative:
            problems.append(f"{identifier}: primary_reference does not match asset.path")
    print(json.dumps({
        "ok": not problems,
        "registry": str(path),
        "characters": len(characters),
        "ids": sorted(seen),
        "lookup_keys": len(keys),
        "problems": problems,
    }, ensure_ascii=False, indent=2))
    return 0 if not problems else 1


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", default=str(DEFAULT_SOURCE))
    parser.add_argument(
        "--check",
        action="store_true",
        help="verify the existing registry read-only instead of rebuilding it",
    )
    args = parser.parse_args()
    if args.check:
        return check_registry()
    source = Path(args.source)
    old = json.loads(source.read_text(encoding="utf-8"))
    old_characters = old["characters"]

    characters: list[dict] = []
    warnings: list[str] = []

    for entry in old_characters:
        identifier = entry["id"]
        brief = BRIEFS.get(identifier)
        if brief is None:
            warnings.append(f"no brief authored for {identifier}; value/draw_note left empty")
            brief = {"value": "", "draw_note": ""}
        display = entry["display_name"]
        asset_slug = slug(display)
        new_relative = f"{NEW_MASTER_ROOT}/{identifier}/{identifier}_{asset_slug}_01_master.jpg"
        old_relative = entry["asset"]["path"]
        old_path = OLD_MASTER_ROOT / Path(old_relative).relative_to("assets/character-library")
        new_path = SKILL_ROOT / new_relative
        new_path.parent.mkdir(parents=True, exist_ok=True)
        copy_master(old_path, new_path)
        digested = sha256(new_path)
        if digested != entry["asset"]["sha256"]:
            warnings.append(f"{identifier}: copied master hash differs from the source registry")
        form = entry.get("character_form", {})
        drawn = form.get("note_graded_head_ratio")
        if drawn is None:
            warnings.append(f"{identifier}: no drawn ratio recorded")
            drawn = 6.0
        register = "chibi" if drawn <= 3.6 else "compact" if drawn <= 6.0 else "mature"
        characters.append(
            {
                "id": identifier,
                "display_name": display,
                "aliases": entry["aliases"],
                "kind": entry["kind"],
                "look": entry.get("look", entry["identity_lock"]),
                "design": entry["identity_lock"],
                "outfit": next(
                    (
                        item
                        for item in entry["signature_elements"]
                        if item.lower().startswith(("navy bodice", "white hanfu", "white qipao", "black-and-white victorian", "white dress with a black vest", "black gold-trimmed victorian", "white jacket"))
                    ),
                    "",
                ),
                "value": brief["value"],
                "signature_elements": entry["signature_elements"],
                "palette": entry["palette"],
                "drawn_ratio": drawn,
                "confidence": form.get("confidence", "low"),
                "register": register,
                "proportion_policy": {"chibi": "as-drawn", "compact": "redraw", "mature": "mature"}[register],
                "ratio_note": form.get("note", ""),
                "asset": {
                    "path": new_relative,
                    "sha256": digested,
                    "media_type": "image/jpeg",
                    "bytes": new_path.stat().st_size,
                    "width": entry["asset"]["width"],
                    "height": entry["asset"]["height"],
                },
                "primary_reference": new_relative,
                "identity_lock": entry["identity_lock"],
                "draw_note": brief["draw_note"],
                "prompt_block": entry["prompt_block"],
                "negative": entry["negative"],
                "name_note": entry["name_note"],
            }
        )

    whale_relative = f"{NEW_MASTER_ROOT}/whalechan/whalechan_whale-chan_01_master.webp"
    whale_path = SKILL_ROOT / whale_relative
    whale_path.parent.mkdir(parents=True, exist_ok=True)
    copy_master(WHALE_CHAN_MASTER, whale_path)
    whale_entry = dict(WHALE_CHAN)
    whale_entry["signature_elements"] = [
        "paired side whale-fin ears",
        "forward-curving ahoge",
        "one naturally attached whale tail",
        "white frilled headpiece and apron",
        "small blue whale emblem on the apron",
        "muted-gold piping and navy neck bow with a blue gem",
    ]
    whale_entry["assemble_brief"] = (
        "She is the only character with whale-fin ears, an ahoge and a tail at once, and the only one in a "
        "navy-and-white maid outfit."
    )
    whale_entry["asset"] = {
        "path": whale_relative,
        "sha256": sha256(whale_path),
        "media_type": "image/webp",
        "bytes": whale_path.stat().st_size,
        "width": 1024,
        "height": 1024,
    }
    whale_entry["primary_reference"] = whale_relative
    whale_entry["identity_lock"] = (
        "deep-ocean-blue hair mass fading to cyan curled ends, broad round face, blue-gradient eyes, paired "
        "side whale-fin ears, forward-curving ahoge, one naturally attached whale tail"
    )
    whale_entry["name_note"] = WHALE_CHAN["name_note"]
    whale_entry["ratio_note"] = WHALE_CHAN["ratio_note"]
    characters.append(whale_entry)

    # The registry outranks the aliases: reject any key that two characters share.
    keys: dict[str, str] = {}
    for entry in characters:
        for candidate in [entry["id"], entry["display_name"], *entry["aliases"]]:
            key = normalise_key(candidate)
            owner = keys.get(key)
            if owner is not None and owner != entry["id"]:
                raise SystemExit(f"ambiguous lookup key {candidate!r}: {owner} and {entry['id']}")
            keys[key] = entry["id"]

    registry = {
        "schema_version": 2,
        "registry_id": "cast-image-studio-characters",
        "title": "Cast Image Studio character registry",
        "owner_skill": "cast-image-studio",
        "canonical_character": None,
        "authority": (
            "Machine-readable authority for every character this skill may draw: ids, reference sheets, SHA-256 "
            "hashes, looks, drawn ratios, prompt blocks and negatives. Read a character's prompt_block verbatim "
            "into the generation prompt; never describe a registered character from memory and never paraphrase a "
            "negative."
        ),
        "usage_rules": [
            "There is no default protagonist. A character appears in an image only when the frozen cast names it.",
            "A character reference controls identity only. It never controls style, costume, background, pose, crop, composition or text; those come from the request and from art_direction.",
            "Art-style consistency comes from the frozen art_direction contract, not from any character's sheet. Every character is drawn in the register and style that contract states.",
            "drawn_ratio is a planning hint for relative height inside a cast. It is never a QA target and never overrides the frozen register.",
            "One reference image per character per image task is enough, and only for characters that are physically in frame or drawn as an avatar.",
            "Declare a character reference with the character's id as the reference id; identity is always one of its roles.",
            "The master images are the user's original files (or the bundled canonical master for Whale-chan), stored byte-for-byte. Their hashes are frozen: do not re-encode, re-compress or upscale them.",
        ],
        "ratio_authority": RATIO_AUTHORITY,
        "registers": REGISTERS,
        "proportion_policy_values": {
            "as-drawn": "the character's own design is already close to the frozen register; scale only",
            "redraw": "keep identity, redesign scale: redraw limbs and torso at the frozen register",
            "mature": "keep the character's adult apparent age; never turn an adult character into a child",
        },
        "characters": characters,
    }
    destination = SKILL_ROOT / "assets" / "characters" / "character-registry.json"
    destination.write_text(json.dumps(registry, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({
        "registry": str(destination),
        "characters": [entry["id"] for entry in characters],
        "lookup_keys": len(keys),
        "warnings": warnings,
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
