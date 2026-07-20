from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
MAIN = ROOT / "main.py"


class CliTests(unittest.TestCase):
    def run_cli(self, cwd, *args):
        return subprocess.run([sys.executable, str(MAIN), *args], cwd=cwd, text=True, capture_output=True)

    def test_help_and_version(self):
        with tempfile.TemporaryDirectory() as temp:
            self.assertEqual(self.run_cli(temp).returncode, 0)
            self.assertIn("usage:", self.run_cli(temp, "--help").stdout)
            self.assertIn("0.1.0", self.run_cli(temp, "--version").stdout)

    def test_baseline_workflow_and_subdirectory_discovery(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            self.assertEqual(self.run_cli(root, "init").returncode, 0)
            (root / "note.txt").write_text("one\n", encoding="utf-8")
            self.assertEqual(self.run_cli(root, "add", "note.txt").returncode, 0)
            commit = self.run_cli(root, "commit", "-m", "initial")
            self.assertEqual(commit.returncode, 0, commit.stderr)
            commit_id = commit.stdout.split()[2]
            child = root / "child"
            child.mkdir()
            log = self.run_cli(child, "log")
            self.assertEqual(log.returncode, 0, log.stderr)
            self.assertIn(commit_id, log.stdout)
            (root / "note.txt").write_text("two\n", encoding="utf-8")
            self.assertEqual(self.run_cli(root, "checkout", commit_id).returncode, 0)
            self.assertEqual((root / "note.txt").read_text(encoding="utf-8"), "one\n")

    def test_unknown_command_is_usage_error(self):
        with tempfile.TemporaryDirectory() as temp:
            result = self.run_cli(temp, "wat")
            self.assertEqual(result.returncode, 2)
            self.assertTrue(result.stderr)


if __name__ == "__main__":
    unittest.main()
