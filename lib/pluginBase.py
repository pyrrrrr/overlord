from __future__ import annotations

from typing import Any

from .core import MonitorCore
from .pluginApi import CommandSpec, TableRow


class PluginBase:
    typeName: str = "?"

    def __init__(self, core: MonitorCore, *, hostKey: str, params: dict[str, Any]) -> None:
        self.core = core
        self.hostKey = str(hostKey).strip() or "?"
        self.params = dict(params or {})
        self.logMessages = False

    def commands(self) -> list[CommandSpec]:
        return []

    def start(self) -> None:
        return

    def stop(self) -> None:
        return

    def execCommand(self, cmd: CommandSpec) -> None:
        return

    def toggleLogMessages(self, enable: bool = False) -> None:
        self.logMessages = bool(enable)

    def getLogMessageState(self) -> bool:
        return bool(self.logMessages)

    def writeLog(self, text: str) -> None:
        self.core.writeLog(f"[{self.typeName}] {self.hostKey}: {text}")

    def writeTable(self, row: TableRow) -> None:
        self.core.writeTable(self.hostKey, row)
