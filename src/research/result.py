from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

import click

from research.constants import RESULT_VERSION


@dataclass(slots=True)
class CommandResult:
    command: str
    status: str
    data: dict[str, Any] = field(default_factory=dict)
    warnings: list[dict[str, Any]] = field(default_factory=list)
    errors: list[dict[str, Any]] = field(default_factory=list)

    def envelope(self) -> dict[str, Any]:
        return {
            "result_version": RESULT_VERSION,
            "command": self.command,
            "status": self.status,
            "data": self.data,
            "warnings": self.warnings,
            "errors": self.errors,
        }


def emit(result: CommandResult, json_output: bool) -> None:
    if json_output:
        click.echo(json.dumps(result.envelope(), ensure_ascii=False, sort_keys=True))
        return
    click.echo(f"{result.command}: {result.status}")
    for key, value in result.data.items():
        click.echo(f"  {key}: {value}")
    for warning in result.warnings:
        click.echo(f"warning: {warning.get('message', warning)}", err=True)
    for error in result.errors:
        click.echo(f"error: {error.get('message', error)}", err=True)
