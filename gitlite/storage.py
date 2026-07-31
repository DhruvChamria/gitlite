from __future__ import annotations

from contextlib import contextmanager
import json
import os
from pathlib import Path
import sys
import tempfile
from typing import Any, Iterator

from .errors import CorruptionError, LockError, RepositoryError
from .models import Commit, sha1_bytes
from .paths import RESERVED_PREFIX, ensure_no_links, is_link_like, validate_snapshot, validate_stored_path


def validate_id(value: object, label: str = "object ID") -> str:
    if not isinstance(value, str) or len(value) != 40 or value != value.lower() or any(c not in "0123456789abcdef" for c in value):
        raise CorruptionError(f"Invalid {label}: {value!r}")
    return value


def _reject_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result = {}
    for key, value in pairs:
        if key in result:
            raise CorruptionError(f"Duplicate JSON key: {key}")
        result[key] = value
    return result


def read_json(path: Path) -> Any:
    try:
        ensure_no_links(path, stop=path.parent)
        if path.stat().st_nlink > 1:
            raise CorruptionError(f"Hard-linked metadata file is unsupported: {path.name}")
        with path.open("r", encoding="utf-8") as handle:
            return json.load(handle, object_pairs_hook=_reject_duplicates)
    except FileNotFoundError as exc:
        raise CorruptionError(f"Missing required metadata: {path.name}") from exc
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise CorruptionError(f"Malformed JSON in {path.name}: {exc}") from exc


def atomic_write(path: Path, data: bytes, *, reject_hardlinks: bool = True) -> None:
    ensure_no_links(path.parent, stop=path.parent)
    if path.exists() or is_link_like(path):
        ensure_no_links(path, stop=path.parent)
        if reject_hardlinks and path.stat().st_nlink > 1:
            raise RepositoryError(f"Refusing to replace hard-linked metadata: {path.name}")
    handle = tempfile.NamedTemporaryFile(prefix=".gitlite-tmp-", dir=path.parent, delete=False)
    temp = Path(handle.name)
    try:
        with handle:
            handle.write(data)
            handle.flush()
            if sys.platform != "emscripten":
                os.fsync(handle.fileno())
        os.replace(temp, path)
    except BaseException:
        try:
            temp.unlink()
        except FileNotFoundError:
            pass
        raise


def atomic_json(path: Path, value: Any) -> None:
    atomic_write(path, json.dumps(value, indent=2, sort_keys=True).encode("utf-8"))


class RepositoryLock:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.handle = None

    def __enter__(self):
        if self.path.exists() or is_link_like(self.path):
            ensure_no_links(self.path, stop=self.path.parent)
            if not self.path.is_file() or self.path.stat().st_nlink > 1:
                raise LockError("Repository lock path is unsafe.")
        else:
            self.path.write_bytes(b"0")
        self.handle = self.path.open("r+b", buffering=0)
        try:
            if sys.platform == "emscripten":
                return self
            self.handle.seek(0)
            if os.name == "nt":
                import msvcrt
                msvcrt.locking(self.handle.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(self.handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            self.handle.close()
            self.handle = None
            raise LockError("Repository is busy; another GitLite command holds the lock.") from exc
        return self

    def __exit__(self, exc_type, exc, tb):
        if self.handle is None:
            return
        try:
            if sys.platform == "emscripten":
                return
            self.handle.seek(0)
            if os.name == "nt":
                import msvcrt
                msvcrt.locking(self.handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl
                fcntl.flock(self.handle.fileno(), fcntl.LOCK_UN)
        finally:
            self.handle.close()


class Store:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.repo = root / ".mygit"
        self.objects = self.repo / "objects"
        self.blobs = self.objects / "blobs"
        self.commits = self.objects / "commits"
        self.head = self.repo / "HEAD"
        self.index = self.repo / "index.json"
        self.lock_path = self.repo / "LOCK"
        self.transaction = self.repo / "transaction.json"

    @classmethod
    def initialize(cls, root: Path) -> tuple["Store", bool]:
        store = cls(root)
        if store.repo.exists() or is_link_like(store.repo):
            if is_link_like(store.repo) or not store.repo.is_dir():
                raise RepositoryError("Existing .mygit is unsafe or incomplete; move it aside after inspection, then retry init.")
            store.validate_structure()
            with store.locked():
                store.validate_structure()
            return store, False
        try:
            store.repo.mkdir(exist_ok=False)
        except FileExistsError as exc:
            raise RepositoryError("Concurrent initialization left .mygit busy or incomplete; inspect it before retrying.") from exc
        store.lock_path.write_bytes(b"0")
        with RepositoryLock(store.lock_path):
            store.blobs.mkdir(parents=True)
            store.commits.mkdir(parents=True)
            atomic_write(store.head, b"")
            atomic_json(store.index, {})
        return store, True

    def validate_structure(self) -> None:
        ensure_no_links(self.repo, stop=self.root)
        for directory in (self.repo, self.objects, self.blobs, self.commits):
            if not directory.is_dir() or is_link_like(directory):
                raise CorruptionError(f"Incomplete repository: missing safe directory {directory.relative_to(self.root)}. Move .mygit aside after inspection, then rerun init.")
        for file in (self.head, self.index):
            if not file.is_file() or is_link_like(file) or file.stat().st_nlink > 1:
                raise CorruptionError(f"Incomplete repository: missing safe file {file.relative_to(self.root)}. Move .mygit aside after inspection, then rerun init.")

    @contextmanager
    def locked(self) -> Iterator[None]:
        self.validate_structure()
        with RepositoryLock(self.lock_path):
            yield

    @contextmanager
    def diagnostic_lock(self) -> Iterator[None]:
        if not self.repo.is_dir() or is_link_like(self.repo):
            raise CorruptionError("Repository metadata directory is missing or unsafe.")
        ensure_no_links(self.repo, stop=self.root)
        with RepositoryLock(self.lock_path):
            yield

    def read_head(self) -> str | None:
        if not self.head.is_file() or is_link_like(self.head) or self.head.stat().st_nlink > 1:
            raise CorruptionError("HEAD is missing or unsafe.")
        raw = self.head.read_text(encoding="utf-8").strip()
        return None if raw == "" else validate_id(raw, "HEAD")

    def write_head(self, value: str | None) -> None:
        atomic_write(self.head, b"" if value is None else validate_id(value).encode("ascii"))

    def read_index(self) -> dict[str, str | None]:
        value = read_json(self.index)
        if not isinstance(value, dict):
            raise CorruptionError("Index must be a JSON object.")
        for name, blob in value.items():
            validate_stored_path(name)
            if blob is not None:
                validate_id(blob, f"index blob for {name}")
        validate_snapshot(value)
        return dict(value)

    def write_index(self, value: dict[str, str | None]) -> None:
        validate_snapshot(value)
        atomic_json(self.index, value)

    def save_blob(self, data: bytes) -> str:
        blob_id = sha1_bytes(data)
        path = self.blobs / blob_id
        if path.exists():
            if self.read_blob(blob_id) != data:
                raise CorruptionError(f"Existing blob {blob_id} is corrupt.")
        else:
            atomic_write(path, data)
        return blob_id

    def read_blob(self, blob_id: str) -> bytes:
        validate_id(blob_id, "blob ID")
        path = self.blobs / blob_id
        if not path.is_file() or is_link_like(path):
            raise CorruptionError(f"Missing blob: {blob_id}")
        data = path.read_bytes()
        if sha1_bytes(data) != blob_id:
            raise CorruptionError(f"Blob content does not match its ID: {blob_id}")
        return data

    def save_commit(self, commit: Commit) -> str:
        commit_id = commit.compute_hash()
        path = self.commits / f"{commit_id}.json"
        value = {"hash": commit_id, **commit.to_dict()}
        if path.exists():
            if self.read_commit(commit_id) != commit:
                raise CorruptionError(f"Existing commit {commit_id} is corrupt.")
        else:
            atomic_json(path, value)
        return commit_id

    def read_commit(self, commit_id: str) -> Commit:
        validate_id(commit_id, "commit ID")
        path = self.commits / f"{commit_id}.json"
        if not path.is_file() or is_link_like(path):
            raise CorruptionError(f"Commit not found: {commit_id}")
        commit = Commit.from_stored(read_json(path), expected_hash=commit_id)
        if commit.parent is not None:
            validate_id(commit.parent, f"parent of {commit_id}")
        for name, blob_id in commit.files.items():
            validate_stored_path(name)
            validate_id(blob_id, f"blob for {name}")
        validate_snapshot(commit.files)
        return commit
