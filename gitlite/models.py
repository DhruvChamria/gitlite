from __future__ import annotations

from dataclasses import asdict, dataclass
import hashlib
import json
from datetime import datetime
from typing import Optional

from .errors import CorruptionError


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

    @classmethod
    def from_stored(cls, value: object, *, expected_hash: str) -> "Commit":
        if not isinstance(value, dict) or set(value) != {"hash", "parent", "timestamp", "message", "files"}:
            raise CorruptionError(f"Commit {expected_hash} has an invalid schema.")
        if value["hash"] != expected_hash:
            raise CorruptionError(f"Commit {expected_hash} has a mismatched embedded hash.")
        parent = value["parent"]
        if parent is not None and not isinstance(parent, str):
            raise CorruptionError(f"Commit {expected_hash} has an invalid parent.")
        timestamp = value["timestamp"]
        if not isinstance(timestamp, str):
            raise CorruptionError(f"Commit {expected_hash} has an invalid timestamp.")
        try:
            parsed = datetime.fromisoformat(timestamp)
        except ValueError as exc:
            raise CorruptionError(f"Commit {expected_hash} has an invalid timestamp.") from exc
        if parsed.tzinfo is None or parsed.utcoffset() is None:
            raise CorruptionError(f"Commit {expected_hash} timestamp must include a timezone.")
        message = value["message"]
        if not isinstance(message, str) or not message.strip():
            raise CorruptionError(f"Commit {expected_hash} has an invalid message.")
        files = value["files"]
        if not isinstance(files, dict) or not all(isinstance(k, str) and isinstance(v, str) for k, v in files.items()):
            raise CorruptionError(f"Commit {expected_hash} has an invalid files map.")
        commit = cls(parent, timestamp, message, dict(files))
        if commit.compute_hash() != expected_hash:
            raise CorruptionError(f"Commit {expected_hash} content does not match its hash.")
        return commit
