"""Catch parse errors that disable every recruitment tab before startup."""
import re
import shutil
import subprocess
import unittest
from pathlib import Path


class RecruitmentScriptTests(unittest.TestCase):
    @unittest.skipUnless(shutil.which('node'), 'Node.js is needed to check JavaScript')
    def test_inline_scripts_parse(self):
        template = (Path(__file__).resolve().parents[1] / 'talent_portal' /
                    'templates/admin/admin_recruitment.html').read_text(encoding='utf-8')
        scripts = re.findall(r'<script>(.*?)</script>', template, re.S)
        self.assertTrue(scripts)
        for script in scripts:
            script = re.sub(r'\{\{.*?\}\}', 'null', script)
            result = subprocess.run(
                [shutil.which('node'), '--check'], input=script.encode('utf-8'),
                capture_output=True, check=False,
            )
            self.assertEqual(result.returncode, 0, result.stderr.decode('utf-8'))
