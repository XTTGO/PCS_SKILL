#!/usr/bin/env python3
"""Fast structural and behavior check for the PCS natural-language entry skill."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

from pcs_user_entry_compile import compile_user_entry  # noqa: E402


REQUIRED_SKILL_TEXT = (
    "text_to_image",
    "image_inversion",
    "subject_transfer",
    "product_integration",
    "character_consistency_edit",
    "video_generation",
    "image_to_video",
    "pcs_user_entry_compile.py",
)


def main() -> int:
    package_skill = ROOT / "SKILL.md"
    skill_path = package_skill if package_skill.exists() else ROOT / "skills" / "pcs-skill" / "SKILL.md"
    if not skill_path.exists():
        print("Missing candidate skill or packaged SKILL.md")
        return 1
    skill_text = skill_path.read_text(encoding="utf-8")
    missing = [item for item in REQUIRED_SKILL_TEXT if item not in skill_text]
    if missing:
        print(f"Skill is missing required references: {missing}")
        return 1
    result = compile_user_entry(
        "Create a cinematic image of a glass astronaut walking through a quiet greenhouse at dawn.",
        target_model="generic",
    )
    if result.get("task_type") != "text_to_image" or not result.get("model_prompt"):
        print("Natural-language entry smoke compilation failed")
        return 1
    if "debug_segments" in result:
        print("Default user result exposed debug segments")
        return 1
    print("PCS user entry skill quick validation OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
