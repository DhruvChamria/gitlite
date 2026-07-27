from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


class DemoTests(unittest.TestCase):
    def test_demo_is_isolated_and_reports_safety_flow(self):
        root = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory() as temp:
            caller = Path(temp)
            sentinel = caller / "sentinel.txt"
            sentinel.write_bytes(b"untouched")
            result = subprocess.run(
                [sys.executable, str(root / "examples/demo.py")],
                cwd=caller,
                text=True,
                capture_output=True,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(sentinel.read_bytes(), b"untouched")
            self.assertEqual(sorted(path.name for path in caller.iterdir()), ["sentinel.txt"])
            self.assertIn("Checkout refused", result.stdout)
            self.assertIn("fsck OK", result.stdout)
            self.assertIn("Temporary demo repository cleaned up", result.stdout)
            self.assertIn("Initial commit:", result.stdout)
            self.assertIn("Second commit:", result.stdout)


if __name__ == "__main__":
    unittest.main()
