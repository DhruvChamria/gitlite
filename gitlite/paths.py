from __future__ import annotations

import os
from pathlib import Path, PurePosixPath, PureWindowsPath
import stat

from .errors import PathError, RepositoryError


EXCLUDED_DIRS = {".git", ".mygit", ".venv", "venv", "__pycache__"}
FORBIDDEN_DIRS = {".git", ".mygit"}
RESERVED_PREFIX = ".gitlite-tmp-"
DEVICE_NAMES = {"con", "prn", "aux", "nul", *(f"com{i}" for i in range(1, 10)), *(f"lpt{i}" for i in range(1, 10))}
BAD_CHARS = set('<>:"|?*')


def is_link_like(path: Path) -> bool:
    try:
        info = path.lstat()
    except FileNotFoundError:
        return False
    if stat.S_ISLNK(info.st_mode):
        return True
    return bool(getattr(info, "st_file_attributes", 0) & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0))


def ensure_no_links(path: Path, *, stop: Path, include_leaf: bool = True) -> None:
    absolute = Path(os.path.abspath(path))
    base = Path(os.path.abspath(stop))
    try:
        relative = absolute.relative_to(base)
    except ValueError as exc:
        raise PathError(f"Path escapes repository: {path}") from exc
    if is_link_like(base):
        raise PathError(f"Linked or reparse-point path is unsupported: {base}")
    current = base
    parts = relative.parts if include_leaf else relative.parts[:-1]
    for part in parts:
        current /= part
        if is_link_like(current):
            raise PathError(f"Linked or reparse-point path is unsupported: {current}")


def validate_component(component: str) -> None:
    if not component or component in {".", ".."}:
        raise PathError(f"Invalid path component: {component!r}")
    folded = component.casefold()
    if folded in FORBIDDEN_DIRS:
        raise PathError(f"Repository metadata path is forbidden: {component}")
    if folded.startswith(RESERVED_PREFIX):
        raise PathError(f"Reserved temporary path is forbidden: {component}")
    if component[-1] in {".", " "}:
        raise PathError(f"Path component cannot end in a dot or space: {component}")
    if any(ord(char) < 32 or ord(char) == 127 or char in BAD_CHARS for char in component):
        raise PathError(f"Path contains unsupported characters: {component!r}")
    if component.split(".", 1)[0].casefold() in DEVICE_NAMES:
        raise PathError(f"Reserved device name is unsupported: {component}")


def validate_stored_path(value: str) -> str:
    if not isinstance(value, str) or not value or "\\" in value:
        raise PathError(f"Stored path is not canonical: {value!r}")
    path = PurePosixPath(value)
    if path.is_absolute() or str(path) != value:
        raise PathError(f"Stored path is not canonical: {value!r}")
    for component in path.parts:
        validate_component(component)
    return value


def validate_snapshot(paths: object) -> None:
    if not isinstance(paths, dict):
        raise PathError("Snapshot must be a path-to-object map.")
    tree: dict[str, tuple[str, dict | None]] = {}
    for raw in sorted(paths):
        validate_stored_path(raw)
        node = tree
        parts = PurePosixPath(raw).parts
        for index, component in enumerate(parts):
            key = component.casefold()
            leaf = index == len(parts) - 1
            existing = node.get(key)
            if existing is None:
                node[key] = (component, None if leaf else {})
                existing = node[key]
            spelling, child = existing
            if spelling != component:
                raise PathError(f"Portable case collision: {spelling!r} and {component!r}")
            if leaf:
                if child is not None:
                    raise PathError(f"File/directory collision at {raw}")
            else:
                if child is None:
                    raise PathError(f"File/directory collision at {raw}")
                node = child


def canonical_user_path(root: Path, cwd: Path, raw: str, *, require_file: bool = False) -> tuple[str, Path]:
    win = PureWindowsPath(raw)
    candidate = Path(raw)
    if candidate.is_absolute() or win.is_absolute() or win.drive:
        raise PathError(f"Absolute, drive, and UNC paths are unsupported: {raw}")
    absolute = Path(os.path.abspath(cwd / candidate))
    root_abs = Path(os.path.abspath(root))
    try:
        relative = absolute.relative_to(root_abs)
    except ValueError as exc:
        raise PathError(f"Path is outside repository: {raw}") from exc
    if not relative.parts:
        raise PathError("Repository root is not a file path.")
    stored = PurePosixPath(*relative.parts).as_posix()
    validate_stored_path(stored)
    ensure_no_links(absolute, stop=root_abs)
    if require_file and not absolute.is_file():
        raise PathError(f"Not a regular file: {raw}")
    return stored, absolute


def ensure_portable_existing_path(root: Path, stored: str) -> None:
    validate_stored_path(stored)
    current = root
    for component in PurePosixPath(stored).parts:
        if not current.is_dir():
            return
        matches = [entry.name for entry in os.scandir(current) if entry.name.casefold() == component.casefold()]
        if matches and component not in matches:
            raise PathError(f"Existing path spelling collides portably: {matches[0]!r} and {component!r}")
        current /= component


def discover_root(start: Path | None = None) -> Path:
    current = Path(os.path.abspath(start or Path.cwd()))
    for candidate in (current, *current.parents):
        marker = candidate / ".mygit"
        if marker.exists() or is_link_like(marker):
            if is_link_like(marker) or not marker.is_dir():
                raise RepositoryError(f"Nearest .mygit is unsafe or malformed: {marker}")
            return candidate
    raise RepositoryError("Not a GitLite repository. Run `gitlite init` first.")


def is_excluded(stored: str) -> bool:
    parts = PurePosixPath(stored).parts
    return any(part.casefold() in EXCLUDED_DIRS for part in parts[:-1]) or parts[-1].casefold().endswith((".pyc", ".pyo"))
