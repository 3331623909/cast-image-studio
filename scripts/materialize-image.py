#!/usr/bin/env python3
"""Materialise a provider result into the frozen output intent of one image.

Providers hand back whatever they feel like: a different container, an alpha
channel nobody asked for, a stray colour profile, the wrong pixel size for the
requested aspect ratio. This script is the single place that fixes that, and it
refuses to guess:

* the aspect ratio is only ever achieved by cropping to the largest centred
  rectangle of the target ratio, and cropping is allowed only when the source is
  within ``--max-crop`` of the target (default 0.02, i.e. 2% of the pixels);
* a source that has to be scaled is scaled with Lanczos and recorded as such;
* alpha is dropped by compositing onto the frozen background colour, never by
  simply discarding the channel, so transparent pixels do not become black.

Every action it takes is written to the sidecar report, and the run manifest is
not touched: recording the candidate is `manage-run.py record-candidate`'s job.

Usage:
    python scripts/materialize-image.py --run-dir <run_dir> --image <image_id> \
        --source <provider_output> --output <path.png> [--report <path.json>]
        [--max-crop 0.02] [--allow-scale]
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import sys
from pathlib import Path
from typing import Any

try:
    from PIL import Image
except ImportError:  # pragma: no cover - only on a broken install
    print(json.dumps({"ok": False, "error": "Pillow is required to materialise images"}))
    raise SystemExit(2)

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))

_spec = importlib.util.spec_from_file_location("cast_manage_run", SCRIPT_DIR / "manage-run.py")
assert _spec and _spec.loader
manage = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(manage)

PILLOW_FORMAT = {"png": "PNG", "jpeg": "JPEG", "jpg": "JPEG", "webp": "WEBP"}
PILLOW_EXTENSION = {"png": ".png", "jpeg": ".jpg", "jpg": ".jpg", "webp": ".webp"}
RESAMPLING = Image.Resampling.LANCZOS


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def ratio_target(aspect_ratio: str) -> tuple[int, int]:
    left, _, right = aspect_ratio.partition(":")
    if not left.isdigit() or not right.isdigit() or int(left) <= 0 or int(right) <= 0:
        raise manage.RunError(f"Unsupported aspect ratio: {aspect_ratio}")
    return int(left), int(right)


def background_rgb(image: dict[str, Any], frozen: dict[str, Any]) -> tuple[int, int, int] | None:
    background = image.get("background") or {}
    colour = background.get("color")
    if not colour and isinstance(frozen.get("background"), dict):
        colour = frozen["background"].get("color")
    if not colour:
        return None
    text = str(colour).lstrip("#")
    if len(text) != 6:
        raise manage.RunError(f"Unsupported background colour: {colour}")
    return tuple(int(text[index:index + 2], 16) for index in (0, 2, 4))  # type: ignore[return-value]


def centred_ratio_box(width: int, height: int, target: tuple[int, int]) -> tuple[int, int, int, int]:
    """Largest centred rectangle of the target ratio that fits inside the source."""
    target_width, target_height = target
    scale = min(width / target_width, height / target_height)
    crop_width = max(1, min(width, int(round(target_width * scale))))
    crop_height = max(1, min(height, int(round(target_height * scale))))
    left = (width - crop_width) // 2
    top = (height - crop_height) // 2
    return left, top, left + crop_width, top + crop_height


def materialise(source: Path, destination: Path, image: dict[str, Any],
                max_crop: float, allow_scale: bool, frozen: dict[str, Any]) -> dict[str, Any]:
    if not source.is_file():
        raise manage.RunError(f"Source image does not exist: {source}")
    if source.resolve() == destination.resolve():
        raise manage.RunError("Source and destination are the same file; refuse to work in place")
    output = image["output"]
    wanted_format = PILLOW_FORMAT.get(str(output["format"]).lower())
    if not wanted_format:
        raise manage.RunError(f"Unsupported output format: {output['format']}")
    wanted_extension = PILLOW_EXTENSION[str(output["format"]).lower()]
    if destination.suffix.lower() not in {wanted_extension, ".jpeg"}:
        raise manage.RunError(f"Destination extension must be {wanted_extension} for {output['format']}")

    actions: list[str] = []
    with Image.open(source) as handle:
        handle.load()
        original_format = (handle.format or "").upper()
        original_size = handle.size
        original_mode = handle.mode
        # Always normalise to RGBA: alpha compositing and the flatten step below
        # both require a four-channel frame, and providers happily return RGB.
        frame = handle.convert("RGBA")

    target = ratio_target(str(output["aspect_ratio"]))
    crop_box = centred_ratio_box(frame.width, frame.height, target)
    if crop_box != (0, 0, frame.width, frame.height):
        cropped_width = crop_box[2] - crop_box[0]
        cropped_height = crop_box[3] - crop_box[1]
        removed = 1.0 - (cropped_width * cropped_height) / (frame.width * frame.height)
        if removed > max_crop:
            raise manage.RunError(
                f"Reaching {output['aspect_ratio']} from {frame.width}x{frame.height} would crop "
                f"{removed:.1%} of the picture, above the {max_crop:.1%} limit; regenerate instead"
            )
        frame = frame.crop(crop_box)
        actions.append(
            f"cropped {frame.width}x{frame.height} centred from {original_size[0]}x{original_size[1]} "
            f"({removed:.2%} removed)"
        )

    resolution = output["resolution"]
    if resolution["mode"] == "exact":
        expected = (int(resolution["width"]), int(resolution["height"]))
        if frame.size != expected:
            if not allow_scale:
                raise manage.RunError(
                    f"Source is {frame.size[0]}x{frame.size[1]} but the assignment froze {expected[0]}x{expected[1]}; "
                    "pass --allow-scale to resize with Lanczos, or regenerate at the right size"
                )
            frame = frame.resize(expected, RESAMPLING)
            actions.append(f"resized to {expected[0]}x{expected[1]} with Lanczos")

    if output["alpha"]:
        actions.append("kept the alpha channel")
    else:
        colour = background_rgb(image, frozen)
        if colour is None:
            # No background colour is frozen: flatten onto white rather than black.
            colour = (255, 255, 255)
            actions.append("flattened alpha onto white (no background colour was frozen)")
        else:
            actions.append("flattened alpha onto the frozen background colour")
        flat = Image.new("RGBA", frame.size, colour + (255,))
        flat.alpha_composite(frame)
        frame = flat.convert("RGB")

    if frame.mode == "RGB" and wanted_format == "JPEG":
        pass
    destination.parent.mkdir(parents=True, exist_ok=True)
    save_options: dict[str, Any] = {}
    if wanted_format == "PNG":
        save_options["optimize"] = True
    if wanted_format == "JPEG":
        save_options["quality"] = 95
    frame.save(destination, format=wanted_format, **save_options)
    if wanted_format != original_format:
        actions.append(f"rewrote the container {original_format or 'unknown'} -> {wanted_format}")

    with Image.open(destination) as written:
        written.load()
        final_size = written.size
        final_mode = written.mode
        final_format = (written.format or "").upper()

    return {
        "actions": actions,
        "source": str(source),
        "source_sha256": sha256(source),
        "source_format": original_format,
        "source_size": list(original_size),
        "source_mode": original_mode,
        "output": str(destination),
        "output_sha256": sha256(destination),
        "output_format": final_format,
        "output_size": list(final_size),
        "output_mode": final_mode,
        "output_bytes": destination.stat().st_size,
        "aspect_ratio": str(output["aspect_ratio"]),
        "alpha_requested": bool(output["alpha"]),
        "resized": any(action.startswith("resized") for action in actions),
        "cropped": any(action.startswith("cropped") for action in actions),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-dir", required=True)
    parser.add_argument("--image", required=True)
    parser.add_argument("--source", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--report")
    parser.add_argument("--max-crop", type=float, default=0.02)
    parser.add_argument("--allow-scale", action="store_true")
    args = parser.parse_args()
    try:
        root, assignment, _manifest = manage.load_run(Path(args.run_dir))
        image = manage.image_spec(assignment, args.image)
        frozen = image
        source = Path(args.source).resolve()
        destination = Path(args.output).resolve()
        if destination.exists():
            raise manage.RunError(f"Refusing to overwrite {destination}")
        record = materialise(source, destination, image, args.max_crop, args.allow_scale, frozen)
    except (manage.RunError, OSError, Image.DecompressionBombError) as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 2
    payload = {"ok": True, "image": args.image, "run_dir": str(root), **record}
    if args.report:
        report_path = Path(args.report)
        if report_path.exists():
            print(json.dumps({"ok": False, "error": f"Refusing to overwrite {report_path}"}, ensure_ascii=False),
                  file=sys.stderr)
            return 2
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
