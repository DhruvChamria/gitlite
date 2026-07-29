from pathlib import Path
import tempfile
import unittest

from gitlite.errors import ConflictError, CorruptionError, PathError, RecoveryError
from gitlite.repository import Repository
from gitlite.storage import atomic_write
from gitlite.transactions import write_journal
from tests.helpers import working_directory


class CheckoutRecoveryTests(unittest.TestCase):
    def history(self, root: Path):
        repo = Repository(root, discover=False)
        repo.init()
        (root / "a.txt").write_bytes(b"one")
        repo.add(["a.txt"])
        first, _ = repo.commit("first")
        (root / "a.txt").write_bytes(b"two")
        (root / "b.txt").write_bytes(b"bee")
        repo.add(["a.txt", "b.txt"])
        second, _ = repo.commit("second")
        return repo, first, second

    def test_checkout_removes_obsolete_tracked_and_preserves_untracked(self):
        with tempfile.TemporaryDirectory() as temp, working_directory(Path(temp)):
            root = Path(temp)
            repo, first, second = self.history(root)
            (root / "unrelated.txt").write_bytes(b"safe")
            repo.checkout(first)
            self.assertEqual((root / "a.txt").read_bytes(), b"one")
            self.assertFalse((root / "b.txt").exists())
            self.assertEqual((root / "unrelated.txt").read_bytes(), b"safe")
            repo.checkout(second)
            self.assertEqual((root / "b.txt").read_bytes(), b"bee")

    def test_dirty_staged_and_untracked_target_conflicts_change_nothing(self):
        with tempfile.TemporaryDirectory() as temp, working_directory(Path(temp)):
            root = Path(temp)
            repo, first, second = self.history(root)
            (root / "a.txt").write_bytes(b"local")
            before_head = repo.store.head.read_bytes()
            with self.assertRaises(ConflictError):
                repo.checkout(first)
            self.assertEqual((root / "a.txt").read_bytes(), b"local")
            self.assertEqual(repo.store.head.read_bytes(), before_head)
            (root / "a.txt").write_bytes(b"two")
            repo.remove(["b.txt"])
            with self.assertRaises(ConflictError):
                repo.checkout(first)
            repo.unstage(["b.txt"])
            repo.checkout(first)
            (root / "b.txt").write_bytes(b"untracked")
            with self.assertRaises(ConflictError):
                repo.checkout(second)
            self.assertEqual((root / "b.txt").read_bytes(), b"untracked")

    def test_missing_target_blob_is_detected_before_first_write(self):
        with tempfile.TemporaryDirectory() as temp, working_directory(Path(temp)):
            root = Path(temp)
            repo, first, second = self.history(root)
            repo.checkout(first)
            target = repo.store.read_commit(second)
            missing = target.files["b.txt"]
            (repo.store.blobs / missing).unlink()
            before = (root / "a.txt").read_bytes()
            with self.assertRaises(CorruptionError):
                repo.checkout(second)
            self.assertEqual((root / "a.txt").read_bytes(), before)
            self.assertEqual(repo.store.read_head(), first)

    def test_checkout_rejects_existing_directory_case_collision(self):
        with tempfile.TemporaryDirectory() as temp, working_directory(Path(temp)):
            root = Path(temp)
            repo = Repository(root, discover=False)
            repo.init()
            (root / "Folder").mkdir()
            (root / "Folder/a.txt").write_bytes(b"a")
            repo.add(["Folder/a.txt"])
            commit_id, _ = repo.commit("folder")
            repo.remove(["Folder/a.txt"])
            repo.commit("empty")
            (root / "Folder/a.txt").unlink()
            (root / "Folder").rmdir()
            (root / "folder").mkdir()
            with self.assertRaises(PathError) as caught:
                repo.checkout(commit_id)
            self.assertIn("collides portably", str(caught.exception))

    def test_interrupted_checkout_rolls_back_and_pending_commands_refuse(self):
        with tempfile.TemporaryDirectory() as temp, working_directory(Path(temp)):
            root = Path(temp)
            repo, first, second = self.history(root)
            repo.checkout(first)
            old = repo.store.read_commit(first).files
            new = repo.store.read_commit(second).files
            changes = {name: {"before": old.get(name), "after": new.get(name)} for name in sorted(set(old) | set(new)) if old.get(name) != new.get(name)}
            journal = {"version": 1, "operation": "checkout", "old_head": first, "new_head": second, "old_index": {}, "changes": changes, "created_dirs": []}
            write_journal(repo.store, journal)
            atomic_write(root / "a.txt", repo.store.read_blob(new["a.txt"]), reject_hardlinks=False)
            with self.assertRaises(RecoveryError):
                repo.status()
            recovered, leftovers = repo.recover()
            self.assertTrue(recovered)
            self.assertEqual(leftovers, [])
            self.assertEqual((root / "a.txt").read_bytes(), b"one")
            self.assertFalse((root / "b.txt").exists())
            self.assertEqual(repo.store.read_head(), first)
            self.assertFalse(repo.store.transaction.exists())
            self.assertEqual(repo.recover(), (False, []))

    def test_recovery_preserves_third_party_edit_and_journal(self):
        with tempfile.TemporaryDirectory() as temp, working_directory(Path(temp)):
            root = Path(temp)
            repo, first, second = self.history(root)
            repo.checkout(first)
            old = repo.store.read_commit(first).files
            new = repo.store.read_commit(second).files
            changes = {name: {"before": old.get(name), "after": new.get(name)} for name in sorted(set(old) | set(new)) if old.get(name) != new.get(name)}
            journal = {"version": 1, "operation": "checkout", "old_head": first, "new_head": second, "old_index": {}, "changes": changes, "created_dirs": []}
            write_journal(repo.store, journal)
            (root / "a.txt").write_bytes(b"third-party")
            with self.assertRaises(RecoveryError):
                repo.recover()
            self.assertEqual((root / "a.txt").read_bytes(), b"third-party")
            self.assertTrue(repo.store.transaction.exists())


if __name__ == "__main__":
    unittest.main()
