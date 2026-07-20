from __future__ import annotations

from dataclasses import asdict, dataclass
import hashlib
import json
from typing import Optional


def sha1_bytes(data: bytes) -> str:
    return hashlib.sha1(data).hexdigest()


@dataclass(frozen=True)
class Commit:
    parent: Optional[str]
    timestamp: str
    message: str
    files: dict[str, str]

    def to_dict(self) -> dict[str, object]:
        return asdict(self)

    def compute_hash(self) -> str:
        raw = json.dumps(
            self.to_dict(), sort_keys=True, separators=(",", ":")
        ).encode("utf-8")
        return sha1_bytes(raw)
