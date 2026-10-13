#!/usr/bin/env python3
"""Extend the automatic gates for a finished multi-character image.

Adds background integrity, an alpha coverage check, a flat-illustration colour
check, lossless reference-sheet inspection and a mechanical injection survey.
Identity, likeness, anatomy, style consistency and text accuracy stay human
gates and are reported as NOT-CHECKED, never as a pass.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import math
import sys
from collections import Counter
from pathlib import Path
from typing import Any

try:
    from PIL import Image
except ImportError:  # pragma: no cover
    print(json.dumps({"ok": False, "error": "Pillow is required"}))
    raise SystemExit(2)

SCRIPT_DIR = Path(__file__).resolve().parent
_spec = importlib.util.spec_from_file_location("cast_manage_run", SCRIPT_DIR / "manage-run.py")
assert _spec and _spec.loader
manage = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(manage)

_spec_image = importlib.util.spec_from_file_location("cast_validate_image", SCRIPT_DIR / "validate-image.py")
assert _spec_image and _spec_image.loader
validate_image = importlib.util.module_from_spec(_spec_image)
_spec_image.loader.exec_module(validate_image)

NOT_CHECKED = "NOT-CHECKED"
BACKGROUND_TOLERANCE = 16
BORDER_WITHIN_MIN = 0.9
BORDER_CLEAN_SIDES_MIN = 3
ALPHA_COVERAGE_MIN = 0.02
ALPHA_COVERAGE_MAX = 0.97
COLOUR_SATURATION_MIN = 40.0
GRAYSCALE_TOLERANCE = 12.0


def parse_colour(value: str) -> tuple[int, int, int]:
    return (int(value[1:3], 16), int(value[3:5], 16), int(value[5:7], 16))


def background_metrics(handle: Image.Image, mode: str, expected: tuple[int, int, int] | None) -> dict[str, Any]:
    rgb = handle.convert("RGB")
    width, height = rgb.size
    # Sample the outermost row and column, keeping the four sides separate: a subject that runs off one
    # edge of the frame is a legitimate composition, while a background that is broken on every side is
    # not. Judging only the pooled border would confuse the two.
    step = max(1, min(width, height) // 48)
    sides: dict[str, list[tuple[int, int, int]]] = {"top": [], "bottom": [], "left": [], "right": []}
    for x in range(0, width, step):
        sides["top"].append(rgb.getpixel((x, 0)))
        sides["bottom"].append(rgb.getpixel((x, height - 1)))
    for y in range(0, height, step):
        sides["left"].append(rgb.getpixel((0, y)))
        sides["right"].append(rgb.getpixel((width - 1, y)))
    border = [pixel for side in sides.values() for pixel in side]
    counts: Counter[tuple[int, int, int]] = Counter(border)
    dominant, hits = counts.most_common(1)[0]
    deviations = sorted(max(abs(dominant[index] - item[index]) for index in range(3)) for item in border)
    spread = deviations[-1] if deviations else 0
    within = sum(1 for value in deviations if value <= BACKGROUND_TOLERANCE)
    side_report = {
        name: round(
            sum(1 for pixel in pixels if max(abs(dominant[index] - pixel[index]) for index in range(3)) <= BACKGROUND_TOLERANCE)
            / max(1, len(pixels)),
            3,
        )
        for name, pixels in sides.items()
    }
    clean_sides = sorted(name for name, share in side_report.items() if share >= BORDER_WITHIN_MIN)
    result: dict[str, Any] = {
        "border_dominant_rgb": list(dominant),
        "border_dominant_hex": "#%02X%02X%02X" % dominant,
        "border_dominant_share": round(hits / len(border), 3),
        "border_max_channel_drift": spread,
        "border_share_within_tolerance": round(within / len(border), 3),
        "border_clean_share_per_side": side_report,
        "border_clean_sides": clean_sides,
    }
    if mode == "solid":
        flat = len(clean_sides) >= BORDER_CLEAN_SIDES_MIN
        result["uniform"] = flat
        if flat:
            result["note"] = (
                f"background reads as a flat field on {len(clean_sides)} of 4 sides "
                f"({', '.join(clean_sides)}) against {result['border_dominant_hex']}"
            )
        else:
            result["note"] = (
                f"background is not a flat field: only {len(clean_sides)} of 4 sides "
                f"({', '.join(clean_sides) or 'none'}) hold {result['border_dominant_hex']} within "
                f"{BACKGROUND_TOLERANCE}; worst border pixel drifts {spread}"
            )
        if expected is not None:
            distance = max(abs(dominant[index] - expected[index]) for index in range(3))
            result["expected_hex"] = "#%02X%02X%02X" % expected
            result["distance_to_expected"] = distance
            result["matches_expected"] = distance <= BACKGROUND_TOLERANCE
    elif mode == "transparent":
        result["uniform"] = None
    else:
        result["uniform"] = None
        result["note"] = "scene background: only the border drift is recorded"
    return result


def alpha_coverage(handle: Image.Image) -> dict[str, Any]:
    alpha = handle.convert("RGBA").getchannel("A")
    histogram = alpha.histogram()
    total = sum(histogram)
    opaque = sum(histogram[200:])
    transparent = sum(histogram[:56])
    return {
        "opaque_share": round(opaque / total, 4),
        "fully_transparent_share": round(transparent / total, 4),
    }


def colour_metrics(handle: Image.Image) -> dict[str, Any]:
    small = handle.convert("RGB")
    small.thumbnail((160, 160))
    flattened = getattr(small, "get_flattened_data", None)
    pixels = list(flattened() if callable(flattened) else small.getdata())
    if not pixels:
        return {"sampled": 0}
    saturations: list[float] = []
    grayscale = 0
    for red, green, blue in pixels:
        maximum = max(red, green, blue)
        minimum = min(red, green, blue)
        saturations.append(float(maximum - minimum))
        if maximum - minimum <= GRAYSCALE_TOLERANCE:
            grayscale += 1
    mean = sum(saturations) / len(saturations)
    return {
        "sampled": len(pixels),
        "mean_chroma": round(mean, 1),
        "grayscale_share": round(grayscale / len(pixels), 3),
        "looks_monochrome": mean < COLOUR_SATURATION_MIN and grayscale / len(pixels) > 0.9,
    }


def reference_report(image: dict[str, Any]) -> dict[str, Any]:
    entries: list[dict[str, Any]] = []
    for reference in image["references"]:
        path = Path(reference["path"])
        digest = validate_image.sha256(path)
        entry: dict[str, Any] = {
            "id": reference["id"],
            "roles": reference["roles"],
            "path": str(path),
            "sha256": digest,
            "frozen_sha256_matches": digest == reference["sha256"],
        }
        if reference["source"] == "registered":
            with Image.open(path) as handle:
                entry["width"], entry["height"] = handle.size
                entry["mode"] = handle.mode
        entries.append(entry)
    return {
        "entries": entries,
        "identity_match": NOT_CHECKED,
        "note": "Reference files are verified by hash and geometry; whether the drawn character actually matches "
                "the sheet is a human gate.",
    }


def injection_survey(handle: Image.Image, image: dict[str, Any], characters: dict[str, dict[str, Any]]) -> dict[str, Any]:
    forbidden: dict[str, list[str]] = {}
    for member in image["cast"]:
        entry = characters[member["character"]]
        hints = [item for item in entry.get("negative_tokens", []) if isinstance(item, str)]
        forbidden[entry["display_name"]] = hints
    hints_present = sorted({hint for item in forbidden.values() for hint in item})
    return {
        "verdict": NOT_CHECKED,
        "characters": sorted(entry["display_name"] for entry in (characters[member["character"]] for member in image["cast"])),
        "forbidden_feature_hints": forbidden,
        "reason": "Whether a character's forbidden features leaked into another character cannot be decided by a "
                  "script; " + ("look specifically for: " + ", ".join(hints_present) if hints_present else
                                "compare each character against her own sheet and check that no other character's "
                                "signature features were copied onto her."),
    }


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
    parser.add_argument("--candidate", required=True)
    parser.add_argument("--run-dir", required=True)
    parser.add_argument("--image", required=True)
    parser.add_argument("--output")
    args = parser.parse_args()
    try:
        root, assignment, _manifest = manage.load_run(Path(args.run_dir))
        image = manage.image_spec(assignment, args.image)
        candidate = Path(args.candidate).resolve()
        characters = manage.load_registry()
        record = validate_image.inspect(candidate, image)
        with Image.open(candidate) as handle:
            handle.load()
            mode = image["background"]["mode"]
            colour = image["background"]["color"]
            expected = parse_colour(colour) if colour else None
            background = background_metrics(handle, mode, expected)
            coverage = alpha_coverage(handle)
            colour_stats = colour_metrics(handle)
    except (manage.RunError, OSError, Image.DecompressionBombError) as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 2

    notes = list(record.pop("notes", []))
    automatic_failures: list[str] = []
    # A solid background is judged only by whether the field that IS there matches the declared colour.
    # Whether the border is perfectly flat is reported, never fatal: a composition whose subjects run off
    # the frame legitimately fills an edge, and calling that a broken background rejects good pictures.
    if mode == "solid" and background.get("matches_expected") is False:
        automatic_failures.append("background")
        notes.append(
            f"background is {background['border_dominant_hex']} but the assignment declares "
            f"{background['expected_hex']}"
        )
    if mode == "solid" and background.get("uniform") is False:
        notes.append("background note (not fatal): " + str(background.get("note")))
    if image["output"]["alpha"]:
        share = coverage["opaque_share"]
        if not ALPHA_COVERAGE_MIN <= share <= ALPHA_COVERAGE_MAX:
            automatic_failures.append("alpha_policy")
            notes.append(f"opaque share {share} is outside the {ALPHA_COVERAGE_MIN}-{ALPHA_COVERAGE_MAX} band for a "
                         "transparent-background picture")
    if colour_stats.get("looks_monochrome"):
        automatic_failures.append("colour_mode")
        notes.append("the picture reads as monochrome; the assignment asks for a flat colour illustration")

    if automatic_failures:
        record["verdict"] = "FAIL"
    record.update({
        "background": background,
        "alpha_coverage": coverage,
        "colour_statistics": colour_stats,
        "references": reference_report(image),
        "injection_survey": injection_survey(handle, image, characters),
        "notes": notes,
        "machine_verified_only": [
            "geometry", "colour_mode", "alpha_policy", "background_integrity", "reference_integrity",
        ],
        "not_machine_verifiable": [
            "style_consistency", "register_consistency", "anatomy_contact", "cast_accuracy",
            "text_accuracy", "pose_and_story", "identity_required_elements", "injection_survey",
        ],
    })
    if args.output:
        destination = Path(args.output)
        if destination.exists():
            print(json.dumps({"ok": False, "error": f"Refusing to overwrite {destination}"}, ensure_ascii=False),
                  file=sys.stderr)
            return 2
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(json.dumps(record, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"ok": True, **record}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
