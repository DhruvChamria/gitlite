from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from gitlite.errors import RepositoryError
from gitlite.repository import Repository
from tests.helpers import working_directory


class HistoryDiffTests(unittest.TestCase):
    def test_text_binary_newline_and_empty_diffs(self):
        with tempfile.TemporaryDirectory() as temp, working_directory(Path(temp)):
            root = Path(temp)
            repo = Repository(root, discover=False)
            repo.init()
            (root / "text.txt").write_bytes(b"one\n")
            (root / "empty.txt").write_bytes(b"")
            (root / "binary.bin").write_bytes(b"a\0b")
            repo.add(["text.txt", "empty.txt", "binary.bin"])
            repo.commit("initial")
            (root / "text.txt").write_bytes(b"two")
            (root / "empty.txt").unlink()
            (root / "binary.bin").write_bytes(b"a\0c")
            output = repo.diff()
            self.assertIn("-one", output)
            self.assertIn("+two", output)
            self.assertIn("\\ No newline at end of file", output)
            self.assertIn("Deleted empty file: empty.txt", output)
            self.assertIn("Binary files differ: binary.bin", output)
            (root / "added.txt").write_bytes(b"")
            self.assertEqual(repo.diff("added.txt"), "Added empty file: added.txt")

    def test_staged_diff_and_unrelated_explicit_path(self):
        with tempfile.TemporaryDirectory() as temp, working_directory(Path(temp)):
            root = Path(temp)
            repo = Repository(root, discover=False)
            repo.init()
            (root / "a.txt").write_bytes(b"a\n")
            repo.add(["a.txt"])
            self.assertIn("+a", repo.diff(staged=True))
            (root / "other.txt").write_bytes(b"x")
            with self.assertRaises(RepositoryError):
                repo.diff("other.txt", staged=True)

    def test_log_all_preserves_alternate_descendant_and_show(self):
        with tempfile.TemporaryDirectory() as temp, working_directory(Path(temp)):
            root = Path(temp)
            repo = Repository(root, discover=False)
            repo.init()
            path = root / "a.txt"
            path.write_bytes(b"one")
            repo.add(["a.txt"])
            first, _ = repo.commit("first")
            path.write_bytes(b"two")
            repo.add(["a.txt"])
            second, _ = repo.commit("second")
            repo.checkout(first)
            path.write_bytes(b"branch")
            repo.add(["a.txt"])
            third, parent = repo.commit("alternate")
            self.assertEqual(parent, first)
            ids = {item["hash"] for item in repo.log(all_commits=True)}
            self.assertEqual(ids, {first, second, third})
            self.assertEqual(repo.show(second)["message"], "second")
            self.assertEqual(repo.show()["hash"], third)

    def test_cli_escapes_control_characters_in_messages(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            main = Path(__file__).resolve().parents[1] / "main.py"
            def run(*args):
                return subprocess.run([sys.executable, str(main), *args], cwd=root, capture_output=True, text=True)
            self.assertEqual(run("init").returncode, 0)
            (root / "a.txt").write_bytes(b"a")
            self.assertEqual(run("add", "a.txt").returncode, 0)
            self.assertEqual(run("commit", "-m", "safe\x1b[31m\nnext").returncode, 0)
            log = run("log")
            self.assertNotIn("\x1b", log.stdout)
            self.assertIn("\\u001b", log.stdout)
            self.assertIn("\\u000a", log.stdout)


if __name__ == "__main__":
    unittest.main()
