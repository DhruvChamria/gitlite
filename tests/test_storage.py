from pathlib import Path
import json
import subprocess
import sys
import tempfile
import unittest

from gitlite.errors import CorruptionError, PathError
from gitlite.repository import Repository
from tests.helpers import working_directory


class StorageTests(unittest.TestCase):
    def test_incomplete_repository_is_not_repaired(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / ".mygit").mkdir()
            with working_directory(root), self.assertRaises(CorruptionError):
                Repository(discover=False).init()
            self.assertEqual(list((root / ".mygit").iterdir()), [])

    def test_tampered_blob_is_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            with working_directory(root):
                repo = Repository(discover=False)
                repo.init()
                (root / "a.txt").write_bytes(b"original")
                repo.add(["a.txt"])
                blob_id = next((root / ".mygit/objects/blobs").iterdir()).name
                (root / ".mygit/objects/blobs" / blob_id).write_bytes(b"tampered")
                with self.assertRaises(CorruptionError):
                    repo.commit("message")

    def test_duplicate_json_keys_are_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            with working_directory(root):
                repo = Repository(discover=False)
                repo.init()
                (root / ".mygit/index.json").write_text('{"a":"0000000000000000000000000000000000000000","a":null}', encoding="utf-8")
                with self.assertRaises(CorruptionError):
                    repo.status()

    def test_invalid_batch_does_not_update_index(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            with working_directory(root):
                repo = Repository(discover=False)
                repo.init()
                (root / "ok.txt").write_text("ok", encoding="utf-8")
                before = (root / ".mygit/index.json").read_bytes()
                with self.assertRaises(PathError):
                    repo.add(["ok.txt", "../escape.txt"])
                self.assertEqual((root / ".mygit/index.json").read_bytes(), before)

    def test_real_lock_excludes_second_process_and_releases_on_exit(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            with working_directory(root):
                Repository(discover=False).init()
            script = (
                "from pathlib import Path; import sys; "
                "from gitlite.storage import Store; "
                "lock=Store(Path(sys.argv[1])).locked(); lock.__enter__(); "
                "print('ready', flush=True); sys.stdin.readline(); lock.__exit__(None,None,None)"
            )
            child = subprocess.Popen(
                [sys.executable, "-c", script, str(root)],
                cwd=Path(__file__).resolve().parents[1],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                text=True,
            )
            try:
                self.assertEqual(child.stdout.readline().strip(), "ready")
                with working_directory(root):
                    result = subprocess.run(
                        [sys.executable, str(Path(__file__).resolve().parents[1] / "main.py"), "status"],
                        capture_output=True,
                        text=True,
                    )
                self.assertEqual(result.returncode, 1)
                self.assertIn("busy", result.stderr)
            finally:
                child.stdin.write("\n")
                child.stdin.flush()
                child.wait(timeout=5)
            with working_directory(root):
                self.assertEqual(Repository().status(), (None, {}))


if __name__ == "__main__":
    unittest.main()
