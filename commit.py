from dataclasses import dataclass, asdict
from typing import Dict, Optional
import json

from utils import sha1_bytes


@dataclass
class Commit:
    parent: Optional[str]
    timestamp: str
    message: str
    files: Dict[str, str]

    def to_dict(self) -> dict:
        return asdict(self)

    def compute_hash(self) -> str:
        raw = json.dumps(
            self.to_dict(),
            sort_keys=True,
            separators=(",", ":")
        ).encode("utf-8")

        return sha1_bytes(raw)