from pathlib import Path
import tempfile
import unittest

from gitlite.errors import RepositoryError
from gitlite.repository import Repository
from tests.helpers import working_directory


class RepositoryTests(unittest.TestCase):
    def make_repo(self, root: Path) -> Repository:
        repo = Repository(root, discover=False)
        repo.init()
        return repo

    def test_h_i_w_status_matrix_and_staged_bytes(self):
        with tempfile.TemporaryDirectory() as temp, working_directory(Path(temp)):
            root = Path(temp)
            repo = self.make_repo(root)
            (root / "tracked.txt").write_bytes(b"one")
            repo.add(["tracked.txt"])
            repo.commit("initial")
            (root / "tracked.txt").write_bytes(b"two")
            repo.add(["tracked.txt"])
            (root / "tracked.txt").write_bytes(b"three")
            (root / "new.txt").write_bytes(b"new")
            repo.add(["new.txt"])
            (root / "new.txt").write_bytes(b"changed")
            self.assertEqual(repo.status().rows, ("AM new.txt", "MM tracked.txt"))
            commit_id, _ = repo.commit("second")
            self.assertEqual(repo.store.read_commit(commit_id).files["tracked.txt"], repo.store.save_blob(b"two"))

    def test_rm_keeps_file_and_unstage_is_batch_atomic(self):
        with tempfile.TemporaryDirectory() as temp, working_directory(Path(temp)):
            root = Path(temp)
            repo = self.make_repo(root)
            (root / "a.txt").write_bytes(b"a")
            repo.add(["a.txt"])
            repo.commit("initial")
            repo.remove(["a.txt"])
            self.assertTrue((root / "a.txt").exists())
            self.assertEqual(repo.status().rows, ("D  a.txt", "?? a.txt"))
            before = repo.store.index.read_bytes()
            with self.assertRaises(RepositoryError):
                repo.unstage(["a.txt", "missing.txt"])
            self.assertEqual(repo.store.index.read_bytes(), before)
            repo.unstage(["a.txt"])
            self.assertEqual(repo.status().rows, ())

    def test_staged_new_then_rm_and_noop_commit(self):
        with tempfile.TemporaryDirectory() as temp, working_directory(Path(temp)):
            root = Path(temp)
            repo = self.make_repo(root)
            (root / "a.txt").write_bytes(b"a")
            repo.add(["a.txt"])
            repo.remove(["a.txt"])
            self.assertEqual(repo.store.read_index(), {})
            with self.assertRaises(RepositoryError):
                repo.commit("nothing")

    def test_missing_tracked_add_stages_deletion_and_readd_clears_it(self):
        with tempfile.TemporaryDirectory() as temp, working_directory(Path(temp)):
            root = Path(temp)
            repo = self.make_repo(root)
            path = root / "a.txt"
            path.write_bytes(b"a")
            repo.add(["a.txt"])
            repo.commit("initial")
            path.unlink()
            repo.add(["a.txt"])
            self.assertIsNone(repo.store.read_index()["a.txt"])
            path.write_bytes(b"a")
            repo.add(["a.txt"])
            self.assertEqual(repo.store.read_index(), {})


if __name__ == "__main__":
    unittest.main()
