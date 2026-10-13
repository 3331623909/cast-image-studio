#!/usr/bin/env python3
"""Contract tests for the cast-image-studio run manager and prompt builder."""
from __future__ import annotations

import copy
import importlib.util
import json
import shutil
import tempfile
import unittest
from pathlib import Path

SKILL_ROOT = Path(__file__).resolve().parents[1]
LIBRARY_ROOT = SKILL_ROOT / "assets" / "characters"


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


manage = load_module("cast_manage_run", SKILL_ROOT / "scripts" / "manage-run.py")
build_prompt = load_module("cast_build_prompt", SKILL_ROOT / "scripts" / "build-prompt.py")
validate_image = load_module("cast_validate_image", SKILL_ROOT / "scripts" / "validate-image.py")


def cast_member(character: str, representation: str = "physical", panels=(1,)):
    member = {"character": character, "representation": representation, "panels": list(panels)}
    if representation in {"physical", "avatar"}:
        member["staging"] = f"{character} stands in the frame"
    return member


def references_for(cast, characters):
    items = []
    for member in cast:
        if member["representation"] not in {"physical", "avatar"}:
            continue
        identifier = manage.resolve_character(member["character"], characters, "cast.character")
        entry = characters[identifier]
        items.append({
            "id": identifier,
            "path": entry["resolved_path"],
            "roles": ["identity"],
            "instruction": "Control identity only",
            "character": identifier,
        })
    return items


def lettering_reference(style=None):
    style = style or manage.DEFAULT_TEXT_STYLE
    return {
        "id": "lettering",
        "path": manage.text_style_reference(style),
        "roles": ["lettering", "typography"],
        "instruction": "Copy the lettering treatment only, never the reference wording",
    }


def lettering(payload=None, style=None, panel_count=1, speaker="gemini"):
    style = style or manage.DEFAULT_TEXT_STYLE
    if payload is None:
        payload = [{"text": f"第 {index} 格的对白", "panel": index, "speaker": speaker, "delivery": "speech"}
                   for index in range(1, panel_count + 1)]
    core = []
    for index, item in enumerate(payload):
        if isinstance(item, str):
            core.append({"index": index, "text": item, "panel": index + 1,
                         "speaker": speaker, "delivery": "caption"})
        else:
            entry = {"index": index}
            entry.update(item)
            core.append(entry)
    return {"text_style": style, "language": "zh-Hans",
            "style_reason": "plain dialogue for a one-panel scene", "core_text": core}


def image_spec(characters, cast, *, register=None, output=None, background=None, lettering_value=None,
               name="first_meeting", frame=None, panels=None, style=None, speaker=None):
    if speaker is None:
        speaker = cast[0]["character"]
        if speaker not in characters:
            speaker = "gemini"
    if register is None:
        register = {"mode": "locked", "name": "compact", "head_ratio": 4.6,
                    "acceptance_range": [4.45, 4.75], "reason": "one readable register for the whole picture"}
    frame = frame or {"mode": "whole-canvas", "panel_count": 1, "layout": "single"}
    all_panels = list(range(1, frame["panel_count"] + 1))
    for member in cast:
        if member.get("representation") != "absent" and member.get("panels") == [1]:
            member["panels"] = list(all_panels)
    if panels is None:
        panels = [{"panel": index + 1, "shot": "medium group shot",
                   "action": "they react to the same event",
                   "expression": "as the beat requires"}
                  for index in range(frame["panel_count"])]
    references = references_for(cast, characters)
    references.append(lettering_reference(style))
    return {
        "name": name,
        "framing": "waist-up three-quarter view, the group fills the frame",
        "shot": "medium group shot",
        "subject": "the declared cast sharing one moment",
        "action": "they react to the same event",
        "comic": frame,
        "panels": panels,
        "lettering": lettering(lettering_value, style, frame["panel_count"], speaker),
        "cast": cast,
        "art": {"preset": "manga", "register": register, "style": {"mode": "preset"}},
        "background": background or {"mode": "solid", "description": "flat ivory studio backdrop", "color": "#F5EADD"},
        "references": references,
        "output": output or {"format": "png", "aspect_ratio": "1:1", "alpha": False,
                             "resolution": {"mode": "provider-native", "width": None, "height": None}},
    }


class AssignmentTestCase(unittest.TestCase):
    def setUp(self):
        self.characters = manage.load_registry()
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)

    def assignment(self, images, *, run_name="studio-contract", confirmation=None):
        return {
            "schema_version": manage.ASSIGNMENT_SCHEMA_VERSION,
            "confirmation": confirmation or {"confirmed": True, "confirmed_at": "2026-01-01T00:00:00Z"},
            "run_name": run_name,
            "image_count": len(images),
            "input": {"kind": "material", "text": "the team argues about a release date", "language": "zh-Hans"},
            "images": images,
            "execution": {"mode": "sequential", "requested_parallelism": 1,
                          "max_parallelism": manage.MAX_PARALLELISM, "commit_strategy": "coordinator-serial"},
            "budget": {"per_image_candidates": 8, "per_provider_candidates": 3,
                       "run_candidates": len(images) * 8, "confirmed_over_24": len(images) * 8 > 24},
            "output_dir": str(self.root / run_name),
        }

    def write(self, value, name=None):
        path = self.root / (name or f"{value.get('run_name', 'assignment')}.json")
        path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
        return path

    def validate(self, value):
        return manage.validate_assignment(self.write(value))


class CastContractTests(AssignmentTestCase):
    def test_brief_material_and_multi_cast_are_accepted(self):
        cast = [cast_member("gemini"), cast_member("chatgpt"), cast_member("claude")]
        frozen = self.validate(self.assignment([image_spec(self.characters, cast)]))
        self.assertEqual([item["id"] for item in frozen["images"]], ["first_meeting"])
        self.assertEqual([item["character"] for item in frozen["images"][0]["cast"]],
                         ["c01", "c02", "c05"])
        self.assertEqual(len(frozen["images"][0]["references"]), 4)

    def test_unconfirmed_assignment_is_rejected(self):
        value = self.assignment([image_spec(self.characters, [cast_member("gemini")])],
                                confirmation={"confirmed": False, "confirmed_at": "2026-01-01T00:00:00Z"})
        with self.assertRaisesRegex(manage.RunError, "must be true"):
            self.validate(value)

    def test_display_name_and_alias_resolve_to_the_same_character(self):
        cast = [cast_member("gpt"), cast_member("Gemini")]
        frozen = self.validate(self.assignment([image_spec(self.characters, cast)]))
        self.assertEqual([item["character"] for item in frozen["images"][0]["cast"]], ["c02", "c01"])

    def test_unregistered_character_is_rejected(self):
        cast = [cast_member("deepseek")]
        with self.assertRaisesRegex(manage.RunError, "unregistered character"):
            self.validate(self.assignment([image_spec(self.characters, cast)]))

    def test_cast_ceiling_is_enforced(self):
        cast = [cast_member(item) for item in ("c01", "c02", "c03", "c04", "c05", "c06", "c07")]
        with self.assertRaisesRegex(manage.RunError, "at most 6 characters"):
            self.validate(self.assignment([image_spec(self.characters, cast)]))

    def test_in_frame_character_without_reference_is_rejected(self):
        cast = [cast_member("gemini")]
        image = image_spec(self.characters, cast)
        image["references"] = []
        with self.assertRaisesRegex(manage.RunError, "loads no reference"):
            self.validate(self.assignment([image]))

    def test_reference_for_an_absent_character_is_rejected(self):
        cast = [cast_member("gemini"), cast_member("claude", representation="absent", panels=())]
        image = image_spec(self.characters, cast)
        entry = self.characters["c05"]
        image["references"].append({"id": "c05", "path": entry["resolved_path"], "roles": ["identity"],
                                    "instruction": "Control identity only", "character": "c05"})
        with self.assertRaisesRegex(manage.RunError, "not in frame"):
            self.validate(self.assignment([image]))

    def test_reference_must_be_the_registered_sheet(self):
        cast = [cast_member("gemini")]
        image = image_spec(self.characters, cast)
        other = self.characters["c02"]["resolved_path"]
        image["references"][0]["path"] = other
        with self.assertRaisesRegex(manage.RunError, "registered sheet"):
            self.validate(self.assignment([image]))

    def test_reference_id_must_be_the_character_id(self):
        cast = [cast_member("gemini")]
        image = image_spec(self.characters, cast)
        image["references"][0]["id"] = "star"
        with self.assertRaisesRegex(manage.RunError, "must be c01"):
            self.validate(self.assignment([image]))

    def test_duplicate_character_in_cast_is_rejected(self):
        cast = [cast_member("gemini"), cast_member("Gemini")]
        with self.assertRaisesRegex(manage.RunError, "twice"):
            self.validate(self.assignment([image_spec(self.characters, cast)]))

    def test_absent_member_may_not_claim_panels(self):
        cast = [cast_member("gemini"), cast_member("claude", representation="absent", panels=(2,))]
        with self.assertRaisesRegex(manage.RunError, "must not claim panels"):
            self.validate(self.assignment([image_spec(self.characters, cast)]))

    def test_whale_chan_can_be_included_as_an_ordinary_character(self):
        cast = [cast_member("whalechan"), cast_member("gemini")]
        frozen = self.validate(self.assignment([image_spec(self.characters, cast)]))
        self.assertIn("whalechan", [item["character"] for item in frozen["images"][0]["cast"]])

    def test_whale_chan_is_not_inserted_when_not_declared(self):
        cast = [cast_member("gemini"), cast_member("kimi")]
        frozen = self.validate(self.assignment([image_spec(self.characters, cast)]))
        self.assertNotIn("whalechan", [item["character"] for item in frozen["images"][0]["cast"]])


class RegisterContractTests(AssignmentTestCase):
    def test_locked_register_below_its_band_is_rejected(self):
        register = {"mode": "locked", "name": "mature", "head_ratio": 3.0,
                    "acceptance_range": [2.85, 3.15], "reason": "x"}
        with self.assertRaisesRegex(manage.RunError, "must sit inside the mature band"):
            self.validate(self.assignment([image_spec(self.characters, [cast_member("gemini")], register=register)]))

    def test_locked_range_must_straddle_the_ratio(self):
        register = {"mode": "locked", "name": "compact", "head_ratio": 4.6,
                    "acceptance_range": [4.0, 4.4], "reason": "x"}
        with self.assertRaisesRegex(manage.RunError, "must contain head_ratio"):
            self.validate(self.assignment([image_spec(self.characters, [cast_member("gemini")], register=register)]))

    def test_follow_cast_uses_the_named_character_register(self):
        cast = [cast_member("c01"), cast_member("c02")]
        frozen = self.validate(self.assignment(
            [image_spec(self.characters, cast, register={"mode": "follow_cast", "of": "c01"})]))
        registers = {item["id"]: item for item in frozen["images"][0]["registers"]}
        self.assertEqual(registers["c01"]["register"], "compact")
        self.assertEqual(registers["c02"]["register"], "compact")
        self.assertIn("adult", registers["c02"]["scale_instruction"])

    def test_mixed_register_keeps_each_member_own_scale(self):
        cast = [cast_member("whalechan"), cast_member("c02")]
        register = {"mode": "mixed", "members": {"whalechan": "chibi", "c02": "mature"},
                    "relative_height": "the mature character is not shorter than the chibi one"}
        frozen = self.validate(self.assignment([image_spec(self.characters, cast, register=register)]))
        registers = {item["id"]: item["register"] for item in frozen["images"][0]["registers"]}
        self.assertEqual(registers, {"whalechan": "chibi", "c02": "mature"})

    def test_mixed_register_requires_a_known_band(self):
        register = {"mode": "mixed", "members": {"c01": "tiny"}, "relative_height": "x"}
        with self.assertRaisesRegex(manage.RunError, "must be one of"):
            self.validate(self.assignment([image_spec(self.characters, [cast_member("c01")], register=register)]))

    def test_unknown_art_preset_is_rejected(self):
        image = image_spec(self.characters, [cast_member("c01")])
        image["art"]["preset"] = "three-d-render"
        with self.assertRaisesRegex(manage.RunError, "preset must be one of"):
            self.validate(self.assignment([image]))


class OutputAndBudgetTests(AssignmentTestCase):
    def test_transparent_background_requires_alpha(self):
        cast = [cast_member("gemini")]
        background = {"mode": "transparent", "description": "cut-out on nothing"}
        with self.assertRaisesRegex(manage.RunError, "must set output.alpha true"):
            self.validate(self.assignment([image_spec(self.characters, cast, background=background)]))

    def test_alpha_without_a_transparent_background_is_rejected(self):
        cast = [cast_member("gemini")]
        output = {"format": "png", "aspect_ratio": "1:1", "alpha": True,
                  "resolution": {"mode": "provider-native", "width": None, "height": None}}
        with self.assertRaisesRegex(manage.RunError, "without a transparent background"):
            self.validate(self.assignment([image_spec(self.characters, cast, output=output)]))

    def test_aspect_ratio_must_be_canonical(self):
        cast = [cast_member("gemini")]
        output = {"format": "png", "aspect_ratio": "16:9 upscaled", "alpha": False,
                  "resolution": {"mode": "provider-native", "width": None, "height": None}}
        with self.assertRaisesRegex(manage.RunError, "positive integers as W:H"):
            self.validate(self.assignment([image_spec(self.characters, cast, output=output)]))

    def test_exact_resolution_is_normalised(self):
        cast = [cast_member("gemini")]
        output = {"format": "png", "aspect_ratio": "4:4", "alpha": False,
                  "resolution": {"mode": "exact", "width": 2048, "height": 2048}}
        frozen = self.validate(self.assignment([image_spec(self.characters, cast, output=output)]))
        self.assertEqual(frozen["images"][0]["output"]["aspect_ratio"], "1:1")

    def test_budget_below_the_estimate_is_rejected(self):
        value = self.assignment([image_spec(self.characters, [cast_member("gemini")])])
        value["budget"]["run_candidates"] = 3
        with self.assertRaisesRegex(manage.RunError, "must cover the estimated maximum"):
            self.validate(value)

    def test_over_twenty_four_candidates_need_the_flag_and_a_note(self):
        images = [image_spec(self.characters, [cast_member("gemini")], name=f"beat_{index}") for index in range(4)]
        value = self.assignment(images, run_name="over-budget")
        self.assertEqual(value["budget"]["run_candidates"], 32)
        value["budget"]["confirmed_over_24"] = False
        with self.assertRaisesRegex(manage.RunError, "confirmed_over_24 must be true"):
            self.validate(value)
        value["budget"]["confirmed_over_24"] = True
        with self.assertRaisesRegex(manage.RunError, "needs an approval_note"):
            self.validate(value)
        value["budget"]["approval_note"] = "the user confirmed four beat images at full candidate depth"
        frozen = self.validate(value)
        self.assertEqual(frozen["budget"]["estimated_maximum"], 32)
        self.assertTrue(frozen["budget"]["confirmed_over_24"])

    def test_a_small_run_needs_no_over_24_flag(self):
        value = self.assignment([image_spec(self.characters, [cast_member("gemini")])], run_name="small-run-deep")
        value["budget"]["run_candidates"] = 32
        value["budget"]["confirmed_over_24"] = True
        with self.assertRaisesRegex(manage.RunError, "confirmed_over_24 must be false"):
            self.validate(value)
        frozen = self.validate(self.assignment([image_spec(self.characters, [cast_member("gemini")])],
                                               run_name="small-run-ok"))
        self.assertEqual(frozen["budget"]["estimated_maximum"], 8)
        self.assertFalse(frozen["budget"]["confirmed_over_24"])

    def test_art_contract_is_flattened_for_the_prompt(self):
        frozen = self.validate(self.assignment([image_spec(self.characters, [cast_member("gemini")])]))
        art = frozen["images"][0]["art"]
        self.assertIn("line", art)
        self.assertIn("finish", art)
        self.assertEqual(art["style"]["name"], "manga")
        self.assertEqual(art["register"]["name"], "compact")


class RunStateTests(AssignmentTestCase):
    def initialise(self, images, run_name="studio-run"):
        value = self.assignment(images, run_name=run_name)
        path = self.write(value)
        frozen = manage.validate_assignment(path)
        result = manage.initialise_run(frozen, path, None)
        return value, frozen, result

    def test_init_freezes_references_and_manifest(self):
        cast = [cast_member("gemini"), cast_member("chatgpt")]
        _value, frozen, result = self.initialise(images=[] or [image_spec(self.characters, cast)])
        run_dir = Path(result["run_dir"])
        self.assertTrue((run_dir / "manifest.json").is_file())
        manifest = json.loads((run_dir / "manifest.json").read_text(encoding="utf-8"))
        self.assertEqual(manifest["status"], "in_progress")
        self.assertEqual(manifest["candidate_count"], 0)
        frozen_reference = frozen["images"][0]["references"][0]["path"]
        self.assertTrue(Path(frozen_reference).is_file())
        inputs = list((run_dir / "inputs" / "references").glob("*"))
        self.assertEqual(len(inputs), 3)

    def test_second_init_on_the_same_directory_is_rejected(self):
        cast = [cast_member("gemini")]
        _value, frozen, result = self.initialise(images=[image_spec(self.characters, cast)], run_name="twice")
        path = self.write(_value, name="again.json")
        with self.assertRaisesRegex(manage.RunError, "already exists"):
            manage.initialise_run(manage.validate_assignment(path), path, None)

    def test_editing_the_frozen_assignment_is_detected(self):
        cast = [cast_member("gemini")]
        value, _frozen, result = self.initialise(images=[image_spec(self.characters, cast)], run_name="tamper")
        run_dir = Path(result["run_dir"])
        assignment_path = run_dir / "assignment.json"
        tampered = json.loads(assignment_path.read_text(encoding="utf-8"))
        tampered["run_name"] = "tamper-renamed"
        assignment_path.write_text(json.dumps(tampered, ensure_ascii=False), encoding="utf-8")
        with self.assertRaisesRegex(manage.RunError, "modified after initialization"):
            manage.load_run(run_dir)

    def test_unknown_image_id_is_reported_with_the_frozen_list(self):
        cast = [cast_member("gemini")]
        _value, _frozen, result = self.initialise(images=[image_spec(self.characters, cast)], run_name="listing")
        run_dir = Path(result["run_dir"])
        with self.assertRaisesRegex(manage.RunError, "frozen images: first_meeting"):
            manage.load_run(run_dir)
            manage.image_spec(json.loads((run_dir / "assignment.json").read_text(encoding="utf-8")), "missing")

    def test_status_reports_register_per_image(self):
        from types import SimpleNamespace

        cast = [cast_member("gemini"), cast_member("c02")]
        _value, _frozen, result = self.initialise(images=[image_spec(self.characters, cast)], run_name="report")
        summary = manage.status(SimpleNamespace(run_dir=result["run_dir"]))
        self.assertEqual(summary["images"]["first_meeting"]["registers"], ["Gemini=compact", "ChatGPT=compact"])


class PromptTests(AssignmentTestCase):
    def build(self, image, characters=None, **assignment_kwargs):
        value = self.assignment([image], **assignment_kwargs)
        frozen = self.validate(value)
        return build_prompt.build_prompt(frozen, frozen["images"][0], self.root), frozen

    def test_prompt_carries_identity_blocks_and_shared_art_contract(self):
        cast = [cast_member("gemini"), cast_member("chatgpt")]
        prompt, _frozen = self.build(image_spec(self.characters, cast))
        self.assertIn(self.characters["c01"]["prompt_block"], prompt)
        self.assertIn(self.characters["c02"]["prompt_block"], prompt)
        self.assertIn("ART CONTRACT", prompt)
        self.assertIn("Draw all characters with the same line weight", prompt)
        self.assertIn("register: compact", prompt)
        self.assertIn("never:", prompt)

    def test_prompt_never_inserts_an_undeclared_character(self):
        cast = [cast_member("gemini"), cast_member("kimi")]
        prompt, _frozen = self.build(image_spec(self.characters, cast))
        self.assertNotIn("REGISTERED CHARACTER c02 (ChatGPT", prompt)
        self.assertNotIn("REGISTERED CHARACTER whalechan", prompt)
        self.assertIn("Whale-chan is not assumed", prompt)

    def test_prompt_reproduces_the_exact_lettering(self):
        cast = [cast_member("gemini")]
        lines = [{"text": "又鸽了", "panel": 1, "speaker": "gemini", "delivery": "speech"}]
        prompt, _frozen = self.build(image_spec(self.characters, cast, lettering_value=lines))
        self.assertIn("又鸽了", prompt)
        self.assertIn("character for character", prompt)
        self.assertIn("LETTERING", prompt)
        self.assertIn("speaker=c01", prompt)

    def test_prompt_carries_the_panel_layout_and_the_lettering_treatment(self):
        cast = [cast_member("gemini"), cast_member("claude")]
        frame = {"mode": "whole-canvas", "panel_count": 2, "layout": "top-bottom"}
        panels = [
            {"panel": 1, "shot": "wide establishing shot", "action": "they size each other up",
             "expression": "guarded", "transition": "the mood turns"},
            {"panel": 2, "shot": "close-up", "action": "she slams the desk",
             "expression": "furious", "props": ["a cracked mug"]},
        ]
        lines = [{"text": "你敢？", "panel": 1, "speaker": "gemini", "delivery": "speech"},
                 {"text": "砰！", "panel": 2, "speaker": "device", "delivery": "sfx"}]
        prompt, _frozen = self.build(
            image_spec(self.characters, cast, frame=frame, panels=panels, lettering_value=lines)
        )
        self.assertIn("PANEL LAYOUT: exactly 2 panels", prompt)
        self.assertIn("arranged as top-bottom", prompt)
        self.assertIn("Panel 2 (shot close-up): she slams the desk", prompt)
        self.assertIn("props: a cracked mug", prompt)
        self.assertIn("panel 2 | sfx | speaker=device: 砰！", prompt)
        self.assertIn("balloon whose tail points at the mouth", prompt)
        self.assertIn(manage.text_style_fragment(manage.DEFAULT_TEXT_STYLE), prompt)

    def test_prompt_states_the_frozen_register_and_reference_roles(self):
        cast = [cast_member("gemini"), cast_member("c02")]
        prompt, _frozen = self.build(image_spec(self.characters, cast))
        self.assertIn("about 4.6 heads tall", prompt)
        self.assertIn("roles: identity", prompt)
        self.assertIn("roles: lettering, typography", prompt)
        self.assertIn("redraw", prompt.lower())

    def test_build_prompt_cli_refuses_to_overwrite(self):
        cast = [cast_member("gemini")]
        image = image_spec(self.characters, cast)
        value = self.assignment([image], run_name="cli-refuse")
        path = self.write(value, name="cli.json")
        frozen = manage.validate_assignment(path)
        result = manage.initialise_run(frozen, path, None)
        run_dir = Path(result["run_dir"])
        target = run_dir / "prompt-01.txt"
        target.write_text("existing", encoding="utf-8")
        prompt = build_prompt.build_prompt(frozen, frozen["images"][0], run_dir)
        self.assertEqual(target.read_text(encoding="utf-8"), "existing")
        self.assertIn("IDENTITY", prompt)


class ComicContractTests(AssignmentTestCase):
    """The manga contract: panels, exact lettering and one shared treatment."""

    def frozen(self, image):
        return self.validate(self.assignment([image]))["images"][0]

    def test_two_panel_page_freezes_its_panels_and_lettering(self):
        cast = [cast_member("gemini"), cast_member("claude")]
        frame = {"mode": "whole-canvas", "panel_count": 2, "layout": "top-bottom"}
        panels = [{"panel": 1, "shot": "wide", "action": "they square up"},
                  {"panel": 2, "shot": "close", "action": "she folds her arms"}]
        lines = [{"text": "开始吧", "panel": 1, "speaker": "gemini", "delivery": "speech"},
                 {"text": "你先把图交了", "panel": 2, "speaker": "claude", "delivery": "speech"}]
        frozen = self.frozen(image_spec(self.characters, cast, frame=frame, panels=panels,
                                        lettering_value=lines))
        self.assertEqual(frozen["comic"]["panel_count"], 2)
        self.assertEqual([panel["panel"] for panel in frozen["panels"]], [1, 2])
        self.assertEqual([line["speaker"] for line in frozen["lettering"]["core_text"]], ["c01", "c05"])

    def test_panel_count_must_match_the_layout(self):
        cast = [cast_member("gemini")]
        frame = {"mode": "whole-canvas", "panel_count": 3, "layout": "top-bottom"}
        with self.assertRaisesRegex(manage.RunError, "needs panel_count 2"):
            self.frozen(image_spec(self.characters, cast, frame=frame))

    def test_panels_list_must_match_the_frozen_count(self):
        cast = [cast_member("gemini")]
        frame = {"mode": "whole-canvas", "panel_count": 2, "layout": "left-right"}
        panels = [{"panel": 1, "shot": "wide", "action": "one beat only"}]
        with self.assertRaisesRegex(manage.RunError, "must hold exactly 2 panels"):
            self.frozen(image_spec(self.characters, cast, frame=frame, panels=panels))

    def test_every_panel_must_carry_text(self):
        cast = [cast_member("gemini")]
        frame = {"mode": "whole-canvas", "panel_count": 2, "layout": "top-bottom"}
        lines = [{"text": "只有第一格有字", "panel": 1, "speaker": "gemini", "delivery": "speech"}]
        with self.assertRaisesRegex(manage.RunError, "gives no text to panel"):
            self.frozen(image_spec(self.characters, cast, frame=frame, lettering_value=lines))

    def test_line_may_not_name_an_undeclared_speaker(self):
        cast = [cast_member("gemini")]
        lines = [{"text": "谁在说话", "panel": 1, "speaker": "kimi", "delivery": "speech"}]
        with self.assertRaisesRegex(manage.RunError, "neither a character in this image's cast"):
            self.frozen(image_spec(self.characters, cast, lettering_value=lines))

    def test_a_speaker_must_be_placed_in_that_panel(self):
        cast = [cast_member("gemini"), cast_member("claude")]
        frame = {"mode": "whole-canvas", "panel_count": 2, "layout": "top-bottom"}
        panels = [{"panel": 1, "shot": "wide", "action": "one beat"},
                  {"panel": 2, "shot": "close", "action": "another beat"}]
        lines = [{"text": "第一格", "panel": 1, "speaker": "gemini", "delivery": "speech"},
                 {"text": "我也在第一格", "panel": 1, "speaker": "claude", "delivery": "speech"}]
        image = image_spec(self.characters, cast, frame=frame, panels=panels, lettering_value=lines)
        for member in image["cast"]:
            if member["character"] == "claude":
                member["panels"] = [2]
        with self.assertRaisesRegex(manage.RunError, "does not place that character in panel 1"):
            self.frozen(image)

    def test_line_may_not_point_outside_the_layout(self):
        cast = [cast_member("gemini")]
        lines = [{"text": "跑出画格了", "panel": 4, "speaker": "gemini", "delivery": "speech"}]
        with self.assertRaisesRegex(manage.RunError, "outside the frozen 1-panel layout"):
            self.frozen(image_spec(self.characters, cast, lettering_value=lines))

    def test_lettering_reference_must_be_the_declared_template(self):
        cast = [cast_member("gemini")]
        image = image_spec(self.characters, cast)
        image["references"][-1] = lettering_reference("04_caption-box")
        with self.assertRaisesRegex(manage.RunError, "must be the registered template of"):
            self.frozen(image)

    def test_lettering_reference_is_required(self):
        cast = [cast_member("gemini")]
        image = image_spec(self.characters, cast)
        image["references"] = [item for item in image["references"] if "lettering" not in item["roles"]]
        with self.assertRaisesRegex(manage.RunError, "must load exactly one lettering reference"):
            self.frozen(image)

    def test_comic_block_is_required(self):
        cast = [cast_member("gemini")]
        image = image_spec(self.characters, cast)
        del image["comic"]
        with self.assertRaisesRegex(manage.RunError, r"\.comic is required"):
            self.frozen(image)

    def test_prompt_states_the_shared_hand_for_every_panel(self):
        cast = [cast_member("gemini")]
        prompt, _frozen = self.build_prompt_for(image_spec(self.characters, cast))
        self.assertIn("Every panel of this page is drawn by the same hand", prompt)
        self.assertIn("PRESET", prompt.upper())

    def build_prompt_for(self, image, **assignment_kwargs):
        value = self.assignment([image], **assignment_kwargs)
        frozen = self.validate(value)
        return build_prompt.build_prompt(frozen, frozen["images"][0], self.root), frozen

    def test_two_panel_page_says_it_is_one_picture(self):
        cast = [cast_member("gemini")]
        frame = {"mode": "whole-canvas", "panel_count": 2, "layout": "top-bottom"}
        lines = [{"text": "上", "panel": 1, "speaker": "gemini", "delivery": "speech"},
                 {"text": "下", "panel": 2, "speaker": "gemini", "delivery": "speech"}]
        prompt, _frozen = self.build_prompt_for(
            image_spec(self.characters, cast, frame=frame, lettering_value=lines)
        )
        self.assertIn("One comic page holding all 2 panels at once", prompt)
        self.assertIn("Do not return separate pictures", prompt)


class AutomaticGateTests(AssignmentTestCase):
    def render(self, path: Path, size=(1024, 1024), colour=(245, 234, 221), corners=None, mode="RGB"):
        from PIL import Image, ImageDraw

        image = Image.new(mode, size, colour)
        draw = ImageDraw.Draw(image)
        draw.ellipse((size[0] // 4, size[1] // 6, size[0] * 3 // 4, size[1] * 5 // 6), fill=(30, 40, 90))
        if corners is not None:
            draw.rectangle((0, 0, size[0], size[1]), outline=corners, width=8)
        image.save(path)
        return path

    def frozen_image(self, **image_kwargs):
        image = image_spec(self.characters, [cast_member("gemini")], **image_kwargs)
        frozen = self.validate(self.assignment([image]))
        return frozen["images"][0]

    def test_matching_candidate_passes_the_automatic_gates(self):
        spec = self.frozen_image()
        candidate = self.render(self.root / "ok.png", corners=(245, 234, 221))
        record = validate_image.inspect(candidate, spec)
        self.assertEqual(record["verdict"], "PASS")
        self.assertEqual(record["identity_required_elements"], "NOT-CHECKED")
        self.assertIn("style_consistency", record["not_machine_verifiable"])

    def test_wrong_aspect_ratio_fails_geometry(self):
        spec = self.frozen_image()
        candidate = self.render(self.root / "wide.png", size=(1280, 720))
        record = validate_image.inspect(candidate, spec)
        self.assertEqual(record["verdict"], "FAIL")
        self.assertEqual(record["geometry"], "FAIL")

    def test_alpha_without_transparency_fails(self):
        spec = self.frozen_image()
        candidate = self.render(self.root / "alpha.png", mode="RGBA")
        record = validate_image.inspect(candidate, spec)
        self.assertEqual(record["alpha_policy"], "FAIL")

    def test_exact_resolution_mismatch_fails(self):
        output = {"format": "png", "aspect_ratio": "1:1", "alpha": False,
                  "resolution": {"mode": "exact", "width": 2048, "height": 2048}}
        spec = self.frozen_image(output=output)
        candidate = self.render(self.root / "small.png")
        record = validate_image.inspect(candidate, spec)
        self.assertEqual(record["geometry"], "FAIL")
        self.assertIn("2048x2048", " ".join(record["notes"]))

    def test_validate_composite_reports_background_and_injection(self):
        composite = load_module("cast_validate_composite", SKILL_ROOT / "scripts" / "validate-composite.py")
        from PIL import Image

        spec = self.frozen_image()
        candidate = self.render(self.root / "composite.png", corners=(245, 234, 221))
        record = composite.validate_image.inspect(candidate, spec)
        with Image.open(candidate) as handle:
            background = composite.background_metrics(handle, "solid", (245, 234, 221))
        self.assertTrue(background["uniform"])
        self.assertTrue(background["matches_expected"])
        self.assertEqual(record["identity_required_elements"], "NOT-CHECKED")
        self.assertIn("style_consistency", record["not_machine_verifiable"])
        self.assertIn("geometry", record["machine_verified_only"])

    def test_wrong_background_colour_is_failed_by_the_composite_gate(self):
        composite = load_module("cast_validate_composite", SKILL_ROOT / "scripts" / "validate-composite.py")
        from PIL import Image

        spec = self.frozen_image()
        candidate = self.render(self.root / "grey.png", colour=(200, 200, 200), corners=(200, 200, 200))
        with Image.open(candidate) as handle:
            background = composite.background_metrics(handle, "solid", (245, 234, 221))
        self.assertFalse(background["matches_expected"])
        self.assertGreater(background["distance_to_expected"], composite.BACKGROUND_TOLERANCE)


class ReviewContractTests(unittest.TestCase):
    def test_style_gate_cannot_pass_without_a_note(self):
        review = {"verdict": "PASS", "candidate_sha256": "a" * 64,
                  "gates": {gate: "PASS" for gate in manage.REQUIRED_REVIEW_GATES}, "defects": []}
        with self.assertRaisesRegex(manage.RunError, "style_consistency_note"):
            manage.validate_review(review, {}, "review")

    def test_style_gate_with_a_note_is_accepted(self):
        review = {"verdict": "PASS", "candidate_sha256": "a" * 64,
                  "gates": {gate: "PASS" for gate in manage.REQUIRED_REVIEW_GATES}, "defects": [],
                  "style_consistency_note": "compared line weight, shading steps and palette across all four figures"}
        manage.validate_review(review, {}, "review")

    def test_a_failed_gate_blocks_a_pass_verdict(self):
        gates = {gate: "PASS" for gate in manage.REQUIRED_REVIEW_GATES}
        gates["cast_accuracy"] = "FAIL"
        review = {"verdict": "PASS", "candidate_sha256": "a" * 64, "gates": gates, "defects": ["wrong hair"],
                  "style_consistency_note": "compared line weight, shading steps and palette across the whole cast"}
        with self.assertRaisesRegex(manage.RunError, "not: cast_accuracy"):
            manage.validate_review(review, {}, "review")

    def test_unknown_gate_is_rejected(self):
        gates = {gate: "PASS" for gate in manage.REQUIRED_REVIEW_GATES}
        gates["vibes"] = "PASS"
        review = {"verdict": "FAIL", "candidate_sha256": "a" * 64, "gates": gates, "defects": []}
        with self.assertRaisesRegex(manage.RunError, "unknown gates"):
            manage.validate_review(review, {}, "review")


class RegistryTests(unittest.TestCase):
    def test_registry_and_sheets_are_self_consistent(self):
        entries = manage.load_registry()
        self.assertEqual(len(entries), 8)
        for identifier, entry in entries.items():
            path = Path(entry["resolved_path"])
            self.assertTrue(path.is_file(), identifier)
            self.assertEqual(manage.sha256(path), entry["asset"]["sha256"])
            self.assertTrue(entry["prompt_block"].startswith(f"REGISTERED CHARACTER {identifier} ("))
            self.assertTrue(entry["negative"].strip())
            low, high = manage.REGISTER_BANDS[entry["register"]]
            self.assertTrue(low <= entry["drawn_ratio"] <= high, identifier)

    def test_every_character_can_be_resolved_by_name(self):
        entries = manage.load_registry()
        for entry in entries.values():
            for token in [entry["display_name"], *entry["aliases"]]:
                self.assertEqual(manage.resolve_character(token, entries, "token"), entry["id"])

    def test_id_wins_over_another_characters_alias(self):
        entries = copy.deepcopy(manage.load_registry())
        entries["c02"]["aliases"] = list(entries["c02"]["aliases"]) + ["c01"]
        self.assertEqual(manage.resolve_character("c01", entries, "token"), "c01")

    def test_ambiguous_lookup_key_is_rejected(self):
        value = json.loads(Path(manage.REGISTRY_PATH).read_text(encoding="utf-8"))
        entry = next(item for item in value["characters"] if item["id"] == "c02")
        entry["aliases"] = list(entry["aliases"]) + ["双星"]
        with tempfile.TemporaryDirectory() as temporary:
            broken = Path(temporary) / "character-registry.json"
            broken.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
            original = manage.REGISTRY_PATH
            manage.REGISTRY_PATH = broken
            try:
                with self.assertRaisesRegex(manage.RunError, "ambiguous lookup key"):
                    manage.load_registry()
            finally:
                manage.REGISTRY_PATH = original


if __name__ == "__main__":
    unittest.main(verbosity=2)
