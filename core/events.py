"""Stage events: the single record of what happened, used live and for replay."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum


class StageStatus(str, Enum):
    RUNNING = "running"
    OK = "ok"
    WARN = "warn"
    FAIL = "fail"
    ERROR = "error"
    SKIPPED = "skipped"


@dataclass
class StageEvent:
    stage: str
    status: StageStatus
    summary: str = ""
    details: dict = field(default_factory=dict)
    duration_ms: int = 0
    seq: int = 0
    ts: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


@dataclass
class StageResult:
    status: StageStatus
    summary: str
    details: dict = field(default_factory=dict)
    halt: bool = False

    @classmethod
    def error(cls, e: Exception) -> "StageResult":
        return cls(StageStatus.ERROR, f"{type(e).__name__}: {e}", {"error": str(e)})
