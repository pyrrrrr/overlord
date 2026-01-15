# plugins/processes.py  (new PluginApi style)

from __future__ import annotations

import json
import socket
import threading
import time
from typing import Any

from lib.core import MonitorCore
from lib.pluginApi import PluginMeta, TableRow
from lib.pluginBase import PluginBase
from lib.utils import parseBool, parseFloat, parseInt, parseStr, parseStrList

typeName = "processes"

pluginMeta = PluginMeta(
    typeName= "processes",
    defaultParams={
        "host": None,
        "port": 8765,
        "prog": [],
        "everySec": 5.0,
        "timeoutSec": 1.0,
        "showAll": True,
    },
    exposeStatus=True,
    showInTable=True,
)


class Processes:
    def __init__(self, host: str, port: int, timeoutSec: float) -> None:
        self.host = host
        self.port = int(port)
        self.timeoutSec = float(timeoutSec)

    def udpGetJson(self, payloadObj: dict[str, Any]) -> dict[str, Any] | None:
        sockObj: socket.socket | None = None
        try:
            dataBytes = json.dumps(payloadObj).encode("utf-8")

            sockObj = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            sockObj.settimeout(float(self.timeoutSec))
            sockObj.sendto(dataBytes, (self.host, int(self.port)))

            respBytes, _ = sockObj.recvfrom(64 * 1024)
            obj = json.loads(respBytes.decode("utf-8"))
            return obj if isinstance(obj, dict) else None
        except Exception:
            return None
        finally:
            if sockObj is not None:
                try:
                    sockObj.close()
                except Exception:
                    pass

    def checkOne(self, procName: str) -> bool | None:
        obj = self.udpGetJson({"cmd": "check", "name": procName})
        if not obj:
            return None

        if obj.get("ok") is not True:
            return None

        runningVal = obj.get("running")
        if isinstance(runningVal, bool):
            return runningVal
        if isinstance(runningVal, (int, float)):
            return bool(runningVal)
        return None

    def rowFor(self, hostKey: str, nowTs: float, procName: str, running: bool | None) -> TableRow:
        if running is True:
            statusStr = "OK"
            sev = "ok"
        elif running is False:
            statusStr = "OFFLINE"
            sev = "bad"
        else:
            statusStr = "ERR"
            sev = "bad"

        return TableRow(
            host=hostKey,
            ip=self.host,
            source=f"processes:{procName}",
            text=f"PROC: {procName}={statusStr}",
            severity=sev,
            ts=nowTs,
        )


class ProcessesPlugin(PluginBase):
    typeName: str = "processes"

    def __init__(self, core: MonitorCore, *, hostKey: str, params: dict[str, Any]) -> None:
        super().__init__(core, hostKey=hostKey, params=params)

        self.host = parseStr(params.get("host")) or self.hostKey
        self.port = parseInt(params.get("port"), 8765)
        self.everySec = parseFloat(params.get("everySec"), 5.0)
        self.timeoutSec = parseFloat(params.get("timeoutSec"), 1.0)
        self.showAll = parseBool(params.get("showAll"), True)

        self.proc = Processes(self.host, self.port, self.timeoutSec)
        self.progList = parseStrList(params.get("prog"))

        self.stopEvent: threading.Event | None = None
        self.threadObj: threading.Thread | None = None

    def start(self) -> None:
        self.stopEvent = threading.Event()

        # initial emit (stable UI)
        nowTs = time.time()
        if not self.progList:
            self.writeTable(
                TableRow(
                    host=self.hostKey,
                    ip=self.host,
                    source="processes",
                    text="PROC: -",
                    severity="info",
                    ts=nowTs,
                )
            )
        else:
            for procName in self.progList:
                self.writeTable(
                    TableRow(
                        host=self.hostKey,
                        ip=self.host,
                        source=f"processes:{procName}",
                        text=f"PROC: {procName}=...",
                        severity="info",
                        ts=nowTs,
                    )
                )

        self.threadObj = threading.Thread(target=self.loopSafe, daemon=True)
        self.threadObj.start()

    def stop(self) -> None:
        if self.stopEvent is not None:
            self.stopEvent.set()
        self.stopEvent = None
        self.threadObj = None

    def loopSafe(self) -> None:
        try:
            self.loop()
        except Exception as exc:
            self.writeLog(f"PROC LOOP EXC {type(exc).__name__}: {exc}")
            self.writeTable(
                TableRow(
                    host=self.hostKey,
                    ip=self.host,
                    source="processes",
                    text="PROC: EXC",
                    severity="bad",
                    ts=time.time(),
                )
            )

    def loop(self) -> None:
        nextTs = 0.0
        hasSentInitial = False

        while self.stopEvent is not None and not self.stopEvent.is_set():
            nowTs = time.time()

            if nowTs >= nextTs:
                nextTs = nowTs + max(0.2, float(self.everySec))

                if not self.progList or self.proc is None:
                    if not hasSentInitial:
                        self.writeTable(
                            TableRow(
                                host=self.hostKey,
                                ip=self.host,
                                source="processes",
                                text="PROC: -",
                                severity="info",
                                ts=nowTs,
                            )
                        )
                        hasSentInitial = True
                    time.sleep(0.05)
                    continue

                results: list[tuple[str, bool | None]] = []
                anyBad = False

                for procName in self.progList:
                    running = self.proc.checkOne(procName)
                    results.append((procName, running))
                    if running is not True:
                        anyBad = True

                if self.showAll or (not hasSentInitial):
                    for procName, running in results:
                        self.writeTable(self.proc.rowFor(self.hostKey, nowTs, procName, running))
                else:
                    if anyBad:
                        for procName, running in results:
                            if running is not True:
                                self.writeTable(self.proc.rowFor(self.hostKey, nowTs, procName, running))

                hasSentInitial = True

            time.sleep(0.05)


def createPlugin(core: MonitorCore, hostKey: str, params: dict[str, Any]) -> ProcessesPlugin:
    return ProcessesPlugin(core, hostKey=hostKey, params=params)
