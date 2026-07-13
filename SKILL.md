---
name: pcs-skill
description: Use when a user gives a natural-language visual brief or reference-image description and needs a PCS task classification plus a model-ready prompt without manually authoring PCS JSON.
---

# PCS Skill

## Runtime reference

Read `references/pcs-core-skill-runtime.json` as the only PCS Core reference at runtime. Treat it as read-only. Do not read or expose the PCS Core development directory.

## Procedure

1. Identify one existing task type: `text_to_image`, `image_inversion`, `subject_transfer`, `product_integration`, `character_consistency_edit`, `video_generation`, or `image_to_video`.
2. Resolve the target model from the request; otherwise use the `generic` adapter.
3. Resolve density from an explicit request. Default to `standard`; ask only if the density choice is genuinely outcome-critical.
4. Extract only non-empty, task-relevant field control units. Preserve explicit source, target, `LOCK`, and `P0` evidence. Do not create fields.
5. Omit empty values, `IGNORE` controls, task-irrelevant groups, and semantic duplicates. Keep `LOCK` and `P0` wording before any length budget.
6. Call the packaged compiler; never hand-join a final prompt:

```bash
python tools/pcs_user_entry_compile.py "<natural-language visual request>" --target-model generic --prompt-density standard
```

7. Return `task_type`, `prompt_density`, `model_prompt`, model-supported `negative_prompt`, and `warnings` by default. Show `compile_info` or debug segments only when requested.

## Blocking questions

Ask only for information that prevents a usable result: an edit task without an identifiable source or target, or an image-to-video task without a source image. Omit non-critical visual details rather than inventing them.

## Boundaries

- Keep PCS Core as the source of truth; use this Skill only as an entry adapter.
- Use supplied visual evidence or descriptions for reference-image interpretation. Do not claim automatic visual scoring.
- Do not treat output quality as automatic rule validation. Do not write observations back to Core rules.
- Do not implement Web behavior or automatic rule upgrades.
