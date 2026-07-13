from __future__ import annotations

import json
import subprocess
import sys
import unittest
from pathlib import Path

PACKAGE_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = PACKAGE_ROOT / 'tools' / 'pcs_user_entry_compile.py'
RUNTIME_EXPORT = PACKAGE_ROOT / 'references' / 'pcs-core-skill-runtime.json'

class PublishedSkillPackageTests(unittest.TestCase):
    def run_entry(self, prompt: str, *args: str) -> dict[str, object]:
        completed = subprocess.run([sys.executable, str(SCRIPT), prompt, *args], cwd=PACKAGE_ROOT, capture_output=True, text=True, check=False)
        self.assertEqual(completed.returncode, 0, completed.stderr)
        return json.loads(completed.stdout)

    def test_runtime_export_is_the_only_core_reference(self) -> None:
        self.assertTrue(RUNTIME_EXPORT.exists(), 'Runtime Core export is missing')
        self.assertEqual(json.loads(RUNTIME_EXPORT.read_text(encoding='utf-8'))['profile'], 'skill-runtime')
        for forbidden_directory in ('07_OUTPUT_TEMPLATE', '08_MODEL_ADAPTER', '10_AESTHETICS', '99_SCHEMAS', '99_GENERATED'):
            self.assertFalse((PACKAGE_ROOT / forbidden_directory).exists())

    def test_text_to_image_runs_from_runtime_export(self) -> None:
        result = self.run_entry('Create a cinematic image of a glass astronaut walking through a quiet greenhouse at dawn.')
        self.assertEqual(result['task_type'], 'text_to_image')
        self.assertEqual(result['prompt_density'], 'standard')
        self.assertTrue(result['model_prompt'])
        self.assertNotIn('debug_segments', result)

    def test_chinese_text_to_image_runs_from_runtime_export(self) -> None:
        result = self.run_entry('生成一张玻璃宇航员穿过清晨温室的电影感画面。')
        self.assertEqual(result['task_type'], 'text_to_image')
        self.assertIn('玻璃宇航员', result['model_prompt'])
        self.assertIn('清晨温室', result['model_prompt'])

    def test_chinese_product_integration_routes_from_runtime_export(self) -> None:
        result = self.run_entry('将参考图中的香水瓶融合到大理石浴室广告场景。')
        self.assertEqual(result['task_type'], 'product_integration')
        self.assertTrue(result['model_prompt'])

    def test_other_language_fallback_is_not_empty(self) -> None:
        result = self.run_entry('朝の温室を歩くガラスの宇宙飛行士を生成')
        self.assertTrue(result['model_prompt'])
    def test_product_negative_constraints_are_not_duplicated(self) -> None:
        result = self.run_entry('Integrate the matte black perfume bottle from reference image 1 into a marble bathroom ad scene. Preserve the bottle silhouette and logo, match reflections and contact shadow.', '--target-model', 'comfyui_sd', '--prompt-density', 'high_density')
        negatives = [item.strip().lower() for item in result['negative_prompt'].split(',') if item.strip()]
        self.assertEqual(negatives.count('distorted logo'), 1)
        self.assertEqual(negatives.count('altered product silhouette'), 1)

if __name__ == '__main__':
    unittest.main()
