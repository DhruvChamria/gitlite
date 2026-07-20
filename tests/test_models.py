import unittest

from gitlite.models import Commit


class CommitTests(unittest.TestCase):
    def test_hash_is_independent_of_file_insertion_order(self):
        left = Commit(None, "2026-01-01T00:00:00+00:00", "m", {"b": "2", "a": "1"})
        right = Commit(None, "2026-01-01T00:00:00+00:00", "m", {"a": "1", "b": "2"})
        self.assertEqual(left.compute_hash(), right.compute_hash())


if __name__ == "__main__":
    unittest.main()
