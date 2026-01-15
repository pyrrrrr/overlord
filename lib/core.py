from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any
import threading

from .pluginApi import *


@dataclass
class HostState:
    host: str
    ip: str | None = None
    rowsBySource: dict[str, TableRow] = field(default_factory=dict)
    commandsByKey: dict[str, CommandSpec] = field(default_factory=dict)
    executorsByPlugin: dict[str, Any] = field(default_factory=dict)

    @property
    def rows(self) -> list[TableRow]:
        return list(self.rowsBySource.values())

    @property
    def statusLines(self) -> list[TableRow]:
        return self.rows

    @property
    def commands(self) -> list[CommandSpec]:
        return sorted(list(self.commandsByKey.values()), key=lambda c: c.key)

    def getLogMessageState(self) -> bool:
        for pluginObj in self.executorsByPlugin.values():
            fn = getattr(pluginObj, "getLogMessageState", None)
            if callable(fn) and fn():
                return True
        return False


class MonitorCore:
    def __init__(self, *, pluginRegistry: Any) -> None:
        self.pluginRegistry = pluginRegistry
        self.hostsByName: dict[str, HostState] = {}
        self.hostOrder: list[str] = []
        self.selectedIndex: int = 0
        self.commandLog: list[str] = []
        self.maxLogLines: int = 512
        self.statusMsg: str = "ready"
        self.logLock = threading.Lock()


        # minimal state cache for watchdog (and similar)
        self.lastRowByHostBaseType: dict[tuple[str, str], TableRow] = {}

    def ensureHost(self, hostKey: str) -> HostState:
        key = str(hostKey or "").strip() or "?"
        if key not in self.hostsByName:
            self.hostsByName[key] = HostState(host=key)
            self.hostOrder.append(key)
            if len(self.hostOrder) == 1:
                self.selectedIndex = 0
        return self.hostsByName[key]

    def selectedHost(self) -> str | None:
        if not self.hostOrder:
            return None
        self.selectedIndex = max(0, min(self.selectedIndex, len(self.hostOrder) - 1))
        return self.hostOrder[self.selectedIndex]

    def selectByNumber(self, n1: int) -> bool:
        idx = int(n1) - 1
        if 0 <= idx < len(self.hostOrder):
            self.selectedIndex = idx
            return True
        return False

    def getCommandsForSelectedHost(self) -> list[CommandSpec]:
        hostKey = self.selectedHost()
        if not hostKey:
            return []
        st = self.hostsByName.get(hostKey)
        if not st:
            return []
        return list(st.commands)

    def writeLog(self, msg: str) -> None:
        tsStr = time.strftime("%H:%M:%S")
        line = f"[{tsStr}] {msg}"

        with self.logLock:
            self.commandLog.append(line)
            if len(self.commandLog) > self.maxLogLines:
                self.commandLog = self.commandLog[-self.maxLogLines :]


    def logLine(self, msg: str) -> None:
        self.writeLog(msg)
    
    def pluginShowInTable(self, pluginType: str) -> bool:
        loaded = self.pluginRegistry.resolve(pluginType)
        return bool(loaded and getattr(loaded.meta, "showInTable", True))

    def getBaseTypeFromSource(self, source: str | None) -> str:
        pluginTypeFull = str(source or "").strip().lower() or "?"
        return pluginTypeFull.split(":", 1)[0]

    def getLastSeverity(self, hostKey: str, sourceBaseType: str) -> str | None:
        hk = str(hostKey or "").strip()
        bt = str(sourceBaseType or "").strip().lower()
        if not hk or not bt:
            return None
        row = self.lastRowByHostBaseType.get((hk, bt))
        if row is None:
            return None
        sev = str(getattr(row, "severity", "") or "").strip().lower()
        return sev or None

    def writeTableRow(self, row: TableRow) -> None:
        st = self.ensureHost(row.host)

        pluginTypeFull = str(row.source or "").strip().lower() or "?"
        baseType = pluginTypeFull.split(":", 1)[0]

        if not self.pluginShowInTable(baseType):
            return

        st.rowsBySource[pluginTypeFull] = row

        if isinstance(row.ip, str) and row.ip.strip():
            st.ip = row.ip.strip()

    def writeTable(self, hostKey: str, row: TableRow) -> None:
        if not isinstance(row, TableRow):
            return

        if row.host:
            fixedRow = row
        else:
            fixedRow = TableRow(
                host=str(hostKey or "").strip() or "?",
                ip=row.ip,
                source=row.source,
                text=row.text,
                severity=row.severity,
                ts=row.ts,
            )

        # ALWAYS cache last state (even if not shown in UI)
        hostKeyFixed = str(fixedRow.host or "").strip()
        baseType = self.getBaseTypeFromSource(getattr(fixedRow, "source", None))
        if hostKeyFixed and baseType:
            self.lastRowByHostBaseType[(hostKeyFixed, baseType)] = fixedRow

        # UI update remains controlled by showInTable
        self.writeTableRow(fixedRow)

    def registerPlugin(self, pluginObj: Any) -> None:
        pluginKey = str(getattr(pluginObj, "typeName", "") or "").strip().lower()
        hostKey = str(getattr(pluginObj, "hostKey", "") or "").strip()
        if not pluginKey or not hostKey:
            return

        st = self.ensureHost(hostKey)
        st.executorsByPlugin[pluginKey] = pluginObj

        cmds: list[CommandSpec] = []
        if hasattr(pluginObj, "commands"):
            try:
                cmds = list(pluginObj.commands() or [])
            except Exception:
                cmds = []

        for c in cmds:
            if not isinstance(c, CommandSpec) or not c.key:
                continue

            payloadObj = dict(c.payload) if isinstance(c.payload, dict) else {}
            payloadObj["plugin"] = pluginKey

            st.commandsByKey[c.key] = CommandSpec(
                key=c.key,
                label=c.label,
                payload=payloadObj,
            )

    def execCommand(self, rawCmd: str) -> None:
        cmdStr = (rawCmd or "").strip()

        if not cmdStr:
            self.statusMsg = "ready"
            return

        parts = cmdStr.split()
        cmdKey = parts[0].lower()

        if cmdKey == "++":  # log all
            for _hostKey, hostState in self.hostsByName.items():
                for _pluginKey, pluginObj in hostState.executorsByPlugin.items():
                    fn = getattr(pluginObj, "toggleLogMessages", None)
                    if callable(fn):
                        fn(True)
            return

        if cmdKey == "--":  # log none
            for _hostKey, hostState in self.hostsByName.items():
                for _pluginKey, pluginObj in hostState.executorsByPlugin.items():
                    fn = getattr(pluginObj, "toggleLogMessages", None)
                    if callable(fn):
                        fn(False)
            return

        if cmdKey == "ls+":
            hostKeySel = self.selectedHost()
            hostState = self.hostsByName.get(hostKeySel) if hostKeySel else None
            if not hostState:
                return
            for pluginObj in hostState.executorsByPlugin.values():
                fn = getattr(pluginObj, "toggleLogMessages", None)
                if callable(fn):
                    fn(True)
            return

        if cmdKey == "ls-":
            hostKeySel = self.selectedHost()
            hostState = self.hostsByName.get(hostKeySel) if hostKeySel else None
            if not hostState:
                return
            for pluginObj in hostState.executorsByPlugin.values():
                fn = getattr(pluginObj, "toggleLogMessages", None)
                if callable(fn):
                    fn(False)
            return

        s = str(cmdStr or "").strip()
        if not s:
            return

        if s.isdigit():
            self.selectByNumber(int(s))
            return

        hostKeySel = self.selectedHost()
        if not hostKeySel:
            return

        st = self.hostsByName.get(hostKeySel)
        if not st:
            return

        cmdObj = st.commandsByKey.get(s)
        if cmdObj is None:
            self.writeLog(f"{hostKeySel}: unknown command: {s}")
            return

        payloadObj = cmdObj.payload if isinstance(cmdObj.payload, dict) else {}
        pluginKey = str(payloadObj.get("plugin") or "").strip().lower() or "?"

        executor = st.executorsByPlugin.get(pluginKey)
        if executor is None or not hasattr(executor, "execCommand"):
            self.writeLog(f"{hostKeySel}: no executor for plugin={pluginKey}")
            return

        try:
            executor.execCommand(cmdObj)
        except Exception as exc:
            self.writeLog(f"{hostKeySel}: :{s} EXC {type(exc).__name__}: {exc}")
