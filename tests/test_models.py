import unittest
from pathlib import Path
import shutil
import tempfile

from gitlite.models import Commit
from gitlite.repository import Repository
from tests.helpers import working_directory


class CommitTests(unittest.TestCase):
    def test_hash_is_independent_of_file_insertion_order(self):
        left = Commit(None, "2026-01-01T00:00:00+00:00", "m", {"b": "2", "a": "1"})
        right = Commit(None, "2026-01-01T00:00:00+00:00", "m", {"a": "1", "b": "2"})
        self.assertEqual(left.compute_hash(), right.compute_hash())

    def test_legacy_fixture_hashes_load_without_migration(self):
        fixture = Path(__file__).parent / "fixtures" / "legacy"
        with tempfile.TemporaryDirectory() as temp, working_directory(Path(temp)):
            root = Path(temp)
            shutil.copytree(fixture, root / ".mygit")
            repo = Repository()
            item = repo.show()
            self.assertEqual(item["hash"], "e4d9c5a067fac131bc76d468c4614905b5ef87fd")
            self.assertEqual(item["files"]["legacy.txt"], "643102c60282f84dea8dbc74199b49848c958016")
            self.assertEqual(repo.fsck().errors, ())


if __name__ == "__main__":
    unittest.main()
