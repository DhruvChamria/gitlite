from __future__ import annotations

from contextlib import contextmanager
import os
from pathlib import Path


@contextmanager
def working_directory(path: Path):
    old = Path.cwd()
    os.chdir(path)
    try:
        yield
    finally:
        os.chdir(old)
