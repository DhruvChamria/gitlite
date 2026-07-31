from contextlib import redirect_stdout
from datetime import datetime, timezone
import io
import os
from pathlib import Path
import sys
import tempfile
import unittest

from gitlite.cli import main
from gitlite.errors import CorruptionError, RepositoryError
from gitlite.models import Commit, sha1_bytes
from gitlite.repository import Repository
from tests.helpers import working_directory


class AuditRegressionTests(unittest.TestCase):
    def make_repo(self, root: Path) -> Repository:
        repo = Repository(root, discover=False)
        repo.init()
        return repo

    def test_duplicate_unstage_arguments_are_idempotent(self):
        with tempfile.TemporaryDirectory() as temp, working_directory(Path(temp)):
            root = Path(temp)
            repo = self.make_repo(root)
            (root / "a.txt").write_text("a", encoding="utf-8")
            repo.add(["a.txt"])
            self.assertEqual(repo.unstage(["a.txt", "a.txt"]), ["Unstaged (working file kept): a.txt"])
            self.assertEqual(repo.store.read_index(), {})

    def test_nested_initialization_is_rejected(self):
        with tempfile.TemporaryDirectory() as temp, working_directory(Path(temp)):
            root = Path(temp)
            self.make_repo(root)
            inner = root / "nested"
            inner.mkdir()
            with self.assertRaisesRegex(RepositoryError, "nested repository"):
                Repository(inner, discover=False).init()
            self.assertFalse((inner / ".mygit").exists())

    def test_commit_residue_is_ignored_consistently(self):
        with tempfile.TemporaryDirectory() as temp, working_directory(Path(temp)):
            repo = self.make_repo(Path(temp))
            residue = repo.store.commits / ".gitlite-tmp-abrupt"
            residue.write_bytes(b"partial")
            result = repo.fsck()
            self.assertEqual(result.errors, ())
            self.assertTrue(any("residue" in item for item in result.information))
            self.assertEqual(repo.log(all_commits=True), [])

    def test_history_views_reject_missing_references(self):
        with tempfile.TemporaryDirectory() as temp, working_directory(Path(temp)):
            repo = self.make_repo(Path(temp))
            stamp = datetime.now(timezone.utc).isoformat()
            missing_parent = repo.store.save_commit(Commit("0" * 40, stamp, "missing parent", {}))
            with self.assertRaisesRegex(CorruptionError, "missing parent"):
                repo.show(missing_parent)
            with self.assertRaisesRegex(CorruptionError, "missing parent"):
                repo.log(all_commits=True)
            (repo.store.commits / f"{missing_parent}.json").unlink()
            missing_blob = repo.store.save_commit(Commit(None, stamp, "missing blob", {"a.txt": "1" * 40}))
            with self.assertRaisesRegex(CorruptionError, "invalid blob"):
                repo.show(missing_blob)

    def test_fsck_handles_deep_valid_history_iteratively(self):
        with tempfile.TemporaryDirectory() as temp, working_directory(Path(temp)):
            repo = self.make_repo(Path(temp))
            parent = None
            ids = []
            stamp = datetime.now(timezone.utc).isoformat()
            for index in range(240):
                parent = repo.store.save_commit(Commit(parent, stamp, f"commit {index}", {}))
                ids.append(parent)
            floor = min(ids)
            nonce = 0
            while True:
                candidate = Commit(parent, stamp, f"tip {nonce}", {})
                if candidate.compute_hash() < floor:
                    break
                nonce += 1
            tip = repo.store.save_commit(candidate)
            repo.store.write_head(tip)
            previous_limit = sys.getrecursionlimit()
            try:
                sys.setrecursionlimit(200)
                self.assertEqual(repo.fsck().errors, ())
            finally:
                sys.setrecursionlimit(previous_limit)

    def test_deep_json_is_reported_as_corruption(self):
        with tempfile.TemporaryDirectory() as temp, working_directory(Path(temp)):
            repo = self.make_repo(Path(temp))
            repo.store.index.write_text('{"x":' * 80 + "0" + "}" * 80, encoding="utf-8")
            with self.assertRaisesRegex(CorruptionError, "nested too deeply"):
                repo.store.read_index()

    def test_fsck_does_not_scan_linked_blob_directory(self):
        with tempfile.TemporaryDirectory() as temp, working_directory(Path(temp)):
            root = Path(temp)
            repo = self.make_repo(root)
            external = root / "external-blobs"
            external.mkdir()
            data = b"outside"
            (external / sha1_bytes(data)).write_bytes(data)
            repo.store.blobs.rmdir()
            try:
                repo.store.blobs.symlink_to(external, target_is_directory=True)
            except OSError as exc:
                self.skipTest(f"symlink creation unavailable: {exc}")
            result = repo.fsck()
            self.assertTrue(any("unsafe blob directory" in item for item in result.errors))
            self.assertEqual(result.blobs, 0)

    @unittest.skipIf(os.name == "nt", "Win32 filenames cannot contain control characters")
    def test_status_escapes_control_characters_in_untracked_names(self):
        with tempfile.TemporaryDirectory() as temp, working_directory(Path(temp)):
            root = Path(temp)
            self.make_repo(root)
            (root / "line\nbreak.txt").write_text("x", encoding="utf-8")
            output = io.StringIO()
            with redirect_stdout(output):
                self.assertEqual(main(["status"]), 0)
            self.assertNotIn("line\nbreak.txt", output.getvalue())
            self.assertIn("line\\u000abreak.txt", output.getvalue())


if __name__ == "__main__":
    unittest.main()
