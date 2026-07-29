from pathlib import Path
import tempfile
import unittest

from gitlite.errors import PathError
from gitlite.paths import canonical_user_path, validate_snapshot, validate_stored_path
from gitlite.repository import Repository
from tests.helpers import working_directory


class PathTests(unittest.TestCase):
    def test_user_path_allows_safe_parent_but_rejects_escape_and_metadata(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            child = root / "child"
            child.mkdir()
            self.assertEqual(canonical_user_path(root, child, "../ok.txt")[0], "ok.txt")
            with self.assertRaises(PathError):
                canonical_user_path(root, child, "../../outside.txt")
            with self.assertRaises(PathError):
                canonical_user_path(root, root, ".mygit/HEAD")

    def test_stored_paths_are_portable(self):
        for value in ("../x", "x\\y", "/x", "CON.txt", "bad.", "a/.git/x", ".gitlite-tmp-x"):
            with self.subTest(value=value), self.assertRaises(PathError):
                validate_stored_path(value)
        self.assertEqual(validate_stored_path("Unicode folder/नमस्ते.txt"), "Unicode folder/नमस्ते.txt")

    def test_component_tree_collisions(self):
        validate_snapshot({"Folder/a": "x", "Folder/b": "y"})
        for snapshot in ({"Folder/a": "x", "folder/b": "y"}, {"A": "x", "a/b": "y"}):
            with self.assertRaises(PathError):
                validate_snapshot(snapshot)

    def test_production_guards_reject_symlink_and_allow_worktree_hardlink(self):
        with tempfile.TemporaryDirectory() as temp, working_directory(Path(temp)):
            root = Path(temp)
            repo = Repository(root, discover=False)
            repo.init()
            source = root / "source.txt"
            source.write_bytes(b"data")
            hard = root / "hard.txt"
            hard.hardlink_to(source)
            repo.add(["hard.txt"])
            link = root / "link.txt"
            try:
                link.symlink_to(source)
            except OSError as exc:
                self.skipTest(f"symlink creation unavailable: {exc}")
            with self.assertRaises(PathError):
                repo.add(["link.txt"])


if __name__ == "__main__":
    unittest.main()
