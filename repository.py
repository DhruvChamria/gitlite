from __future__ import annotations

import difflib
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Optional

from commit import Commit
from utils import ensure_dir, read_json, read_text, rel_path, sha1_bytes, write_json, write_text


class Repository:
    def __init__(self, root: Optional[Path] = None) -> None:
        self.root = (root or Path.cwd()).resolve()
        self.repo_dir = self.root / ".mygit"
        self.objects_dir = self.repo_dir / "objects"
        self.blobs_dir = self.objects_dir / "blobs"
        self.commits_dir = self.objects_dir / "commits"
        self.index_file = self.repo_dir / "index.json"
        self.head_file = self.repo_dir / "HEAD"

    def init(self) -> None:
        if self.repo_dir.exists():
            print("Repository already initialized.")
            return

        ensure_dir(self.blobs_dir)
        ensure_dir(self.commits_dir)
        write_json(self.index_file, {})
        write_text(self.head_file, "")

        print(f"Initialized empty GitLite repository in {self.repo_dir}")

    def _require_repo(self) -> None:
        if not self.repo_dir.exists():
            raise RuntimeError("Run `python main.py init` first.")

    def _read_head(self) -> Optional[str]:
        self._require_repo()
        head = read_text(self.head_file, "")
        return head or None

    def _write_head(self, commit_hash: str) -> None:
        write_text(self.head_file, commit_hash)

    def _read_index(self) -> Dict[str, str]:
        return read_json(self.index_file, default={}) or {}

    def _write_index(self, index_data: Dict[str, str]) -> None:
        write_json(self.index_file, index_data)

    def _blob_path(self, blob_hash: str) -> Path:
        return self.blobs_dir / blob_hash

    def _commit_path(self, commit_hash: str) -> Path:
        return self.commits_dir / f"{commit_hash}.json"

    def _save_blob(self, content: bytes) -> str:
        blob_hash = sha1_bytes(content)
        blob_path = self._blob_path(blob_hash)

        if not blob_path.exists():
            blob_path.write_bytes(content)

        return blob_hash

    def _load_commit(self, commit_hash: str) -> dict:
        path = self._commit_path(commit_hash)

        if not path.exists():
            raise RuntimeError(f"Commit not found: {commit_hash}")

        return read_json(path)

    def _head_snapshot(self) -> Dict[str, str]:
        head = self._read_head()

        if not head:
            return {}

        return self._load_commit(head)["files"]

    def add(self, filename: str) -> None:
        self._require_repo()

        file_path = (self.root / filename).resolve()

        if not file_path.exists():
            raise RuntimeError(f"File does not exist: {filename}")

        relative_name = rel_path(file_path, self.root)
        content = file_path.read_bytes()

        blob_hash = self._save_blob(content)

        index_data = self._read_index()
        index_data[relative_name] = blob_hash
        self._write_index(index_data)

        print(f"Staged {relative_name} as blob {blob_hash}")

    def commit(self, message: str) -> None:
        self._require_repo()

        index_data = self._read_index()

        if not index_data:
            raise RuntimeError("Nothing to commit.")

        parent = self._read_head()
        snapshot = self._head_snapshot()
        snapshot.update(index_data)

        commit = Commit(
            parent=parent,
            timestamp=datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
            message=message,
            files=snapshot,
        )

        commit_hash = commit.compute_hash()

        commit_path = self._commit_path(commit_hash)

        if not commit_path.exists():
            write_json(commit_path, {"hash": commit_hash, **commit.to_dict()})

        self._write_head(commit_hash)
        self._write_index({})

        print(f"Committed as {commit_hash}")

    def log(self) -> None:
        self._require_repo()

        commit_hash = self._read_head()

        if not commit_hash:
            print("No commits yet.")
            return

        while commit_hash:
            commit_data = self._load_commit(commit_hash)

            print(f"commit {commit_data['hash']}")
            print(f"Date:   {commit_data['timestamp']}")
            print(f"Message: {commit_data['message']}")
            print()

            commit_hash = commit_data.get("parent")

    def checkout(self, commit_hash: str) -> None:
        self._require_repo()

        commit_data = self._load_commit(commit_hash)
        target_snapshot = commit_data["files"]

        for path_str, blob_hash in target_snapshot.items():
            target_path = self.root / path_str
            ensure_dir(target_path.parent)

            target_path.write_bytes(
                self._blob_path(blob_hash).read_bytes()
            )

        self._write_head(commit_hash)
        self._write_index({})

        print(f"Checked out commit {commit_hash}")

    def diff(self, filename: str) -> None:
        self._require_repo()

        file_path = (self.root / filename).resolve()
        relative_name = rel_path(file_path, self.root)

        current_text = file_path.read_text(
            encoding="utf-8",
            errors="replace"
        ).splitlines()

        head_snapshot = self._head_snapshot()
        previous_text = []

        if relative_name in head_snapshot:
            blob_hash = head_snapshot[relative_name]
            previous_blob = self._blob_path(blob_hash)

            previous_text = previous_blob.read_text(
                encoding="utf-8",
                errors="replace"
            ).splitlines()

        diff_lines = list(
            difflib.unified_diff(
                previous_text,
                current_text,
                fromfile=f"{relative_name} (HEAD)",
                tofile=f"{relative_name} (working)",
                lineterm="",
            )
        )

        if not diff_lines:
            print("No differences found.")
            return

        print("".join(diff_lines))

    def status(self) -> None:
        self._require_repo()

        head = self._read_head()
        index_data = self._read_index()

        print("=== GitLite Status ===")
        print(f"HEAD: {head if head else 'No commits yet'}")
        print()

        print("Staged files:")

        if index_data:
            for path_str, blob_hash in index_data.items():
                print(f"  {path_str} -> {blob_hash}")
        else:
            print("  (none)")