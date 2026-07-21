import subprocess, sys
from pathlib import Path
import unittest

class CLITests(unittest.TestCase):
    def test_58_self_test(self):
        result=subprocess.run([sys.executable,str(Path(__file__).parents[1]/"main.py"),"--self-test"],capture_output=True,text=True,encoding="utf-8")
        self.assertEqual(result.returncode,0,result.stderr); self.assertIn("离线自检通过",result.stdout)
