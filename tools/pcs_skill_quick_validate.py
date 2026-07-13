#!/usr/bin/env python3
"""Fast deterministic compiler check for the Host LLM PCS Skill package."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

from pcs_prompt_compile import compile_request  # noqa: E402


REQUIRED_SKILL_TEXT = (
    "text_to_image",
    "image_inversion",
    "subject_transfer",
    "product_integration",
    "character_consistency_edit",
    "video_generation",
    "image_to_video",
    "Host LLM",
    "pcs_prompt_compile.py",
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
    result = compile_request(
        {
            "metadata": {
                "task_type": "text_to_image",
                "target_model": "generic",
                "output_mode": "Standard",
                "prompt_density": "standard",
                "language_target": "English",
            },
            "fields": {
                "A3_identity_or_category": {"value": "glass astronaut", "source": "smoke_test", "state": "ADAPT", "priority": "P0"},
                "A6_pose_or_action": {"value": "walking through a greenhouse", "source": "smoke_test", "state": "ADAPT", "priority": "P0"},
                "I1_time_of_day": {"value": "dawn", "source": "smoke_test", "state": "ADAPT", "priority": "P1"},
                "H1_rendering_style": {"value": "cinematic", "source": "smoke_test", "state": "ADAPT", "priority": "P1"},
            },
            "compile_options": {"include_debug_segments": False, "include_adapter_notes": False},
        }
    )
    if result.get("compile_metadata", {}).get("task_type") != "text_to_image" or not result.get("model_prompt"):
        print("Compiler smoke validation failed")
        return 1
    if result.get("debug_segments"):
        print("Compiler smoke validation exposed debug segments")
        return 1
    print("PCS Host LLM skill quick validation OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
