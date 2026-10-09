"""Per-day spending budget, persisted locally so restarts do not reset it."""

from __future__ import annotations

import json
import os
import time
from pathlib import Path


class DailyBudget:
    def __init__(self, limit: int, state_dir: Path):
        self.limit = limit
        self.path = state_dir / "usage.json"

    @staticmethod
    def _today() -> str:
        return time.strftime("%Y-%m-%d", time.gmtime())

    def _load(self) -> dict:
        try:
            data = json.loads(self.path.read_text())
            return data if isinstance(data, dict) else {}
        except (OSError, ValueError):
            return {}

    def used_today(self) -> int:
        data = self._load()
        return int(data.get("count", 0)) if data.get("day") == self._today() else 0

    def remaining(self) -> int:
        return max(0, self.limit - self.used_today())

    def record(self) -> None:
        used = self.used_today() + 1
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps({"day": self._today(), "count": used}))
        os.replace(tmp, self.path)
