from __future__ import annotations

import difflib
from datetime import datetime, timezone
from pathlib import Path

from .errors import CorruptionError, PathError, RepositoryError
from .models import Commit
from .paths import canonical_user_path, discover_root, is_excluded, validate_snapshot
from .storage import Store


class Repository:
    def __init__(self, root: Path | None = None, *, discover: bool = True) -> None:
        if root is None and discover:
            root = discover_root()
        self.root = (root or Path.cwd()).absolute()
        self.store = Store(self.root)

    def init(self) -> str:
        _, created = Store.initialize(self.root)
        return (f"Initialized empty GitLite repository in {self.store.repo}" if created else "Repository already initialized.")

    def _snapshot_unlocked(self) -> dict[str, str]:
        head = self.store.read_head()
        if head is None:
            return {}
        commit = self.store.read_commit(head)
        for blob_id in commit.files.values():
            self.store.read_blob(blob_id)
        return dict(commit.files)

    def add(self, paths: list[str]) -> list[str]:
        with self.store.locked():
            head_snapshot = self._snapshot_unlocked()
            index = self.store.read_index()
            updates: list[tuple[str, Path | None, bytes | None]] = []
            for raw in paths:
                name, path = canonical_user_path(self.root, Path.cwd(), raw)
                if path.exists():
                    if not path.is_file():
                        raise PathError(f"Not a regular file: {raw}")
                    if is_excluded(name) and name not in head_snapshot:
                        raise PathError(f"Excluded path cannot be added: {name}")
                    updates.append((name, path, path.read_bytes()))
                elif name in head_snapshot:
                    updates.append((name, None, None))
                else:
                    raise PathError(f"File does not exist and is not tracked: {raw}")
            proposed = dict(index)
            messages = []
            for name, _, data in updates:
                if data is None:
                    proposed[name] = None
                    messages.append(f"Staged deletion: {name}")
                else:
                    blob_id = self.store.save_blob(data)
                    if head_snapshot.get(name) == blob_id:
                        proposed.pop(name, None)
                        messages.append(f"Unstaged unchanged file: {name}")
                    else:
                        proposed[name] = blob_id
                        messages.append(f"Staged {name} as blob {blob_id}")
            effective = dict(head_snapshot)
            for name, blob_id in proposed.items():
                if blob_id is None:
                    effective.pop(name, None)
                else:
                    effective[name] = blob_id
            validate_snapshot(effective)
            self.store.write_index(proposed)
            return messages

    def commit(self, message: str) -> tuple[str, str | None]:
        if not message.strip():
            raise RepositoryError("Commit message must not be blank.")
        with self.store.locked():
            index = self.store.read_index()
            if not index:
                raise RepositoryError("Nothing to commit.")
            parent = self.store.read_head()
            snapshot = self._snapshot_unlocked()
            for name, blob_id in index.items():
                if blob_id is None:
                    snapshot.pop(name, None)
                else:
                    self.store.read_blob(blob_id)
                    snapshot[name] = blob_id
            validate_snapshot(snapshot)
            commit = Commit(parent, datetime.now(timezone.utc).isoformat(timespec="microseconds"), message, snapshot)
            commit_id = self.store.save_commit(commit)
            self.store.write_head(commit_id)
            self.store.write_index({})
            return commit_id, parent

    def log(self) -> list[dict[str, object]]:
        with self.store.locked():
            result = []
            commit_id = self.store.read_head()
            seen = set()
            while commit_id:
                if commit_id in seen:
                    raise CorruptionError("Commit history contains a cycle; run `gitlite fsck`.")
                seen.add(commit_id)
                commit = self.store.read_commit(commit_id)
                result.append({"hash": commit_id, **commit.to_dict()})
                commit_id = commit.parent
            return result

    def checkout(self, commit_id: str) -> str:
        with self.store.locked():
            commit = self.store.read_commit(commit_id)
            for name, blob_id in commit.files.items():
                data = self.store.read_blob(blob_id)
                _, destination = canonical_user_path(self.root, self.root, name)
                destination.parent.mkdir(parents=True, exist_ok=True)
                destination.write_bytes(data)
            self.store.write_head(commit_id)
            self.store.write_index({})
            return commit_id

    def diff(self, name: str) -> str:
        with self.store.locked():
            path_name, path = canonical_user_path(self.root, Path.cwd(), name)
            if not path.is_file():
                raise RepositoryError(f"File does not exist: {name}")
            current = path.read_text(encoding="utf-8", errors="replace").splitlines()
            snapshot = self._snapshot_unlocked()
            previous = []
            if path_name in snapshot:
                previous = self.store.read_blob(snapshot[path_name]).decode("utf-8", errors="replace").splitlines()
            return "\n".join(difflib.unified_diff(previous, current, fromfile=f"{path_name} (HEAD)", tofile=f"{path_name} (working)", lineterm=""))

    def status(self) -> tuple[str | None, dict[str, str | None]]:
        with self.store.locked():
            return self.store.read_head(), self.store.read_index()
