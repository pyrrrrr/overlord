"""
Configuration data classes for MonitorApp.

ElementConfig defines one plugin instance, including type, name, parameters, enable flag, and host order. Lower order values are shown first.

MonitorConfig holds the global refresh rate and the list of configured elements.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class ElementConfig:
    type: str
    name: str = ""
    params: dict[str, Any] = field(default_factory=dict)
    enabled: bool = True
    order: int = 1000  # <- host order


@dataclass
class MonitorConfig:
    refreshRateSec: float = 0.05
    elements: list[ElementConfig] = field(default_factory=list)