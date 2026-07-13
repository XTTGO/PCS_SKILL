#!/usr/bin/env python3
"""PCS Prompt Compiler reference implementation 0.2.0.

This script is intentionally transparent and dependency-free. It compiles PCS
field-control JSON into:
- positive_prompt
- negative_prompt
- model_prompt
- adapter_notes / parameter_hints
- used_fields / dropped_fields / warnings / debug_segments

Usage:
  python tools/pcs_prompt_compile.py INPUT.json
  python tools/pcs_prompt_compile.py INPUT.json --output RESULT.json
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
RUNTIME_EXPORT_REL = Path("references") / "pcs-core-skill-runtime.json"
RULES_PATH = ROOT / "07_OUTPUT_TEMPLATE" / "Output_Compile_Rules.json"
MAPPING_PATH = ROOT / "07_OUTPUT_TEMPLATE" / "Field_Phrase_Mapping.json"
ADAPTERS_PATH = ROOT / "08_MODEL_ADAPTER" / "Model_Prompt_Adapters.json"
FRAGMENTS_PATH = ROOT / "07_OUTPUT_TEMPLATE" / "Prompt_Fragment_Library.json"
AE_LIBRARY_PATH = ROOT / "10_AESTHETICS" / "Aesthetic_Principle_Library.json"
AE_PROTOCOL_PATH = ROOT / "10_AESTHETICS" / "Aesthetic_Review_Protocol.json"
FIELD_ID_RE = re.compile(r"^[A-Z]{1,2}\d+_[a-z0-9_]+$")


def load_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8-sig") as f:
        return json.load(f)


def runtime_export_path() -> Path | None:
    """Return the packaged Core snapshot when this script runs inside a Skill."""
    candidate = ROOT / RUNTIME_EXPORT_REL
    return candidate if candidate.exists() else None


def load_compiler_sources(runtime_export: Path | None = None) -> dict[str, Any]:
    """Load compiler facts from the packaged export, or Core in development mode."""
    export_path = runtime_export or runtime_export_path()
    if export_path is None:
        return {
            "rules": load_json(RULES_PATH),
            "mapping": load_json(MAPPING_PATH),
            "adapters": load_json(ADAPTERS_PATH),
            "fragments": load_json(FRAGMENTS_PATH),
            "aesthetic_library": load_json(AE_LIBRARY_PATH) if AE_LIBRARY_PATH.exists() else None,
            "aesthetic_protocol": load_json(AE_PROTOCOL_PATH) if AE_PROTOCOL_PATH.exists() else None,
        }
    package = load_json(export_path)
    if package.get("profile") != "skill-runtime":
        raise ValueError(f"Expected skill-runtime export, got {package.get('profile')!r}")
    mappings = package.get("compiler_mappings", {})
    aesthetic = package.get("aesthetic_knowledge", {})
    return {
        "rules": mappings["output_compile_rules"],
        "mapping": mappings["field_phrase_mapping"],
        "adapters": package["model_adapters"],
        "fragments": mappings["prompt_fragment_library"],
        "aesthetic_library": aesthetic.get("principle_library"),
        "aesthetic_protocol": aesthetic.get("review_protocol"),
    }


def dump_json(data: dict[str, Any]) -> str:
    return json.dumps(data, ensure_ascii=False, indent=2) + "\n"


def flatten_fields(node: Any, out: dict[str, dict[str, Any]] | None = None) -> dict[str, dict[str, Any]]:
    """Find PCS field control units in flat or nested JSON."""
    if out is None:
        out = {}
    if isinstance(node, dict):
        for key, value in node.items():
            if FIELD_ID_RE.match(str(key)):
                if isinstance(value, dict) and "value" in value:
                    out[str(key)] = dict(value)
                else:
                    out[str(key)] = {"value": value}
            else:
                flatten_fields(value, out)
    elif isinstance(node, list):
        for value in node:
            flatten_fields(value, out)
    return out


def empty(value: Any) -> bool:
    return value is None or value == "" or value == [] or value == {}


def value_to_items(value: Any) -> list[str]:
    if empty(value):
        return []
    if isinstance(value, list):
        items: list[str] = []
        for item in value:
            items.extend(value_to_items(item))
        return items
    if isinstance(value, dict):
        items = []
        for k, v in value.items():
            if not empty(v):
                items.append(f"{k}: {v}")
        return items
    return [str(value).strip()]


def unique(items: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for item in items:
        normalized = re.sub(r"\s+", " ", item.strip().lower().rstrip(".,;"))
        if normalized and normalized not in seen:
            seen.add(normalized)
            out.append(item.strip())
    return out


def semantic_tokens(text: str) -> set[str]:
    stop = {
        "the", "a", "an", "and", "or", "to", "from", "with", "of", "in", "on", "only",
        "preserve", "inherit", "adapt", "ensure", "use", "task", "source", "image", "target",
        "scene", "context", "original", "maintain", "into", "beneath"
    }
    return {t for t in re.findall(r"[a-z0-9-]+", text.lower()) if t not in stop and len(t) > 2}


def meaningfully_duplicate(a: str, b: str) -> bool:
    ta, tb = semantic_tokens(a), semantic_tokens(b)
    if not ta or not tb:
        return False
    overlap = len(ta & tb)
    smaller = min(len(ta), len(tb))
    return overlap / smaller >= 0.82


def oxford_join(items: list[str]) -> str:
    items = unique([x for x in items if x])
    if not items:
        return ""
    if len(items) == 1:
        return items[0]
    if len(items) == 2:
        return f"{items[0]} and {items[1]}"
    return ", ".join(items[:-1]) + f", and {items[-1]}"


def group_of(field_id: str) -> str:
    m = re.match(r"^([A-Z]{1,2})\d+_", field_id)
    return m.group(1) if m else ""


def split_aesthetic_fields(fields: dict[str, dict[str, Any]]) -> tuple[dict[str, dict[str, Any]], dict[str, dict[str, Any]]]:
    normal: dict[str, dict[str, Any]] = {}
    aesthetic: dict[str, dict[str, Any]] = {}
    for field_id, unit in fields.items():
        if group_of(field_id) == "AE":
            aesthetic[field_id] = unit
        else:
            normal[field_id] = unit
    return normal, aesthetic


def aesthetic_strength(aesthetic_fields: dict[str, dict[str, Any]]) -> str:
    unit = aesthetic_fields.get("AE2_aesthetic_strength", {})
    values = value_to_items(unit.get("value"))
    strength = values[0].strip().lower() if values else "off"
    return strength if strength in {"subtle", "standard", "strong"} else "off"


def resolve_prompt_density(
    metadata: dict[str, Any],
    fields: dict[str, dict[str, Any]],
    rules: dict[str, Any],
    output_mode: str,
) -> str:
    aliases = {
        "low": "compact",
        "compact": "compact",
        "concise": "compact",
        "medium": "standard",
        "standard": "standard",
        "high": "high_density",
        "high-density": "high_density",
        "high_density": "high_density",
        "dense": "high_density",
    }
    requested = str(metadata.get("prompt_density", metadata.get("prompt_density_level", ""))).strip().lower()
    if not requested:
        values = value_to_items(fields.get("O2_prompt_density", {}).get("value"))
        requested = values[0].strip().lower() if values else ""
    resolved = aliases.get(requested)
    if resolved:
        return resolved
    return rules.get("density_by_output_mode", {}).get(output_mode, "standard")


def aesthetic_targets(aesthetic_fields: dict[str, dict[str, Any]]) -> set[str]:
    unit = aesthetic_fields.get("AE1_aesthetic_target", {})
    return {item.strip().lower() for item in value_to_items(unit.get("value")) if item.strip()}


def review_profile_weights(aesthetic_fields: dict[str, dict[str, Any]], protocol: dict[str, Any]) -> dict[str, tuple[bool, float]]:
    profile_unit = aesthetic_fields.get("AE3_review_profile", {})
    value = profile_unit.get("value")
    stage_profile = value.get("stages", {}) if isinstance(value, dict) else {}
    weights: dict[str, tuple[bool, float]] = {}
    for stage in protocol.get("stages", []):
        sid = str(stage.get("id", ""))
        raw = stage_profile.get(sid, {}) if isinstance(stage_profile, dict) else {}
        enabled = bool(raw.get("enabled", True)) if isinstance(raw, dict) else True
        try:
            weight = float(raw.get("weight", stage.get("default_weight", 1.0))) if isinstance(raw, dict) else float(stage.get("default_weight", 1.0))
        except Exception:
            weight = float(stage.get("default_weight", 1.0))
        weights[sid] = (enabled, max(0.0, min(1.0, weight)))
    return weights


def target_categories(targets: set[str]) -> set[str]:
    mapping = {
        "cinematic": {"composition", "value", "light", "color", "mood"},
        "editorial": {"composition", "style", "value", "gestalt"},
        "minimalist": {"composition", "gestalt", "value", "style"},
        "painterly": {"color", "light", "material", "style", "mood"},
        "premium-product": {"composition", "light", "color", "material", "value"},
        "documentary": {"composition", "light", "value", "mood"},
    }
    out: set[str] = set()
    for target in targets:
        out.update(mapping.get(target, set()))
    return out


def build_aesthetic_segments(
    fields: dict[str, dict[str, Any]],
    aesthetic_fields: dict[str, dict[str, Any]],
    strength: str,
    aesthetic_library: list[dict[str, Any]] | None = None,
    aesthetic_protocol: dict[str, Any] | None = None,
) -> tuple[list[tuple[int, int, str, str]], list[dict[str, Any]], list[dict[str, str]]]:
    if strength == "off":
        return [], [], []
    if aesthetic_library is None or aesthetic_protocol is None:
        return [], [], [{"id": "missing_aesthetic_sources", "severity": "warning", "message": "Aesthetic pass enabled but 10_AESTHETICS sources are missing"}]
    weights = review_profile_weights(aesthetic_fields, aesthetic_protocol)
    present_groups = {group_of(fid) for fid, unit in fields.items() if not empty(unit.get("value"))}
    wanted_categories = target_categories(aesthetic_targets(aesthetic_fields))
    if not wanted_categories:
        wanted_categories = {"composition", "value", "light", "color", "gestalt"}

    stage_by_category: dict[str, tuple[int, str, float]] = {}
    for stage in aesthetic_protocol.get("stages", []):
        sid = str(stage.get("id", ""))
        enabled, weight = weights.get(sid, (True, float(stage.get("default_weight", 1.0))))
        if not enabled:
            continue
        for category in stage.get("principle_categories", []):
            current = stage_by_category.get(category)
            candidate = (int(stage.get("order", 99)), sid, weight)
            if current is None or candidate[2] > current[2]:
                stage_by_category[str(category)] = candidate

    strength_score = {"subtle": 1, "standard": 2, "strong": 3}
    limit = {"subtle": 2, "standard": 4, "strong": 6}.get(strength, 0)
    scored: list[tuple[float, int, str, dict[str, Any]]] = []
    for principle in aesthetic_library:
        category = str(principle.get("category", ""))
        if category not in wanted_categories or category not in stage_by_category:
            continue
        related = set(principle.get("related_fields", []))
        if present_groups and not (related & present_groups):
            continue
        order, stage_id, stage_weight = stage_by_category[category]
        score = stage_weight * strength_score.get(str(principle.get("strength", "standard")), 2)
        scored.append((score, order, stage_id, principle))

    scored.sort(key=lambda item: (-item[0], item[1], str(item[3].get("id", ""))))
    segments: list[tuple[int, int, str, str]] = []
    debug: list[dict[str, Any]] = []
    seen_cues: set[str] = set()
    for score, order, stage_id, principle in scored:
        for cue in principle.get("positive_cues", []):
            cue_text = str(cue).strip()
            norm = cue_text.lower()
            if not cue_text or norm in seen_cues:
                continue
            seen_cues.add(norm)
            field_id = f"AE:{principle.get('id')}"
            # High order and low rank keep aesthetic cues behind task-critical
            # field wording when max_segments trimming is active.
            segments.append((9000 + order, -20, field_id, cue_text))
            debug.append({
                "field_id": field_id,
                "mode": "aesthetic_enhancement",
                "stage_id": stage_id,
                "principle_id": principle.get("id"),
                "score": round(score, 3),
                "segment": cue_text,
            })
            break
        if len(segments) >= limit:
            break
    return segments, debug, []


def infer_state(unit: dict[str, Any]) -> str:
    explicit = str(unit.get("state", "")).upper()
    if explicit in {"LOCK", "ADAPT", "IGNORE", "GENERATE"}:
        return explicit
    if unit.get("locked") is True:
        return "LOCK"
    if empty(unit.get("value")) and unit.get("adaptation_allowed", True):
        return "GENERATE"
    if unit.get("adaptation_allowed", True):
        return "ADAPT"
    return "LOCK"


def map_term(text: str, terminology: dict[str, str]) -> tuple[str, bool]:
    changed = False
    out = text
    for src, dst in terminology.items():
        if src in out:
            out = out.replace(src, dst)
            changed = True
    return out, changed


def transform_items(items: list[str], terminology: dict[str, str]) -> tuple[list[str], bool]:
    out: list[str] = []
    changed = False
    for item in items:
        item2, did = map_term(item, terminology)
        out.append(item2)
        changed = changed or did
    return unique(out), changed


def make_segment(
    field_id: str,
    unit: dict[str, Any],
    config: dict[str, Any],
    prompt_kind: str,
    terminology: dict[str, str],
) -> tuple[str, dict[str, Any]]:
    mode = config.get("mode", "direct")
    state = infer_state(unit)
    source = str(unit.get("source", ""))
    raw_items = value_to_items(unit.get("value"))
    items, mapped = transform_items(raw_items, terminology)
    joined = oxford_join(items)
    label = config.get("label", field_id)
    debug = {
        "field_id": field_id,
        "state": state,
        "source": source,
        "mode": mode,
        "input": unit.get("value"),
        "mapped": mapped,
        "segment": "",
    }
    if not joined:
        return "", debug
    if mode in {"negative_only", "internal_only", "priority_notes", "success_notes"}:
        return "", debug
    if mode == "edit_task":
        seg = f"Task: {joined}"
    elif mode == "preserve":
        seg = f"Preserve {joined} from source image 1"
    elif mode == "inherit":
        seg = f"Inherit {joined} from the target context"
    elif mode == "edit_method":
        seg = f"Use {joined}"
    elif mode == "preserve_level":
        seg = f"Maintain {joined} preservation"
    elif mode == "adapt":
        seg = f"Adapt only {joined}"
    elif mode == "ensure":
        seg = f"Ensure {joined}"
    elif mode == "relationship":
        seg = f"Use the source-target relationship: {joined}"
    elif mode == "edit_strength":
        seg = f"Use {joined} edit strength"
    elif mode == "format":
        if field_id == "L1_aspect_ratio":
            seg = f"{joined} aspect ratio"
        else:
            seg = joined
    elif mode == "video":
        seg = joined
    else:
        # Apply source/state semantics to normal visual fields only for editing.
        if prompt_kind == "edit" and state == "LOCK":
            if source == "source_image_1":
                seg = f"preserve {joined} from source image 1"
            elif source in {"target_image_2", "source_image_2"}:
                seg = f"inherit {joined} from the target scene"
            else:
                seg = f"preserve {joined}"
        elif prompt_kind == "edit" and state == "ADAPT" and source in {"target_image_2", "source_image_2"}:
            seg = f"adapt {label} to {joined} from the target scene"
        else:
            seg = joined
    debug["segment"] = seg
    return seg, debug


def model_adapter(adapters: dict[str, Any], target: str) -> tuple[str, dict[str, Any]]:
    aliases = adapters.get("aliases", {})
    key = aliases.get(target.lower(), target.lower()) if target else adapters.get("default_adapter", "generic")
    all_adapters = adapters.get("adapters", {})
    if key not in all_adapters:
        key = adapters.get("default_adapter", "generic")
    return key, all_adapters[key]


def compile_request(request: dict[str, Any], *, runtime_export: Path | None = None) -> dict[str, Any]:
    sources = load_compiler_sources(runtime_export)
    rules = sources["rules"]
    mapping = sources["mapping"]
    adapters = sources["adapters"]
    fragments = sources["fragments"]
    metadata = request.get("metadata", {}) if isinstance(request.get("metadata", {}), dict) else {}
    task_type = str(metadata.get("task_type", "")).strip()
    target_model = str(metadata.get("target_model", "generic")).strip() or "generic"
    output_mode = str(metadata.get("output_mode", "Standard")).strip() or "Standard"
    language_target = str(metadata.get("language_target", "English")).strip() or "English"
    all_fields = flatten_fields(request.get("fields", request))
    density = resolve_prompt_density(metadata, all_fields, rules, output_mode)
    density_rule = rules.get("density_policies", {}).get(density, rules["density_policies"]["standard"])
    task_profile = rules.get("task_profiles", {}).get(task_type, rules.get("task_profiles", {}).get("text_to_image", {}))
    prompt_kind = task_profile.get("prompt_kind", "static")
    fields, aesthetic_fields = split_aesthetic_fields(all_fields)
    ae_strength = aesthetic_strength(aesthetic_fields)
    raw_field_text = {fid: ' '.join(value_to_items(unit.get('value'))).lower() for fid, unit in fields.items()}
    warnings: list[dict[str, str]] = []
    dropped: list[dict[str, str]] = []
    used: list[str] = []
    debug_segments: list[dict[str, Any]] = []
    positive_segments: list[tuple[int, int, str, str]] = []
    protected_fields: set[str] = set()
    terminology = rules.get("terminology_mapping", {})
    priority_rank = rules.get("priority_rank", {})
    profile_required = set(task_profile.get("required_groups", []))
    profile_preferred = set(task_profile.get("preferred_groups", []))
    profile_optional = set(task_profile.get("optional_groups", []))
    floor = priority_rank.get(density_rule.get("priority_floor", "P2"), 50)
    keep_all = output_mode == "Full" and density == "archive"
    high_density = density == "high_density"

    if not task_type:
        warnings.append({"id":"missing_task_type","severity":"error","message":"metadata.task_type is empty"})
    if not metadata.get("target_model"):
        warnings.append({"id":"missing_target_model","severity":"warning","message":"metadata.target_model is empty; generic adapter selected"})

    sources_seen: set[str] = set()
    for field_id, unit in fields.items():
        state = infer_state(unit)
        source = str(unit.get("source", ""))
        sources_seen.add(source)
        group = group_of(field_id)
        value = unit.get("value")
        priority = str(unit.get("priority", ""))
        rank = priority_rank.get(priority, 40)
        if state == "LOCK" or priority == "P0":
            protected_fields.add(field_id)
        config = mapping.get("fields", {}).get(field_id)
        if not config:
            dropped.append({"field_id":field_id,"reason":"no_phrase_mapping"})
            continue
        if state == "IGNORE":
            dropped.append({"field_id":field_id,"reason":"explicit_ignore"})
            continue
        if empty(value):
            dropped.append({"field_id":field_id,"reason":"empty_value"})
            if priority == "P0":
                warnings.append({"id":"missing_p0_value","severity":"warning","message":f"{field_id} is P0 but empty"})
            continue
        if state == "LOCK" and unit.get("adaptation_allowed") is True:
            warnings.append({"id":"lock_adapt_conflict","severity":"warning","message":f"{field_id} is LOCK but adaptation_allowed=true"})
        if not keep_all:
            group_allowed = group in profile_required or group in profile_preferred or group in profile_optional
            if not group_allowed:
                dropped.append({"field_id":field_id,"reason":"group_not_enabled_for_task"})
                continue
            if not high_density and group not in profile_required and rank < floor and state != "LOCK":
                dropped.append({"field_id":field_id,"reason":"below_density_priority_floor"})
                continue
        segment, debug = make_segment(field_id, unit, config, prompt_kind, terminology)
        debug_segments.append(debug)
        if segment:
            positive_segments.append((int(config.get("order",9999)), -rank, field_id, segment))
            used.append(field_id)
        elif config.get("mode") not in {"negative_only","internal_only","priority_notes","success_notes"}:
            dropped.append({"field_id":field_id,"reason":"no_emitted_segment"})

    aesthetic_segments, aesthetic_debug, aesthetic_warnings = build_aesthetic_segments(
        fields,
        aesthetic_fields,
        ae_strength,
        sources["aesthetic_library"],
        sources["aesthetic_protocol"],
    )
    positive_segments.extend(aesthetic_segments)
    debug_segments.extend(aesthetic_debug)
    warnings.extend(aesthetic_warnings)
    if aesthetic_segments:
        for field_id in ("AE1_aesthetic_target", "AE2_aesthetic_strength", "AE3_review_profile"):
            if field_id in aesthetic_fields and field_id not in used:
                used.append(field_id)

    # Edit-source warnings.
    if prompt_kind == "edit":
        if "source_image_1" not in sources_seen:
            warnings.append({"id":"edit_missing_source","severity":"warning","message":"Edit task has no source_image_1 field"})
        if not ({"target_image_2","source_image_2"} & sources_seen):
            warnings.append({"id":"edit_missing_target","severity":"warning","message":"Edit task has no target_image_2/source_image_2 field"})

    # Sort and dedupe segment text.
    positive_segments.sort(key=lambda x:(x[0],x[1],x[2]))
    segment_texts: list[str] = []
    seg_seen: set[str] = set()
    raw_max_segments = density_rule.get("max_segments", 24)
    max_segments = int(raw_max_segments) if raw_max_segments is not None else None
    raw_word_limit = density_rule.get("word_budget", [0, None])[1]
    word_limit = int(raw_word_limit) if raw_word_limit is not None and density not in {"high_density", "archive"} else None
    selected_word_count = 0
    for _, _, field_id, segment in positive_segments:
        norm = re.sub(r"\s+", " ", segment.lower().strip().rstrip(".,;"))
        if norm in seg_seen or any(meaningfully_duplicate(segment, prior) for prior in segment_texts):
            dropped.append({"field_id":field_id,"reason":"duplicate_or_overlapping_segment"})
            if field_id in used:
                used.remove(field_id)
            continue
        if max_segments is not None and len(segment_texts) >= max_segments and not keep_all:
            dropped.append({"field_id":field_id,"reason":"segment_budget_exceeded"})
            if field_id in used:
                used.remove(field_id)
            continue
        segment_word_count = len(re.findall(r"\b[\w'-]+\b", segment))
        if word_limit is not None and selected_word_count + segment_word_count > word_limit and field_id not in protected_fields:
            dropped.append({"field_id":field_id,"reason":"word_budget_exceeded"})
            if field_id in used:
                used.remove(field_id)
            continue
        seg_seen.add(norm)
        segment_texts.append(segment)
        selected_word_count += segment_word_count

    # Trigger reusable fragments only as supplements for missing or trimmed fields.
    # This avoids turning the library into a random phrase stack.
    fragment_mode = request.get("compile_options", {}).get("fragment_mode", "supplement_missing")
    raw_max_fragments = fragments.get("library_policy", {}).get("max_fragments_by_density", {}).get(density, 0)
    max_fragments = int(raw_max_fragments) if raw_max_fragments is not None else None
    added_fragments = 0
    if fragment_mode != "disabled":
        used_set = set(used)
        for frag in fragments.get("fragments", []):
            task_types = frag.get("task_types", [])
            if "*" not in task_types and task_type not in task_types:
                continue
            trigger_fields = frag.get("trigger_fields", [])
            triggered = False
            for fid in trigger_fields:
                text = raw_field_text.get(fid, "")
                if text and any(str(v).lower() in text for v in frag.get("trigger_values", [])):
                    triggered = True
                    break
            if not triggered:
                continue
            # Default behavior: do not add a fragment when its trigger fields already
            # produced prompt segments. The raw mapping remains the source of truth.
            if fragment_mode == "supplement_missing" and any(fid in used_set for fid in trigger_fields):
                continue
            phrase = str(frag.get("phrase", "")).strip()
            if not phrase or any(meaningfully_duplicate(phrase, prior) for prior in segment_texts):
                continue
            if max_segments is not None and len(segment_texts) >= max_segments and not keep_all:
                continue
            phrase_word_count = len(re.findall(r"\b[\w'-]+\b", phrase))
            if word_limit is not None and selected_word_count + phrase_word_count > word_limit:
                continue
            if max_fragments is not None and added_fragments >= max_fragments:
                continue
            segment_texts.append(phrase)
            selected_word_count += phrase_word_count
            added_fragments += 1
            debug_segments.append({"fragment_id":frag.get("id"),"mode":"fragment","segment":phrase})

    # Negative prompt.
    negative_items: list[str] = []
    for fid in rules.get("negative_builder", {}).get("source_fields", []):
        unit = fields.get(fid)
        if unit:
            items, _ = transform_items(value_to_items(unit.get("value")), terminology)
            negative_items.extend(items)
    negative_items.extend(task_profile.get("negative_defaults", []))
    normalized_neg: list[str] = []
    for item in negative_items:
        item = re.sub(r"^do not\s+", "", item.strip(), flags=re.I)
        normalized_neg.extend(part.strip() for part in item.split(",") if part.strip())
    negative_items = unique(normalized_neg)
    negative_prompt = ", ".join(negative_items)

    # Build adapter-specific prompt.
    adapter_key, adapter = model_adapter(adapters, target_model)
    join_style = adapter.get("join_style", "comma")
    if join_style == "sentence":
        positive_prompt = ". ".join(s.rstrip(".,; ") for s in segment_texts if s).strip()
        if positive_prompt and not positive_prompt.endswith("."):
            positive_prompt += "."
    else:
        positive_prompt = ", ".join(s.rstrip(".,; ") for s in segment_texts if s)
    model_prompt = positive_prompt
    if not adapter.get("negative_channel", True) and negative_items and prompt_kind in {"edit","video"}:
        top_neg = negative_items[:8]
        avoid = "Avoid the following failures: " + ", ".join(top_neg) + "."
        if join_style == "sentence":
            model_prompt = (model_prompt + " " + avoid).strip()
        elif adapter_key == "midjourney":
            model_prompt = (model_prompt + " --no " + ", ".join(top_neg[:4])).strip()
        else:
            model_prompt = (model_prompt + ", " + avoid).strip(", ")

    density_word_max = density_rule.get("word_budget", [0, None])[1]
    max_words = int(adapter.get("max_words", 9999))
    if density_word_max is not None:
        max_words = min(max_words, int(density_word_max))
    word_count = len(re.findall(r"\b[\w'-]+\b", model_prompt))
    if word_count > max_words:
        warnings.append({"id":"prompt_over_budget","severity":"warning","message":f"model_prompt has {word_count} words; recommended max is {max_words}"})

    return {
        "compile_metadata":{
            "compiler_version":rules.get("compiler_version"),
            "task_type":task_type,
            "prompt_kind":prompt_kind,
            "target_model":target_model,
            "resolved_adapter":adapter_key,
            "output_mode":output_mode,
            "prompt_density":density,
            "language_target":language_target,
            "aesthetic_strength":ae_strength,
            "model_prompt_word_count":word_count,
        },
        "positive_prompt":positive_prompt,
        "negative_prompt":negative_prompt,
        "model_prompt":model_prompt,
        "adapter_notes":adapter.get("notes", []),
        "parameter_hints":adapter.get("parameter_hints", {}),
        "used_fields":used,
        "dropped_fields":dropped,
        "warnings":warnings,
        "debug_segments":debug_segments if request.get("compile_options", {}).get("include_debug_segments", True) else [],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Compile PCS structured fields into model-ready prompts")
    parser.add_argument("input", type=Path, help="PCS compile request JSON")
    parser.add_argument("--output", type=Path, help="Write result JSON to this path")
    args = parser.parse_args()
    try:
        request = load_json(args.input)
        result = compile_request(request)
        text = dump_json(result)
        if args.output:
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(text, encoding="utf-8")
            print(f"Wrote {args.output}")
        else:
            sys.stdout.write(text)
        return 0
    except Exception as exc:  # noqa: BLE001
        print(f"PCS compiler failed: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
