from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

PACKAGE_ROOT = Path(__file__).resolve().parents[1]
RUNTIME_EXPORT = PACKAGE_ROOT / 'references' / 'pcs-core-skill-runtime.json'
sys.path.insert(0, str(PACKAGE_ROOT / 'tools'))
from pcs_prompt_compile import compile_request  # noqa: E402

class PublishedSkillPackageTests(unittest.TestCase):
    def compile_smoke_request(self) -> dict[str, object]:
        return compile_request({
            'metadata': {'task_type': 'text_to_image', 'target_model': 'generic', 'output_mode': 'Standard', 'prompt_density': 'standard', 'language_target': 'English'},
            'fields': {
                'A3_identity_or_category': {'value': 'glass astronaut', 'source': 'package_test', 'state': 'ADAPT', 'priority': 'P0'},
                'A6_pose_or_action': {'value': 'walking through a greenhouse', 'source': 'package_test', 'state': 'ADAPT', 'priority': 'P0'},
                'H1_rendering_style': {'value': 'cinematic', 'source': 'package_test', 'state': 'ADAPT', 'priority': 'P1'},
            },
            'compile_options': {'include_debug_segments': False, 'include_adapter_notes': False},
        })

    def test_runtime_export_is_the_only_core_reference(self) -> None:
        self.assertTrue(RUNTIME_EXPORT.exists(), 'Runtime Core export is missing')
        self.assertEqual(json.loads(RUNTIME_EXPORT.read_text(encoding='utf-8'))['profile'], 'skill-runtime')
        for forbidden_directory in ('07_OUTPUT_TEMPLATE', '08_MODEL_ADAPTER', '10_AESTHETICS', '99_SCHEMAS', '99_GENERATED'):
            self.assertFalse((PACKAGE_ROOT / forbidden_directory).exists())

    def test_host_llm_skill_compiles_a_canonical_request(self) -> None:
        self.assertFalse((PACKAGE_ROOT / 'tools' / 'pcs_user_entry_compile.py').exists())
        result = self.compile_smoke_request()
        self.assertEqual(result['compile_metadata']['task_type'], 'text_to_image')
        self.assertTrue(result['model_prompt'])
        self.assertEqual(result['debug_segments'], [])

    def test_product_negative_constraints_are_not_duplicated(self) -> None:
        result = compile_request({
            'metadata': {'task_type': 'product_integration', 'target_model': 'comfyui_sd', 'output_mode': 'Standard', 'prompt_density': 'high_density', 'language_target': 'English'},
            'fields': {
                'X1_edit_task_type': {'value': 'product integration', 'source': 'package_test', 'state': 'ADAPT', 'priority': 'P0'},
                'X2_source_asset': {'value': 'matte black perfume bottle', 'source': 'source_image_1', 'state': 'LOCK', 'priority': 'P0'},
                'X3_target_context': {'value': 'marble bathroom ad scene', 'source': 'target_image_2', 'state': 'ADAPT', 'priority': 'P0'},
                'X5_preservation_level': {'value': 'bottle silhouette and logo', 'source': 'source_image_1', 'state': 'LOCK', 'priority': 'P0'},
                'Y8_negative_constraints': {'value': 'distorted logo, altered product silhouette', 'source': 'package_test', 'state': 'ADAPT', 'priority': 'P0'},
            },
            'compile_options': {'include_debug_segments': False, 'include_adapter_notes': False},
        })
        negatives = [item.strip().lower() for item in result['negative_prompt'].split(',') if item.strip()]
        self.assertEqual(negatives.count('distorted logo'), 1)
        self.assertEqual(negatives.count('altered product silhouette'), 1)

if __name__ == '__main__':
    unittest.main()
