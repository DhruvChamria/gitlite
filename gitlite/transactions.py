from __future__ import annotations

from pathlib import Path

from .errors import CorruptionError, RecoveryError
from .models import sha1_bytes
from .paths import ensure_no_links, validate_snapshot, validate_stored_path
from .storage import Store, atomic_json, atomic_write, read_json, validate_id


KEYS = {"version", "operation", "old_head", "new_head", "old_index", "changes", "created_dirs"}


def write_journal(store: Store, value: dict) -> None:
    validate_journal(store, value)
    atomic_json(store.transaction, value)


def load_journal(store: Store) -> dict:
    return validate_journal(store, read_json(store.transaction))


def validate_journal(store: Store, value: object) -> dict:
    if not isinstance(value, dict) or set(value) != KEYS or value.get("version") != 1 or value.get("operation") not in {"commit", "checkout"}:
        raise CorruptionError("Transaction journal has an invalid schema.")
    old_head = value["old_head"]
    new_head = value["new_head"]
    if old_head is not None:
        validate_id(old_head, "transaction old HEAD")
    validate_id(new_head, "transaction new HEAD")
    old_index = value["old_index"]
    if not isinstance(old_index, dict):
        raise CorruptionError("Transaction old_index must be an object.")
    for name, blob in old_index.items():
        validate_stored_path(name)
        if blob is not None:
            validate_id(blob)
            store.read_blob(blob)
    validate_snapshot(old_index)
    changes = value["changes"]
    if not isinstance(changes, dict):
        raise CorruptionError("Transaction changes must be an object.")
    for name, change in changes.items():
        validate_stored_path(name)
        if not isinstance(change, dict) or set(change) != {"before", "after"}:
            raise CorruptionError(f"Invalid transaction change for {name}.")
        for side in ("before", "after"):
            blob = change[side]
            if blob is not None:
                validate_id(blob)
                store.read_blob(blob)
    dirs = value["created_dirs"]
    if not isinstance(dirs, list) or dirs != sorted(set(dirs)):
        raise CorruptionError("Transaction created_dirs must be a sorted unique list.")
    for name in dirs:
        validate_stored_path(name)
    old_snapshot = {} if old_head is None else dict(store.read_commit(old_head).files)
    new_snapshot = dict(store.read_commit(new_head).files)
    if value["operation"] == "checkout":
        expected = {
            name: {"before": old_snapshot.get(name), "after": new_snapshot.get(name)}
            for name in sorted(set(old_snapshot) | set(new_snapshot))
            if old_snapshot.get(name) != new_snapshot.get(name)
        }
        if old_index or changes != expected:
            raise CorruptionError("Checkout journal does not match its commits.")
        changed_targets = [name for name, change in changes.items() if change["after"] is not None]
        for directory in dirs:
            if not any(target.startswith(directory + "/") for target in changed_targets):
                raise CorruptionError(f"Created directory is not an ancestor of a target: {directory}")
    else:
        expected = dict(old_snapshot)
        for name, blob in old_index.items():
            if blob is None:
                expected.pop(name, None)
            else:
                expected[name] = blob
        if changes or dirs or new_snapshot != expected or store.read_commit(new_head).parent != old_head:
            raise CorruptionError("Commit journal does not match staged state.")
    return value


def rollback(store: Store, journal: dict) -> list[str]:
    journal = validate_journal(store, journal)
    conflicts = []
    for name, change in journal["changes"].items():
        path = store.root / Path(*name.split("/"))
        ensure_no_links(path, stop=store.root)
        current = sha1_bytes(path.read_bytes()) if path.is_file() else None
        if current not in {change["before"], change["after"]}:
            conflicts.append(name)
    if conflicts:
        raise RecoveryError("Recovery stopped to preserve third-party edits: " + ", ".join(conflicts))
    current_head = store.read_head()
    if current_head not in {journal["old_head"], journal["new_head"]}:
        raise RecoveryError("Recovery stopped because HEAD is neither recorded state.")
    current_index = store.read_index()
    if current_index not in ({}, journal["old_index"]):
        raise RecoveryError("Recovery stopped because the index is neither recorded state.")
    for name, change in journal["changes"].items():
        path = store.root / Path(*name.split("/"))
        ensure_no_links(path, stop=store.root)
        before = change["before"]
        if before is None:
            if path.exists():
                path.unlink()
        else:
            path.parent.mkdir(parents=True, exist_ok=True)
            atomic_write(path, store.read_blob(before), reject_hardlinks=False)
    store.write_head(journal["old_head"])
    store.write_index(journal["old_index"])
    leftovers = []
    for name in sorted(journal["created_dirs"], key=lambda value: value.count("/"), reverse=True):
        path = store.root / Path(*name.split("/"))
        try:
            path.rmdir()
        except OSError:
            if path.exists():
                leftovers.append(name)
    store.transaction.unlink()
    return leftovers
