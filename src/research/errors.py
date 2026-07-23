from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from research.constants import EXIT_GENERAL


@dataclass(slots=True)
class ResearchError(Exception):
    message: str
    category: str = "general_failure"
    exit_code: int = EXIT_GENERAL
    details: dict[str, Any] = field(default_factory=dict)

    def __str__(self) -> str:
        return self.message
