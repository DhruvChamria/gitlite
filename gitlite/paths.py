from __future__ import annotations

from pathlib import Path

from .errors import RepositoryError


def discover_root(start: Path | None = None) -> Path:
    current = (start or Path.cwd()).resolve()
    for candidate in (current, *current.parents):
        if (candidate / ".mygit").exists():
            return candidate
    raise RepositoryError("Not a GitLite repository. Run `gitlite init` first.")
