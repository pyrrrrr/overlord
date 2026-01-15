
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class PluginMeta:
    typeName: str
    defaultParams: dict[str, Any] = field(default_factory=dict)
    exposeStatus: bool = True
    showInTable: bool = True


@dataclass(frozen=True)
class CommandSpec:
    key: str
    label: str
    payload: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class TableRow:
    host: str
    source: str
    text: str
    severity: str = "info"
    ts: float = 0.0
    ip: str | None = None