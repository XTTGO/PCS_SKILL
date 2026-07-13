#!/usr/bin/env python3
"""Compile a natural-language PCS request through the canonical Prompt Compiler.

This is an entry adapter, not a second prompt compiler.  It recognizes an
existing PCS task profile, proposes only non-empty task-relevant field control
units, and delegates prompt construction and model adaptation to
``pcs_prompt_compile.compile_request``.
"""
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any

from pcs_prompt_compile import compile_request, load_compiler_sources, meaningfully_duplicate


ROOT = Path(__file__).resolve().parents[1]


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def group_of(field_id: str) -> str:
    match = re.match(r"^([A-Z]{1,2})\d+_", field_id)
    return match.group(1) if match else ""


def is_empty(value: Any) -> bool:
    return value is None or value == "" or value == [] or value == {}


def compact_text(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip(" ,.;:")


def field_unit(
    value: Any,
    priority: str,
    *,
    state: str = "ADAPT",
    source: str = "user_input",
) -> dict[str, Any]:
    return {
        "value": value,
        "source": source,
        "state": state,
        "priority": priority,
        "adaptation_allowed": state != "LOCK",
    }


def recognize_task_type(text: str) -> str:
    """Recognize one supported task without adding a new routing taxonomy."""
    normalized = text.lower()
    if re.search(r"\b(image[ -]?to[ -]?video|animate (?:the |a )?(?:source|reference) image|animate image)\b", normalized):
        return "image_to_video"
    if re.search(r"\b(video|animation|cinematic shot|motion)\b", normalized) and re.search(
        r"\b(animate|generate|create|make|second|shot|motion|camera)\b", normalized
    ):
        return "video_generation"
    if re.search(r"\b(product|bottle|packaging|logo)\b", normalized) and re.search(
        r"\b(integrate|integration|place|put|composite|insert)\b", normalized
    ):
        return "product_integration"
    if re.search(r"\b(same character|character identity|face identity|consistent hairstyle|character consistency)\b", normalized):
        return "character_consistency_edit"
    if re.search(r"\b(subject transfer|transfer .*?(?:into|to)|move .*?(?:into|to))\b", normalized):
        return "subject_transfer"
    if re.search(r"\b(reverse prompt|image inversion|analy[sz]e (?:the |this )?(?:reference )?image|extract .*?from (?:the )?(?:reference )?image)\b", normalized):
        return "image_inversion"
    return "text_to_image"


def first_match(text: str, patterns: tuple[str, ...]) -> str:
    for pattern in patterns:
        match = re.search(pattern, text, flags=re.IGNORECASE)
        if match:
            return compact_text(match.group(1))
    return ""


def extract_subject(text: str, task_type: str) -> str:
    if task_type == "product_integration":
        product = first_match(
            text,
            (
                r"\b(?:integrate|place|put|insert)\s+(?:the\s+)?(.+?)\s+(?:from|into|in)\s+(?:reference|source)\s+image",
                r"\b(?:integrate|place|put|insert)\s+(?:the\s+)?(.+?)\s+(?:into|in)\s+",
            ),
        )
        if product:
            return product
    if task_type == "character_consistency_edit":
        return "same character identity"
    return first_match(
        text,
        (
            r"\bof\s+(?:a|an|the)\s+(.+?)(?=\s+(?:walking|standing|drifting|running|sitting|floating|in|through|on|at|with)\b|[,.;]|$)",
            r"^\s*(?:create|generate|make)\s+(?:a|an|the)\s+(.+?)(?=\s+(?:in|through|on|at|with)\b|[,.;]|$)",
        ),
    )


def extract_context(text: str, task_type: str) -> str:
    if task_type == "product_integration":
        return first_match(text, (r"\b(?:into|in)\s+(?:a|an|the)\s+(.+?)(?=[,.]|$)",))
    if task_type == "character_consistency_edit":
        return first_match(text, (r"\b(?:to|into|in)\s+(?:a|an|the)\s+(.+?)(?=[,.]|$)",))
    return first_match(
        text,
        (r"\b(?:in|through|on|at)\s+(?:a|an|the)\s+(.+?)(?=[,.]|$)",),
    )


def extract_common_fields(text: str, task_type: str) -> dict[str, dict[str, Any]]:
    fields: dict[str, dict[str, Any]] = {}

    def add(field_id: str, value: Any, priority: str, **kwargs: Any) -> None:
        if not is_empty(value):
            fields[field_id] = field_unit(value, priority, **kwargs)

    subject = extract_subject(text, task_type)
    context = extract_context(text, task_type)
    if subject:
        add("A3_identity_or_category", subject, "P0")
    if context:
        add("J1_environment_type", context, "P0")

    aspect = first_match(text, (r"\b(\d{1,2}:\d{1,2})\b",))
    if aspect:
        add("L1_aspect_ratio", aspect, "P1")
    if re.search(r"\b(centered|centre(?:d)? hero|hero composition)\b", text, flags=re.IGNORECASE):
        add("B5_composition_style", "centered hero composition", "P2")
    if re.search(r"\bmacro(?:\s+lens)?\b", text, flags=re.IGNORECASE):
        add("B7_lens_type", "macro lens", "P2")
    if re.search(r"\bsoftbox\b", text, flags=re.IGNORECASE):
        add("C3_light_style", "softbox lighting", "P2")
    if re.search(r"\bbrushed titanium\b", text, flags=re.IGNORECASE):
        add("F1_surface_texture", "brushed titanium texture", "P2")
    accent = first_match(text, (r"\b(deep blue(?:\s+accent(?:\s+color)?)?)\b",))
    if accent:
        add("D2_accent_colors", accent, "P2")
    if re.search(r"\b(cinema(?:tic)?|cinematic)\b", text, flags=re.IGNORECASE):
        add("H1_rendering_style", "cinematic", "P2")
    if re.search(r"\bluxury\b", text, flags=re.IGNORECASE):
        add("E6_aesthetic_reference", "luxury product advertising", "P3")
    if re.search(r"\bquiet\b", text, flags=re.IGNORECASE):
        add("K1_emotional_tone", "quiet", "P2")
    if re.search(r"\bdawn\b", text, flags=re.IGNORECASE):
        add("I1_time_of_day", "dawn", "P2")
    return fields


def extract_edit_fields(text: str, task_type: str, fields: dict[str, dict[str, Any]]) -> None:
    subject = extract_subject(text, task_type)
    context = extract_context(text, task_type)
    if task_type == "product_integration":
        fields.update(
            {
                "X1_edit_task_type": field_unit("product integration", "P0"),
                "X2_source_asset": field_unit(subject or "product from source image 1", "P0", state="LOCK", source="source_image_1"),
                "X3_target_context": field_unit(context or "target context", "P0", source="target_image_2"),
                "X5_preservation_level": field_unit("bottle silhouette and logo", "P0", state="LOCK", source="source_image_1"),
                "X6_adaptation_scope": field_unit("reflections and contact shadow", "P1"),
                "X7_integration_requirements": field_unit("matched perspective, reflections, and contact shadow", "P1"),
                "Y8_negative_constraints": field_unit("distorted logo, altered product silhouette", "P0"),
            }
        )
        fields["A3_identity_or_category"] = field_unit(subject or "product", "P0", state="LOCK", source="source_image_1")
        if context:
            fields["J1_environment_type"] = field_unit(context, "P0", source="target_image_2")
        return
    if task_type == "character_consistency_edit":
        identity = "same character identity and hairstyle"
        fields.update(
            {
                "X1_edit_task_type": field_unit("character consistency edit", "P0"),
                "X2_source_asset": field_unit(identity, "P0", state="LOCK", source="source_image_1"),
                "X3_target_context": field_unit(context or "target context", "P0", source="target_image_2"),
                "X5_preservation_level": field_unit("face identity, hairstyle, and body proportion", "P0", state="LOCK", source="source_image_1"),
                "X6_adaptation_scope": field_unit("background, lighting, and color", "P1"),
                "Y8_negative_constraints": field_unit("identity drift, changed face, inconsistent hairstyle", "P0"),
            }
        )
        fields["A3_identity_or_category"] = field_unit("same character identity", "P0", state="LOCK", source="source_image_1")
        if context:
            fields["J1_environment_type"] = field_unit(context, "P0", source="target_image_2")
        return
    if task_type == "subject_transfer":
        fields.update(
            {
                "X1_edit_task_type": field_unit("subject transfer", "P0"),
                "X2_source_asset": field_unit(subject or "subject from source image 1", "P0", state="LOCK", source="source_image_1"),
                "X3_target_context": field_unit(context or "target context", "P0", source="target_image_2"),
                "X5_preservation_level": field_unit("source subject identity", "P0", state="LOCK", source="source_image_1"),
                "X7_integration_requirements": field_unit("matched perspective and natural integration", "P1"),
                "Y8_negative_constraints": field_unit("identity drift, pasted-on collage look", "P0"),
            }
        )


def extract_video_fields(text: str, task_type: str, fields: dict[str, dict[str, Any]]) -> None:
    duration = first_match(text, (r"\b(\d+(?:\.\d+)?\s*(?:seconds?|secs?|s))\b",))
    motion = first_match(text, (r"\b(walking|drifting|running|floating|turning|moving)\b",))
    camera_motion = first_match(text, (r"\b(slow tracking shot|tracking shot|dolly shot|pan|tilt|orbit)\b",))
    fields["V1_video_task_type"] = field_unit(task_type.replace("_", " "), "P0")
    if duration:
        fields["V3_duration"] = field_unit(duration, "P0")
    if camera_motion:
        fields["V5_camera_motion"] = field_unit(camera_motion, "P1")
    if motion:
        fields["V6_subject_motion"] = field_unit(motion, "P1")
    if re.search(r"\bstable motion\b", text, flags=re.IGNORECASE):
        fields["V7_action_continuity"] = field_unit("stable motion", "P0")
    if re.search(r"\bno flicker\b", text, flags=re.IGNORECASE):
        fields["Y8_negative_constraints"] = field_unit("flickering", "P0")
    if task_type == "image_to_video":
        fields["X2_source_asset"] = field_unit("source image 1", "P0", state="LOCK", source="source_image_1")


def filter_fields(
    fields: dict[str, dict[str, Any]], task_type: str, rules: dict[str, Any]
) -> dict[str, dict[str, Any]]:
    profile = rules["task_profiles"][task_type]
    allowed_groups = set(profile.get("required_groups", [])) | set(profile.get("preferred_groups", [])) | set(
        profile.get("optional_groups", [])
    )
    filtered: dict[str, dict[str, Any]] = {}
    emitted_values: list[str] = []
    for field_id, unit in fields.items():
        value = unit.get("value") if isinstance(unit, dict) else None
        state = str(unit.get("state", "ADAPT")).upper() if isinstance(unit, dict) else "ADAPT"
        if group_of(field_id) not in allowed_groups or state == "IGNORE" or is_empty(value):
            continue
        value_text = " ".join(str(item) for item in value) if isinstance(value, list) else str(value)
        # X fields carry edit semantics (preserve, inherit, adapt) in addition
        # to their wording. Keep them even when an A-L field repeats part of
        # the same value; other repeated phrases are noise and are removed.
        if group_of(field_id) != "X" and any(meaningfully_duplicate(value_text, prior) for prior in emitted_values):
            continue
        filtered[field_id] = unit
        emitted_values.append(value_text)
    return filtered


def build_entry_request(
    user_input: str,
    *,
    target_model: str = "generic",
    prompt_density: str = "standard",
    field_overrides: dict[str, dict[str, Any]] | None = None,
    include_debug: bool = False,
) -> dict[str, Any]:
    """Build a canonical Prompt Compiler request from a natural-language brief."""
    if not compact_text(user_input):
        raise ValueError("user_input must contain a visual request")
    rules = load_compiler_sources()["rules"]
    task_type = recognize_task_type(user_input)
    fields = extract_common_fields(user_input, task_type)
    if task_type in {"subject_transfer", "product_integration", "character_consistency_edit"}:
        extract_edit_fields(user_input, task_type, fields)
    if task_type in {"video_generation", "image_to_video"}:
        extract_video_fields(user_input, task_type, fields)
    if task_type == "image_inversion" and "A3_identity_or_category" not in fields:
        fields["A3_identity_or_category"] = field_unit("reference image subject", "P0", source="source_image_1")
    if field_overrides:
        fields.update(field_overrides)
    return {
        "metadata": {
            "task_type": task_type,
            "target_model": target_model or "generic",
            "output_mode": "Standard",
            "prompt_density": prompt_density or "standard",
            "language_target": "English",
        },
        "fields": filter_fields(fields, task_type, rules),
        "compile_options": {
            "include_debug_segments": include_debug,
            "include_adapter_notes": include_debug,
        },
    }


def compile_user_entry(
    user_input: str,
    *,
    target_model: str = "generic",
    prompt_density: str = "standard",
    field_overrides: dict[str, dict[str, Any]] | None = None,
    include_debug: bool = False,
) -> dict[str, Any]:
    """Return the user-facing result of compiling a natural-language brief."""
    request = build_entry_request(
        user_input,
        target_model=target_model,
        prompt_density=prompt_density,
        field_overrides=field_overrides,
        include_debug=include_debug,
    )
    compiled = compile_request(request)
    adapter = load_compiler_sources()["adapters"]["adapters"][compiled["compile_metadata"]["resolved_adapter"]]
    result: dict[str, Any] = {
        "task_type": compiled["compile_metadata"]["task_type"],
        "prompt_density": compiled["compile_metadata"]["prompt_density"],
        "model_prompt": compiled["model_prompt"],
        "warnings": compiled["warnings"],
        "compile_info": {
            "target_model": compiled["compile_metadata"]["target_model"],
            "resolved_adapter": compiled["compile_metadata"]["resolved_adapter"],
            "parameter_hints": compiled["parameter_hints"],
            "used_fields": compiled["used_fields"],
            "dropped_fields": compiled["dropped_fields"],
        },
    }
    if adapter.get("negative_channel", True):
        result["negative_prompt"] = compiled["negative_prompt"]
    if include_debug:
        result["debug_segments"] = compiled["debug_segments"]
        result["compile_info"]["adapter_notes"] = compiled["adapter_notes"]
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description="Compile a natural-language visual brief through PCS")
    parser.add_argument("user_input", help="Natural-language visual request")
    parser.add_argument("--target-model", default="generic")
    parser.add_argument("--prompt-density", default="standard")
    parser.add_argument("--debug", action="store_true")
    args = parser.parse_args()
    try:
        print(
            json.dumps(
                compile_user_entry(
                    args.user_input,
                    target_model=args.target_model,
                    prompt_density=args.prompt_density,
                    include_debug=args.debug,
                ),
                ensure_ascii=False,
                indent=2,
            )
        )
        return 0
    except Exception as exc:  # noqa: BLE001
        print(f"PCS user entry compiler failed: {exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
