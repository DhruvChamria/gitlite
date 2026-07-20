from __future__ import annotations

import difflib
from datetime import datetime, timezone
from pathlib import Path

from .errors import RepositoryError
from .models import Commit, sha1_bytes
from .paths import discover_root
from .storage import read_json, write_json


class Repository:
    def __init__(self, root: Path | None = None, *, discover: bool = True) -> None:
        if root is None and discover:
            root = discover_root()
        self.root = (root or Path.cwd()).resolve()
        self.repo_dir = self.root / ".mygit"
        self.blobs_dir = self.repo_dir / "objects" / "blobs"
        self.commits_dir = self.repo_dir / "objects" / "commits"
        self.index_file = self.repo_dir / "index.json"
        self.head_file = self.repo_dir / "HEAD"

    def init(self) -> str:
        if self.repo_dir.exists():
            return "Repository already initialized."
        self.blobs_dir.mkdir(parents=True)
        self.commits_dir.mkdir(parents=True)
        write_json(self.index_file, {})
        self.head_file.write_text("", encoding="utf-8")
        return f"Initialized empty GitLite repository in {self.repo_dir}"

    def _require_repo(self) -> None:
        if not self.repo_dir.is_dir():
            raise RepositoryError("Not a GitLite repository. Run `gitlite init` first.")

    def _read_head(self) -> str | None:
        self._require_repo()
        value = self.head_file.read_text(encoding="utf-8").strip()
        return value or None

    def _read_index(self) -> dict[str, str]:
        return read_json(self.index_file, {}) or {}

    def _load_commit(self, commit_id: str) -> dict[str, object]:
        path = self.commits_dir / f"{commit_id}.json"
        if not path.exists():
            raise RepositoryError(f"Commit not found: {commit_id}")
        return read_json(path)

    def _snapshot(self) -> dict[str, str]:
        head = self._read_head()
        return {} if head is None else dict(self._load_commit(head)["files"])

    def add(self, paths: list[str]) -> list[str]:
        index = self._read_index()
        messages = []
        for name in paths:
            path = (Path.cwd() / name).resolve()
            if not path.is_file():
                raise RepositoryError(f"File does not exist: {name}")
            try:
                relative = path.relative_to(self.root).as_posix()
            except ValueError as exc:
                raise RepositoryError(f"Path is outside repository: {name}") from exc
            data = path.read_bytes()
            blob_id = sha1_bytes(data)
            blob_path = self.blobs_dir / blob_id
            if not blob_path.exists():
                blob_path.write_bytes(data)
            index[relative] = blob_id
            messages.append(f"Staged {relative} as blob {blob_id}")
        write_json(self.index_file, index)
        return messages

    def commit(self, message: str) -> tuple[str, str | None]:
        index = self._read_index()
        if not index:
            raise RepositoryError("Nothing to commit.")
        parent = self._read_head()
        snapshot = self._snapshot()
        snapshot.update(index)
        commit = Commit(parent, datetime.now(timezone.utc).isoformat(timespec="microseconds"), message, snapshot)
        commit_id = commit.compute_hash()
        write_json(self.commits_dir / f"{commit_id}.json", {"hash": commit_id, **commit.to_dict()})
        self.head_file.write_text(commit_id, encoding="utf-8")
        write_json(self.index_file, {})
        return commit_id, parent

    def log(self) -> list[dict[str, object]]:
        result = []
        commit_id = self._read_head()
        seen = set()
        while commit_id:
            if commit_id in seen:
                raise RepositoryError("Commit history contains a cycle.")
            seen.add(commit_id)
            commit = self._load_commit(commit_id)
            result.append(commit)
            commit_id = commit["parent"]
        return result

    def checkout(self, commit_id: str) -> str:
        commit = self._load_commit(commit_id)
        for name, blob_id in commit["files"].items():
            destination = self.root / name
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes((self.blobs_dir / blob_id).read_bytes())
        self.head_file.write_text(commit_id, encoding="utf-8")
        write_json(self.index_file, {})
        return commit_id

    def diff(self, name: str) -> str:
        path = (Path.cwd() / name).resolve()
        relative = path.relative_to(self.root).as_posix()
        current = path.read_text(encoding="utf-8", errors="replace").splitlines()
        snapshot = self._snapshot()
        previous = []
        if relative in snapshot:
            previous = (self.blobs_dir / snapshot[relative]).read_text(
                encoding="utf-8", errors="replace"
            ).splitlines()
        return "\n".join(difflib.unified_diff(previous, current, fromfile=f"{relative} (HEAD)", tofile=f"{relative} (working)", lineterm=""))

    def status(self) -> tuple[str | None, dict[str, str]]:
        return self._read_head(), self._read_index()
