#!/usr/bin/env python3
"""Assemble one provider prompt from a frozen cast-image assignment.

The prompt is deterministic: registry identity blocks, the shared art contract,
the frozen register of every in-frame character, typed reference roles and the
exact text directive are copied verbatim, so two runs with the same assignment
produce the same prompt. An existing output file is never overwritten.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

SKILL_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SKILL_ROOT / "scripts"))

import importlib.util

_spec = importlib.util.spec_from_file_location("cast_manage_run", SKILL_ROOT / "scripts" / "manage-run.py")
assert _spec and _spec.loader
manage = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(manage)

MATERIAL_EXCERPT_LIMIT = 4000

REPRESENTATION_TEXT = {
    "physical": "drawn in the picture as a fully present character",
    "avatar": "drawn in the picture as a partial or symbolic presence, not a full body",
    "offscreen": "mentioned in the text but never drawn",
    "absent": "declared only so the cast is complete; does not appear at all",
}


def registry() -> dict[str, dict[str, Any]]:
    return manage.load_registry()


def relative_reference(path: str, run_dir: Path) -> str:
    try:
        return str(Path(path).resolve().relative_to(run_dir.resolve()))
    except ValueError:
        return path


def material_section(assignment: dict[str, Any]) -> list[str]:
    data = assignment["input"]
    lines = ["MATERIAL", f"- Language: {data['language']}"]
    if data["kind"] == "brief":
        lines.append(f"- Brief: {data['brief']}")
        return lines
    if data.get("theme"):
        lines.append(f"- Assigned theme: {data['theme']}")
    if data.get("path"):
        lines.append(f"- Source file: {data['path']}")
    source = data.get("text")
    if source:
        excerpt = source.strip()
        clipped = len(excerpt) > MATERIAL_EXCERPT_LIMIT
        if clipped:
            excerpt = excerpt[:MATERIAL_EXCERPT_LIMIT].rstrip() + " ..."
        lines.append("- Source material" + (" (truncated for length; the picture must follow the selected concept, "
                                            "not the whole source)" if clipped else "") + ":")
        lines.extend(f"    {line}" for line in excerpt.splitlines())
    return lines


def cast_section(image: dict[str, Any], characters: dict[str, dict[str, Any]]) -> list[str]:
    lines = ["CAST", "- Whale-chan is not assumed; only the characters listed here may appear."]
    for member in image["cast"]:
        entry = characters[member["character"]]
        lines.append(f"- {entry['display_name']} ({member['character']}): {REPRESENTATION_TEXT[member['representation']]}.")
        lines.append(f"    panels: {member['panels'] or 'none'}")
        if member["staging"]:
            lines.append(f"    staging: {member['staging']}")
    return lines


def identity_section(image: dict[str, Any], characters: dict[str, dict[str, Any]]) -> list[str]:
    in_frame = [member for member in image["cast"] if member["representation"] in {"physical", "avatar"}]
    if not in_frame:
        raise manage.RunError("This image has nobody in frame; at least one physical or avatar character is required")
    registers = {item["id"]: item for item in image["registers"]}
    lines = ["IDENTITY (verbatim identity locks; never blend two characters into one)"]
    for member in in_frame:
        entry = characters[member["character"]]
        register = registers[member["character"]]
        lines.append("")
        lines.append(entry["prompt_block"].strip())
        lines.append(f"    register: {register['register']} at about {register['head_ratio']} heads tall "
                     f"(accept {register['acceptance_range'][0]}-{register['acceptance_range'][1]})")
        lines.append(f"    proportion handling: {register['scale_instruction']}")
        personality = str(entry.get("personality") or "").strip()
        if personality and not personality.lower().startswith("kept as drawn"):
            lines.append(f"    personality: {personality}")
        lines.append(f"    never: {entry['negative'].strip()}")
    return lines


def art_section(image: dict[str, Any]) -> list[str]:
    art = image["art"]
    register = art["register"]
    if register["mode"] == "locked":
        mode_line = (f"- Shared register: every in-frame character is redrawn at the {register['name']} register "
                     f"({register['head_ratio']} heads). {register['reason']}")
    elif register["mode"] == "follow_cast":
        mode_line = (f"- Register follows {register['follow']}, so the whole picture sits at the {register['name']} "
                     f"register ({register['head_ratio']} heads). {register['reason']}")
    else:
        members = ", ".join(f"{item}={name}" for item, name in sorted(register["members"].items()))
        mode_line = (f"- Mixed register: {members}. {register['relative_height']}")
    lines = [
        "ART CONTRACT (identical for every character and for every panel; only identity differs)",
        f"- Preset: {art['preset']} ({art['style']['name']}, {art['style']['mode']})",
        f"- Line: {art['line']}",
        f"- Shading: {art['shading']}",
        f"- Highlights: {art['highlights']}",
        f"- Palette: {art['palette']}",
        f"- Finish: {art['finish']}",
        mode_line,
        "- Draw all characters with the same line weight, the same number of shading steps and the same highlight "
        "treatment. A character may keep her own hue family, but not her own rendering style.",
        "- Every panel of this page is drawn by the same hand: the same line weight, the same shading step count and "
        "the same contrast level in every single panel. If one panel looks rendered, photographic or computer "
        "generated while the others look drawn, the page is rejected.",
    ]
    extras = art.get("extras")
    if extras:
        lines.extend(f"- {item}" for item in extras)
    return lines


def panels_section(image: dict[str, Any]) -> list[str]:
    frame = image["comic"]
    count = frame["panel_count"]
    if count == 1:
        header = (f"PANEL LAYOUT: this page is ONE single unbroken panel, laid out as {frame['layout']}. "
                  "Do not add inner borders or split the picture.")
    else:
        header = (f"PANEL LAYOUT: exactly {count} panels, arranged as {frame['layout']}, read "
                  f"{frame['reading_direction']}. {frame['gutters'].capitalize()}.")
    lines = [header]
    for panel in image["panels"]:
        if count == 1:
            lines.append(f"- Panel {panel['panel']}: shot {panel['shot']}; {panel['action']} "
                         f"(expression: {panel['expression']})")
        else:
            lines.append(f"- Panel {panel['panel']} (shot {panel['shot']}): {panel['action']} "
                         f"(expression: {panel['expression']})")
        if panel.get("props"):
            lines.append(f"    props: {', '.join(panel['props'])}")
        if panel.get("transition"):
            lines.append(f"    transition into the next panel: {panel['transition']}")
    return lines


def lettering_section(image: dict[str, Any]) -> list[str]:
    lettering = image["lettering"]
    lines = [
        "LETTERING (exact; this is the only text allowed anywhere on the page)",
        f"- Language: {lettering['language']}",
        f"- Treatment: {lettering['text_style']} — {manage.text_style_fragment(lettering['text_style'])}",
        f"- Why this treatment: {lettering['style_reason']}",
    ]
    for line in lettering["core_text"]:
        lines.append(
            f"- panel {line['panel']} | {line['delivery']} | speaker={line['speaker']}: {line['text']}"
        )
    lines.extend([
        "- Reproduce every quoted string character for character. Do not translate, shorten, reorder or repeat it, "
        "and add no other words, letters, numbers, logo or watermark anywhere on the page.",
        "- Speech belongs in a balloon whose tail points at the mouth of the speaker named for that line. A title or "
        "caption carries no tail. A sound effect is drawn as part of the artwork and gets no balloon.",
        "- Keep every unit of lettering inside its own panel, in the panel's empty space, and clear of faces, hands, "
        "the acting gesture and the gutter.",
    ])
    return lines


def reference_section(image: dict[str, Any], run_dir: Path) -> list[str]:
    lines = ["REFERENCE ROLES (each reference controls only its declared roles)"]
    for reference in image["references"]:
        roles = ", ".join(reference["roles"])
        lines.append(f"- {relative_reference(reference['path'], run_dir)}  roles: {roles}")
        lines.append(f"    {reference['instruction']}")
    if not image["references"]:
        lines.append("- none; every character is described by the identity locks above alone")
    lines.append("- A reference sheet never controls background, pose, framing or head ratio. Never copy its text, "
                 "props or composition, and never copy one character's features onto another.")
    return lines


def output_section(image: dict[str, Any]) -> list[str]:
    output = image["output"]
    resolution = output["resolution"]
    frame = image["comic"]
    size = ("the provider's native size for this aspect ratio" if resolution["mode"] == "provider-native"
            else f"{resolution['width']}x{resolution['height']}")
    alpha = "a transparent background with a real alpha channel" if output["alpha"] else "no alpha channel"
    background = image["background"]
    if frame["panel_count"] == 1:
        layout_line = ("- One single unbroken panel: no collage, no border, no further frames inside the picture, and "
                       "no lettering outside the picture.")
    else:
        layout_line = (f"- One comic page holding all {frame['panel_count']} panels at once, in one picture: "
                       f"{frame['gutters']}, read {frame['reading_direction']}. Do not return separate pictures and do "
                       "not add extra panels.")
    return [
        "OUTPUT",
        f"- Aspect ratio {output['aspect_ratio']}, resolution {size}, format {output['format']}, {alpha}.",
        f"- Background ({background['mode']}): {background['description']}",
        layout_line,
    ]


def build_prompt(assignment: dict[str, Any], image: dict[str, Any], run_dir: Path) -> str:
    characters = registry()
    frame = image["comic"]
    task = (f"TASK: one finished manga page titled {image['title']!r} ({image['id']}) telling one short story "
            f"in {frame['panel_count']} panel(s), complete with its own lettering.")
    blocks = [
        [task],
        material_section(assignment),
    ]
    if assignment.get("selection"):
        blocks.append(["SELECTED TREATMENT", f"- {assignment['selection']}"])
    detail = assignment.get("selection_detail")
    if detail:
        lines = [f"- Confirmed concept {detail['proposal_id']}: {detail['title']}"]
        if detail.get("rating"):
            lines.append(f"- Reviewer rating when proposed: {detail['rating']}")
        if detail.get("frame"):
            lines.append(f"- Confirmed frame: {detail['frame']}")
        for adjustment in detail.get("adjustments") or []:
            lines.append(f"- User change, overrides the proposal: {adjustment}")
        blocks.append(["SELECTED TREATMENT (frozen selection record)", *lines])
    if assignment.get("cast_markdown"):
        blocks.append(["CAST NOTES (from the confirmed concept)", assignment["cast_markdown"]])
    blocks.extend([
        cast_section(image, characters),
        identity_section(image, characters),
        art_section(image),
        panels_section(image),
        ["FRAMING", f"- Shot: {image['shot']}", f"- Framing: {image['framing']}",
         f"- Subject: {image['subject']}", f"- Expression: {image['expression']}"] +
        ([f"- Action: {image['action']}"] if image.get("action") else []) +
        ([f"- Interaction: {image['interaction']}"] if image.get("interaction") else []) +
        ([f"- Composition: {image['composition']}"] if image.get("composition") else []) +
        ([f"- Props: {', '.join(str(item) for item in image['props'])}"] if image.get("props") else []),
        reference_section(image, run_dir),
        lettering_section(image),
        output_section(image),
    ])
    return "\n\n".join("\n".join(block) for block in blocks) + "\n"


def force_utf8_streams() -> None:
    """Pin stdout/stderr to UTF-8 so a Windows console code page cannot break the output."""
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is None:
            continue
        try:
            reconfigure(encoding="utf-8")
        except (ValueError, OSError):
            pass


def main() -> int:
    force_utf8_streams()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-dir", required=True)
    parser.add_argument("--image", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    try:
        run_dir, assignment, _manifest = manage.load_run(Path(args.run_dir))
        image = manage.image_spec(assignment, args.image)
        prompt = build_prompt(assignment, image, run_dir)
        destination = Path(args.output)
        if not destination.is_absolute():
            destination = (run_dir / destination).resolve()
        if destination.exists():
            raise manage.RunError(f"Refusing to overwrite an existing prompt file: {destination}")
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(prompt, encoding="utf-8")
    except (manage.RunError, OSError) as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 2
    print(json.dumps({"ok": True, "prompt_file": str(destination), "images": [image["id"]],
                      "panels": image["comic"]["panel_count"],
                      "text_style": image["lettering"]["text_style"],
                      "characters": [item["id"] for item in image["registers"]],
                      "reference_count": len(image["references"])}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
