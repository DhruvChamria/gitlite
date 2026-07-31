from __future__ import annotations

import difflib
from datetime import datetime, timezone
import os
from pathlib import Path
import stat

from .errors import ConflictError, CorruptionError, PathError, RecoveryError, RepositoryError
from .models import Commit, IntegrityResult, StatusResult
from .models import sha1_bytes
from .paths import EXCLUDED_DIRS, canonical_user_path, discover_root, ensure_no_links, ensure_portable_existing_path, is_excluded, is_link_like, validate_snapshot
from .storage import Store, atomic_write
from .transactions import load_journal, rollback, write_journal


class Repository:
    def __init__(self, root: Path | None = None, *, discover: bool = True) -> None:
        if root is None and discover:
            root = discover_root()
        self.root = (root or Path.cwd()).absolute()
        self.store = Store(self.root)

    def init(self) -> str:
        if not (self.store.repo.exists() or is_link_like(self.store.repo)):
            for parent in self.root.parents:
                marker = parent / ".mygit"
                if marker.exists() or is_link_like(marker):
                    raise RepositoryError(f"Refusing to initialize a nested repository inside {parent}.")
        store, created = Store.initialize(self.root)
        if store.transaction.exists():
            raise RecoveryError("Interrupted operation detected. Run `gitlite recover` before continuing.")
        return (f"Initialized empty GitLite repository in {self.store.repo}" if created else "Repository already initialized.")

    def _snapshot_unlocked(self) -> dict[str, str]:
        head = self.store.read_head()
        if head is None:
            return {}
        commit = self.store.read_commit(head)
        for blob_id in commit.files.values():
            self.store.read_blob(blob_id)
        return dict(commit.files)

    def _ensure_ready(self) -> None:
        if self.store.transaction.exists():
            raise RecoveryError("Interrupted operation detected. Run `gitlite recover` before continuing.")

    @staticmethod
    def _effective(head: dict[str, str], index: dict[str, str | None]) -> dict[str, str]:
        result = dict(head)
        for name, blob_id in index.items():
            if blob_id is None:
                result.pop(name, None)
            else:
                result[name] = blob_id
        return result

    def add(self, paths: list[str]) -> list[str]:
        with self.store.locked():
            self._ensure_ready()
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
            effective = self._effective(head_snapshot, proposed)
            validate_snapshot(effective)
            self.store.write_index(proposed)
            return messages

    def remove(self, paths: list[str]) -> list[str]:
        with self.store.locked():
            self._ensure_ready()
            head = self._snapshot_unlocked()
            index = self.store.read_index()
            names = list(dict.fromkeys(canonical_user_path(self.root, Path.cwd(), raw)[0] for raw in paths))
            for name in names:
                if name not in head and name not in index:
                    raise RepositoryError(f"Path is not tracked or staged: {name}")
            proposed = dict(index)
            messages = []
            for name in names:
                if name in head:
                    proposed[name] = None
                else:
                    proposed.pop(name, None)
                messages.append(f"Staged removal (working file kept): {name}")
            validate_snapshot(self._effective(head, proposed))
            self.store.write_index(proposed)
            return messages

    def unstage(self, paths: list[str]) -> list[str]:
        with self.store.locked():
            self._ensure_ready()
            index = self.store.read_index()
            names = list(dict.fromkeys(canonical_user_path(self.root, Path.cwd(), raw)[0] for raw in paths))
            missing = [name for name in names if name not in index]
            if missing:
                raise RepositoryError(f"Path is not staged: {missing[0]}")
            proposed = dict(index)
            for name in names:
                proposed.pop(name)
            self.store.write_index(proposed)
            return [f"Unstaged (working file kept): {name}" for name in names]

    def commit(self, message: str) -> tuple[str, str | None]:
        if not message.strip():
            raise RepositoryError("Commit message must not be blank.")
        with self.store.locked():
            self._ensure_ready()
            index = self.store.read_index()
            if not index:
                raise RepositoryError("Nothing to commit.")
            parent = self.store.read_head()
            snapshot = self._effective(self._snapshot_unlocked(), index)
            for blob_id in snapshot.values():
                self.store.read_blob(blob_id)
            validate_snapshot(snapshot)
            commit = Commit(parent, datetime.now(timezone.utc).isoformat(timespec="microseconds"), message, snapshot)
            commit_id = self.store.save_commit(commit)
            journal = {
                "version": 1,
                "operation": "commit",
                "old_head": parent,
                "new_head": commit_id,
                "old_index": index,
                "changes": {},
                "created_dirs": [],
            }
            write_journal(self.store, journal)
            try:
                self.store.write_head(commit_id)
                self.store.write_index({})
                self.store.transaction.unlink()
            except BaseException:
                try:
                    rollback(self.store, journal)
                except BaseException as recovery_error:
                    raise RecoveryError("Commit failed and automatic rollback could not finish; run `gitlite recover`.") from recovery_error
                raise
            return commit_id, parent

    def log(self, *, all_commits: bool = False) -> list[dict[str, object]]:
        with self.store.locked():
            self._ensure_ready()
            if all_commits:
                result = []
                head = self.store.read_head()
                commits: dict[str, Commit] = {}
                for path in self.store.commits.iterdir():
                    if path.name.startswith(".gitlite-tmp-"):
                        continue
                    if not path.is_file() or not path.name.endswith(".json"):
                        raise CorruptionError(f"Invalid commit object filename: {path.name}; run `gitlite fsck`.")
                    commit_id = path.name[:-5]
                    commit = self.store.read_commit(commit_id)
                    commits[commit_id] = commit
                    result.append({"hash": commit_id, "is_head": commit_id == head, **commit.to_dict()})
                for commit_id, commit in commits.items():
                    if commit.parent is not None and commit.parent not in commits:
                        raise CorruptionError(f"Commit {commit_id} references missing parent {commit.parent}; run `gitlite fsck`.")
                    for name, blob_id in commit.files.items():
                        try:
                            self.store.read_blob(blob_id)
                        except CorruptionError as exc:
                            raise CorruptionError(f"Commit {commit_id} path {name} references an invalid blob; run `gitlite fsck`.") from exc
                result.sort(key=lambda item: item["hash"])
                result.sort(key=lambda item: datetime.fromisoformat(item["timestamp"]), reverse=True)
                return result
            result = []
            commit_id = self.store.read_head()
            seen = set()
            while commit_id:
                if commit_id in seen:
                    raise CorruptionError("Commit history contains a cycle; run `gitlite fsck`.")
                seen.add(commit_id)
                commit = self.store.read_commit(commit_id)
                for blob_id in commit.files.values():
                    self.store.read_blob(blob_id)
                result.append({"hash": commit_id, **commit.to_dict()})
                commit_id = commit.parent
            return result

    def show(self, commit_id: str | None = None) -> dict[str, object]:
        with self.store.locked():
            self._ensure_ready()
            selected = commit_id or self.store.read_head()
            if selected is None:
                raise RepositoryError("No commits yet.")
            commit = self.store.read_commit(selected)
            if commit.parent is not None:
                try:
                    self.store.read_commit(commit.parent)
                except CorruptionError as exc:
                    raise CorruptionError(f"Commit {selected} references missing parent {commit.parent}; run `gitlite fsck`.") from exc
            for name, blob_id in commit.files.items():
                try:
                    self.store.read_blob(blob_id)
                except CorruptionError as exc:
                    raise CorruptionError(f"Commit {selected} path {name} references an invalid blob; run `gitlite fsck`.") from exc
            return {"hash": selected, **commit.to_dict()}

    def checkout(self, commit_id: str) -> str:
        with self.store.locked():
            self._ensure_ready()
            old_head = self.store.read_head()
            old = self._snapshot_unlocked()
            target_commit = self.store.read_commit(commit_id)
            target = dict(target_commit.files)
            for blob_id in target.values():
                self.store.read_blob(blob_id)
            index = self.store.read_index()
            if index:
                raise ConflictError("Checkout requires an empty staging index; commit or unstage changes first.")
            dirty = []
            for name, blob_id in old.items():
                _, path = canonical_user_path(self.root, self.root, name)
                if not path.is_file() or self.store.read_blob(blob_id) != path.read_bytes():
                    dirty.append(name)
            if dirty:
                raise ConflictError("Checkout refused modified or missing tracked files: " + ", ".join(dirty))
            validate_snapshot({**old, **target})
            for name in sorted(set(old) | set(target)):
                ensure_portable_existing_path(self.root, name)
            changes = {
                name: {"before": old.get(name), "after": target.get(name)}
                for name in sorted(set(old) | set(target))
                if old.get(name) != target.get(name)
            }
            created_dirs = set()
            for name, change in changes.items():
                path = self.root / Path(*name.split("/"))
                if change["after"] is not None and change["before"] is None and (path.exists() or is_link_like(path)):
                    raise ConflictError(f"Checkout target collides with an untracked entry: {name}")
                parent = path.parent
                while parent != self.root and not parent.exists():
                    created_dirs.add(parent.relative_to(self.root).as_posix())
                    parent = parent.parent
                if parent != self.root and (is_link_like(parent) or not parent.is_dir()):
                    raise ConflictError(f"Checkout target has an obstructing ancestor: {name}")
            journal = {
                "version": 1,
                "operation": "checkout",
                "old_head": old_head,
                "new_head": commit_id,
                "old_index": {},
                "changes": changes,
                "created_dirs": sorted(created_dirs),
            }
            write_journal(self.store, journal)
            try:
                for directory in sorted(created_dirs, key=lambda value: value.count("/")):
                    (self.root / Path(*directory.split("/"))).mkdir(exist_ok=True)
                for name, change in changes.items():
                    path = self.root / Path(*name.split("/"))
                    canonical_user_path(self.root, self.root, name)
                    before = change["before"]
                    current = sha1_bytes(path.read_bytes()) if path.is_file() else None
                    if current != before:
                        raise ConflictError(f"File changed during checkout: {name}")
                    after = change["after"]
                    if after is None:
                        path.unlink()
                    else:
                        atomic_write(path, self.store.read_blob(after), reject_hardlinks=False)
                self.store.write_head(commit_id)
                self.store.write_index({})
                self.store.transaction.unlink()
            except BaseException:
                try:
                    rollback(self.store, journal)
                except BaseException as recovery_error:
                    raise RecoveryError("Checkout failed and automatic rollback could not finish; run `gitlite recover`.") from recovery_error
                raise
            return commit_id

    def recover(self) -> tuple[bool, list[str]]:
        with self.store.locked():
            if not self.store.transaction.exists():
                self.store.read_head()
                self.store.read_index()
                return False, []
            journal = load_journal(self.store)
            return True, rollback(self.store, journal)

    def fsck(self) -> IntegrityResult:
        errors: list[str] = []
        information: list[str] = []
        commits: dict[str, Commit] = {}
        blobs: set[str] = set()
        head: str | None = None
        index: dict[str, str | None] = {}
        with self.store.diagnostic_lock():
            safe_directories: dict[Path, bool] = {}
            for directory, label in ((self.store.objects, "objects"), (self.store.blobs, "blob"), (self.store.commits, "commit")):
                try:
                    ensure_no_links(directory, stop=self.root)
                    safe = directory.is_dir()
                except PathError:
                    safe = False
                safe_directories[directory] = safe
                if not safe:
                    errors.append(f"Missing or unsafe {label} directory: {directory.relative_to(self.root)}")
            try:
                head = self.store.read_head()
            except Exception as exc:
                errors.append(f"HEAD: {exc}")
            try:
                index = self.store.read_index()
                for name, blob in index.items():
                    if blob is not None:
                        try:
                            self.store.read_blob(blob)
                        except Exception as exc:
                            errors.append(f"index {name}: {exc}")
            except Exception as exc:
                errors.append(f"index.json: {exc}")
            if safe_directories[self.store.blobs]:
                for path in sorted(self.store.blobs.iterdir(), key=lambda item: item.name):
                    if path.name.startswith(".gitlite-tmp-"):
                        information.append(f"Interruption residue preserved: objects/blobs/{path.name}")
                        continue
                    try:
                        self.store.read_blob(path.name)
                        blobs.add(path.name)
                    except Exception as exc:
                        errors.append(f"blob {path.name}: {exc}")
            if safe_directories[self.store.commits]:
                for path in sorted(self.store.commits.iterdir(), key=lambda item: item.name):
                    if path.name.startswith(".gitlite-tmp-"):
                        information.append(f"Interruption residue preserved: objects/commits/{path.name}")
                        continue
                    if not path.name.endswith(".json"):
                        errors.append(f"Invalid commit object filename: {path.name}")
                        continue
                    commit_id = path.name[:-5]
                    try:
                        commits[commit_id] = self.store.read_commit(commit_id)
                    except Exception as exc:
                        errors.append(f"commit {commit_id}: {exc}")
            for commit_id, commit in commits.items():
                if commit.parent is not None and commit.parent not in commits:
                    errors.append(f"commit {commit_id}: missing parent {commit.parent}")
                for name, blob in commit.files.items():
                    if blob not in blobs:
                        errors.append(f"commit {commit_id} path {name}: missing or corrupt blob {blob}")
            complete: set[str] = set()
            for start in sorted(commits):
                if start in complete:
                    continue
                trail: list[str] = []
                positions: dict[str, int] = {}
                current: str | None = start
                while current is not None and current in commits and current not in complete:
                    if current in positions:
                        cycle = trail[positions[current]:] + [current]
                        errors.append("Commit parent cycle: " + " -> ".join(cycle))
                        break
                    positions[current] = len(trail)
                    trail.append(current)
                    current = commits[current].parent
                complete.update(trail)
            if head is not None and head not in commits:
                errors.append(f"HEAD references missing or corrupt commit {head}")
            if self.store.transaction.exists():
                try:
                    load_journal(self.store)
                    errors.append("Pending transaction requires `gitlite recover`.")
                except Exception as exc:
                    errors.append(f"transaction.json: {exc}")
            referenced = {blob for commit in commits.values() for blob in commit.files.values()}
            referenced.update(blob for blob in index.values() if blob is not None)
            for blob in sorted(blobs - referenced):
                information.append(f"Unreachable blob retained: {blob}")
            if head is not None:
                reachable = set()
                current = head
                while current in commits and current not in reachable:
                    reachable.add(current)
                    current = commits[current].parent
                for commit_id in sorted(set(commits) - reachable):
                    information.append(f"Unreachable commit retained: {commit_id}")
        return IntegrityResult(len(commits), len(blobs), tuple(sorted(set(errors))), tuple(sorted(set(information))))

    @staticmethod
    def _render_diff(name: str, before: bytes | None, after: bytes | None) -> str:
        if before is None and after == b"":
            return f"Added empty file: {name}"
        if before == b"" and after is None:
            return f"Deleted empty file: {name}"
        if before is None:
            before_data = b""
        else:
            before_data = before
        if after is None:
            after_data = b""
        else:
            after_data = after
        if before is not None and after is not None and before_data == after_data:
            return ""
        if b"\0" in before_data or b"\0" in after_data:
            return f"Binary files differ: {name}"
        try:
            before_text = before_data.decode("utf-8")
            after_text = after_data.decode("utf-8")
        except UnicodeDecodeError:
            return f"Binary files differ: {name}"
        fromfile = "/dev/null" if before is None else f"a/{name}"
        tofile = "/dev/null" if after is None else f"b/{name}"
        lines = list(difflib.unified_diff(
            before_text.splitlines(keepends=True),
            after_text.splitlines(keepends=True),
            fromfile=fromfile,
            tofile=tofile,
            lineterm="\n",
        ))
        if not lines:
            return f"Line endings differ: {name}"
        rendered = "".join(line if line.endswith("\n") else line + "\n" for line in lines).rstrip("\n")
        if (before_data and not before_data.endswith((b"\n", b"\r"))) or (after_data and not after_data.endswith((b"\n", b"\r"))):
            rendered += "\n\\ No newline at end of file"
        return rendered

    def diff(self, name: str | None = None, *, staged: bool = False) -> str:
        with self.store.locked():
            self._ensure_ready()
            head = self._snapshot_unlocked()
            effective = self._effective(head, self.store.read_index())
            selected: list[str]
            explicit_path = None
            if name is not None:
                explicit_path, path = canonical_user_path(self.root, Path.cwd(), name)
                known = explicit_path in head or explicit_path in effective
                if staged and not known:
                    raise RepositoryError(f"Path is not tracked or staged: {explicit_path}")
                if not staged and not known and not path.is_file():
                    raise RepositoryError(f"Path does not exist and is not tracked: {explicit_path}")
                selected = [explicit_path]
            else:
                selected = sorted(set(head) | set(effective))
            output = []
            for path_name in selected:
                before = self.store.read_blob(head[path_name]) if path_name in head else None
                if staged:
                    after = self.store.read_blob(effective[path_name]) if path_name in effective else None
                else:
                    path = self.root / Path(*path_name.split("/"))
                    canonical_user_path(self.root, self.root, path_name)
                    after = path.read_bytes() if path.is_file() else None
                rendered = self._render_diff(path_name, before, after)
                if rendered:
                    output.append(rendered)
            return "\n\n".join(output)

    def _scan_worktree(self) -> tuple[dict[str, bytes], list[str]]:
        regular: dict[str, bytes] = {}
        unsupported: list[str] = []

        def walk(directory: Path, prefix: tuple[str, ...] = ()) -> None:
            with os.scandir(directory) as entries:
                for entry in entries:
                    folded = entry.name.casefold()
                    relative_parts = (*prefix, entry.name)
                    name = "/".join(relative_parts)
                    try:
                        info = entry.stat(follow_symlinks=False)
                    except OSError:
                        unsupported.append(name)
                        continue
                    if stat.S_ISDIR(info.st_mode) and not is_link_like(Path(entry.path)):
                        if folded not in EXCLUDED_DIRS:
                            walk(Path(entry.path), relative_parts)
                    elif stat.S_ISREG(info.st_mode) and not is_link_like(Path(entry.path)):
                        if not is_excluded(name):
                            regular[name] = Path(entry.path).read_bytes()
                    elif folded not in EXCLUDED_DIRS and not is_excluded(name):
                        unsupported.append(name)

        walk(self.root)
        return regular, unsupported

    def status(self) -> StatusResult:
        with self.store.locked():
            self._ensure_ready()
            head_id = self.store.read_head()
            head = self._snapshot_unlocked()
            index = self.store.read_index()
            effective = self._effective(head, index)
            regular, unsupported = self._scan_worktree()
            rows: list[str] = []
            for name in sorted(set(head) | set(effective)):
                before = head.get(name)
                staged = effective.get(name)
                first = " "
                if before is None and staged is not None:
                    first = "A"
                elif before is not None and staged is None:
                    first = "D"
                elif before != staged:
                    first = "M"
                second = " "
                if staged is not None:
                    data = regular.get(name)
                    if data is None:
                        second = "D"
                    elif sha1_bytes(data) != staged:
                        second = "M"
                if first != " " or second != " ":
                    rows.append(f"{first}{second} {name}")
            for name in sorted(set(regular) - set(effective)):
                rows.append(f"?? {name}")
            for name in sorted(unsupported):
                rows.append(f"!! {name}")
            return StatusResult(head_id, tuple(rows))
