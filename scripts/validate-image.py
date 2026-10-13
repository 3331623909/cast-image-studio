#!/usr/bin/env python3
"""Run the automatic image gates for one candidate and emit the QA record.

These gates are the only checks a machine performs: geometry, colour mode and
alpha policy. They never claim anything about style, anatomy or likeness, and
the emitted `identity_required_elements` field is always NOT-CHECKED so that no
later step can mistake an automatic pass for a human review.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from typing import Any

try:
    from PIL import Image
except ImportError:  # pragma: no cover - only on a broken install
    print(json.dumps({"ok": False, "error": "Pillow is required to inspect candidate images"}))
    raise SystemExit(2)

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))

import importlib.util

_spec = importlib.util.spec_from_file_location("cast_manage_run", SCRIPT_DIR / "manage-run.py")
assert _spec and _spec.loader
manage = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(manage)

NOT_CHECKED = "NOT-CHECKED"
FORMAT_EXTENSIONS = {"PNG": ".png", "JPEG": ".jpg", "WEBP": ".webp"}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def ratio_of(width: int, height: int) -> str:
    from math import gcd

    divisor = gcd(width, height)
    return f"{width // divisor}:{height // divisor}"


# A provider rarely returns the exact pixel count the ratio implies, so the frozen
# crop lands on a neighbouring size (3:4 can be 1769x2359, not 1770x2360). Compare
# the ratios as numbers with a tight tolerance instead of comparing the reduced
# ratio strings, which would reject a correct crop over one pixel of rounding.
ASPECT_RATIO_TOLERANCE = 0.005


def ratio_value(text: str) -> float | None:
    left, _, right = str(text).partition(":")
    if not left.strip().isdigit() or not right.strip().isdigit():
        return None
    denominator = int(right.strip())
    if denominator == 0:
        return None
    return int(left.strip()) / denominator


def inspect(candidate: Path, image: dict[str, Any]) -> dict[str, Any]:
    if not candidate.is_file():
        raise manage.RunError(f"Candidate does not exist: {candidate}")
    output = image["output"]
    with Image.open(candidate) as handle:
        handle.load()
        width, height = handle.size
        image_format = (handle.format or "").upper()
        mode = handle.mode
        has_alpha = mode in {"RGBA", "LA", "PA"} or "transparency" in handle.info
        bands = len(handle.getbands())
        icc = handle.info.get("icc_profile") is not None

    metrics: dict[str, Any] = {
        "sha256": sha256(candidate),
        "bytes": candidate.stat().st_size,
        "width": width,
        "height": height,
        "aspect_ratio": ratio_of(width, height),
        "format": image_format,
        "mode": mode,
        "bands": bands,
        "has_alpha_channel": has_alpha,
        "has_icc_profile": icc,
    }

    geometry = "PASS"
    notes: list[str] = []
    if image_format != output["format"].upper():
        geometry = "FAIL"
        notes.append(f"format is {image_format or 'unknown'}, expected {output['format'].upper()}")
    expected_extension = FORMAT_EXTENSIONS.get(image_format)
    if expected_extension and candidate.suffix.lower() not in {expected_extension, ".jpeg"}:
        geometry = "FAIL"
        notes.append(f"file extension {candidate.suffix.lower()} does not match {image_format}")
    if metrics["aspect_ratio"] != output["aspect_ratio"]:
        actual_value = ratio_value(metrics["aspect_ratio"])
        expected_value = ratio_value(str(output["aspect_ratio"]))
        if actual_value is None or expected_value is None:
            geometry = "FAIL"
            notes.append(f"aspect ratio is {metrics['aspect_ratio']}, expected {output['aspect_ratio']}")
        elif abs(actual_value - expected_value) > ASPECT_RATIO_TOLERANCE * expected_value:
            geometry = "FAIL"
            notes.append(f"aspect ratio is {metrics['aspect_ratio']}, expected {output['aspect_ratio']}")
    if output["resolution"]["mode"] == "exact":
        expected = (output["resolution"]["width"], output["resolution"]["height"])
        if (width, height) != expected:
            geometry = "FAIL"
            notes.append(f"resolution is {width}x{height}, expected {expected[0]}x{expected[1]}")
    elif width < 512 or height < 512:
        geometry = "FAIL"
        notes.append(f"provider-native resolution {width}x{height} is too small to evaluate")

    colour_mode = "PASS"
    if mode not in {"RGB", "RGBA", "L", "LA", "P"}:
        colour_mode = "FAIL"
        notes.append(f"colour mode {mode} is not a flat illustration mode")
    if bands not in {1, 2, 3, 4}:
        colour_mode = "FAIL"
        notes.append(f"{bands} colour bands is not a plausible illustration file")

    alpha_policy = "PASS"
    if output["alpha"] and not has_alpha:
        alpha_policy = "FAIL"
        notes.append("the assignment requires a real alpha channel and the file has none")
    if not output["alpha"] and has_alpha:
        alpha_policy = "FAIL"
        notes.append("the assignment forbids alpha and the file carries one")

    verdict = "PASS" if geometry == colour_mode == alpha_policy == "PASS" else "FAIL"
    return {
        "verdict": verdict,
        "candidate_sha256": metrics["sha256"],
        "geometry": geometry,
        "colour_mode": colour_mode,
        "alpha_policy": alpha_policy,
        "identity_required_elements": NOT_CHECKED,
        "metrics": metrics,
        "notes": notes,
        "machine_verified_only": [
            "geometry", "colour_mode", "alpha_policy",
        ],
        "not_machine_verifiable": [
            "style_consistency", "register_consistency", "anatomy_contact", "cast_accuracy",
            "text_accuracy", "pose_and_story", "identity_required_elements",
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--candidate", required=True)
    parser.add_argument("--run-dir")
    parser.add_argument("--image")
    parser.add_argument("--output")
    args = parser.parse_args()
    try:
        if bool(args.run_dir) != bool(args.image):
            raise manage.RunError("--run-dir and --image must be given together")
        if args.run_dir:
            _root, assignment, _manifest = manage.load_run(Path(args.run_dir))
            image = manage.image_spec(assignment, args.image)
        else:
            raise manage.RunError("--run-dir and --image are required to know the output intent")
        record = inspect(Path(args.candidate).resolve(), image)
    except (manage.RunError, OSError, Image.DecompressionBombError) as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 2
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
