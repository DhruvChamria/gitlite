from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from gitlite.repository import Repository
from tests.helpers import working_directory


class IntegrityTests(unittest.TestCase):
    def test_valid_and_unreachable_objects_are_retained(self):
        with tempfile.TemporaryDirectory() as temp, working_directory(Path(temp)):
            root = Path(temp)
            repo = Repository(root, discover=False)
            repo.init()
            (root / "a.txt").write_bytes(b"a")
            repo.add(["a.txt"])
            first, _ = repo.commit("first")
            (root / "a.txt").write_bytes(b"b")
            repo.add(["a.txt"])
            second, _ = repo.commit("second")
            repo.checkout(first)
            result = repo.fsck()
            self.assertEqual(result.errors, ())
            self.assertTrue(any(second in item for item in result.information))
            self.assertTrue((repo.store.commits / f"{second}.json").exists())

    def test_fsck_collects_independent_head_index_and_object_errors(self):
        with tempfile.TemporaryDirectory() as temp, working_directory(Path(temp)):
            root = Path(temp)
            repo = Repository(root, discover=False)
            repo.init()
            (root / "a.txt").write_bytes(b"a")
            repo.add(["a.txt"])
            commit_id, _ = repo.commit("first")
            blob_id = repo.store.read_commit(commit_id).files["a.txt"]
            repo.store.head.write_text("not-an-id", encoding="utf-8")
            repo.store.index.write_text("[]", encoding="utf-8")
            (repo.store.blobs / blob_id).write_bytes(b"corrupt")
            (repo.store.commits / "bad-name").write_text("x", encoding="utf-8")
            result = repo.fsck()
            joined = "\n".join(result.errors)
            self.assertIn("HEAD", joined)
            self.assertIn("index.json", joined)
            self.assertIn("Blob content", joined)
            self.assertIn("Invalid commit object filename", joined)
            self.assertGreaterEqual(len(result.errors), 4)

    def test_temp_residue_is_informational_and_preserved(self):
        with tempfile.TemporaryDirectory() as temp, working_directory(Path(temp)):
            root = Path(temp)
            repo = Repository(root, discover=False)
            repo.init()
            residue = repo.store.blobs / ".gitlite-tmp-abrupt"
            residue.write_bytes(b"partial")
            result = repo.fsck()
            self.assertEqual(result.errors, ())
            self.assertTrue(any("residue" in item for item in result.information))
            self.assertEqual(residue.read_bytes(), b"partial")

    def test_cli_fsck_exit_codes(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            main = Path(__file__).resolve().parents[1] / "main.py"
            def run(*args):
                return subprocess.run([sys.executable, str(main), *args], cwd=root, capture_output=True, text=True)
            self.assertEqual(run("init").returncode, 0)
            clean = run("fsck")
            self.assertEqual(clean.returncode, 0, clean.stderr)
            self.assertIn("fsck OK", clean.stdout)
            (root / ".mygit/HEAD").write_text("broken", encoding="utf-8")
            broken = run("fsck")
            self.assertEqual(broken.returncode, 1)
            self.assertIn("HEAD", broken.stderr)


if __name__ == "__main__":
    unittest.main()
