# plugins/ping.py  (new PluginApi style)

from __future__ import annotations
import re
import os
import subprocess
import threading
import time
from typing import Any

from lib.core import MonitorCore
from lib.pluginApi import CommandSpec, PluginMeta, TableRow
from lib.pluginBase import PluginBase
from lib.utils import parseFloat, parseInt, parseStr


typeName = "ping"

pluginMeta = PluginMeta(
    typeName = "ping",
    defaultParams ={
        "host": None,
        "everySec": 5.0,
        "timeoutMs": 2000,
    },
    exposeStatus=True,
    showInTable=True,
)



class Ping:
    def __init__(self, *, targetHost: str, timeoutMs: int) -> None:
        self.targetHost = targetHost
        self.timeoutMs = int(timeoutMs)

        self._reIp = re.compile(
            r"\b(?:(?:25[0-5]|2[0-4]\d|1?\d?\d)\.){3}"
            r"(?:25[0-5]|2[0-4]\d|1?\d?\d)\b"
        )
        self._reTime = re.compile(r"time[=<]?\s*([0-9]+(?:\.[0-9]+)?)\s*ms", re.IGNORECASE)

    def _extractIp(self, outputStr: str) -> Optional[str]:
        m = self._reIp.search(outputStr or "")
        return m.group(0) if m else None

    def _extractLatencyMs(self, outputStr: str) -> Optional[int]:
        m = self._reTime.search(outputStr or "")
        if not m:
            return None
        try:
            return int(round(float(m.group(1))))
        except Exception:
            return None

    def _run(self, argsList: list[str]) -> tuple[int, str]:
        try:
            resObj = subprocess.run(argsList, capture_output=True, text=True)
        except Exception:
            return 999, ""
        out = (resObj.stdout or "") + "\n" + (resObj.stderr or "")
        return int(resObj.returncode), out

    def _buildPingArgs(self) -> list[str]:
        t = self.targetHost
        ms = max(1, int(self.timeoutMs))

        if os.name == "nt":
            # Windows: -n 1 (count), -w <ms> (timeout)
            return ["ping", "-n", "1", "-w", str(ms), t]

        # Linux/iputils: -c 1 (count), -W <sec> (timeout per reply)
        sec = max(1, int(round(ms / 1000.0)))
        return ["ping", "-c", "1", "-W", str(sec), t]

    def pingOnce(self) -> tuple[Optional[str], Optional[int]]:
        pingArgs = self._buildPingArgs()
        rc, outputStr = self._run(pingArgs)

        ipVal = self._extractIp(outputStr)

        if rc == 0:
            latencyMs = self._extractLatencyMs(outputStr)
            return ipVal, latencyMs

        return ipVal, None




class PingPlugin(PluginBase):
    typeName: str = "ping"

    def __init__(self, core: MonitorCore, *, hostKey: str, params: dict[str, Any]) -> None:
        super().__init__(core, hostKey=hostKey, params=params)

        hostStr = parseStr(params.get("host")) or self.hostKey
        self.everySec = parseFloat(params.get("everySec"), 5.0)
        self.timeoutMs = parseInt(params.get("timeoutMs"), 2000)

        self.ping = Ping(targetHost=hostStr, timeoutMs=self.timeoutMs)

        self.isOnline: bool = False
        self.stopEvent: threading.Event | None = None
        self.threadObj: threading.Thread | None = None

    def commands(self) -> list[CommandSpec]:
        return [
            CommandSpec(
                key="t",
                label="tracert",
                payload={},
            )
        ]

    def execCommand(self, cmd: CommandSpec) -> None:
        if cmd.key != "t":
            return

        threading.Thread(target=self._runTracert, daemon=True).start()

    # TODO: make tracert linuxcompatible
    def _runTracert(self) -> None:
        target = self.ping.targetHost
        self.writeLog(f"TRACERT {target}")

        try:
            res = subprocess.run(
                ["tracert", "-d", "-h", "20", "-w", "1000", target],
                capture_output=True,
                text=True,
                stdin=subprocess.DEVNULL,
                timeout=60,
            )

            formatted = self._formatTracertOutput(res.stdout)
            for ln in formatted:
                self.writeLog(ln)
            self.writeLog(f"TRACERT COMPLETE")

        except Exception as exc:
            self.writeLog(f"TRACERT EXC {type(exc).__name__}: {exc}")

    def _formatTracertOutput(self,raw: str) -> list[str]:
        lines = []
        for ln in (raw or "").splitlines():
            ln = ln.strip()
            if not ln:
                continue

            # skip header/footer noise
            if ln.lower().startswith(("tracing route", "trace complete")):
                continue

            parts = ln.split()
            if not parts or not parts[0].isdigit():
                continue

            hop = parts[0].rjust(2)

            times: list[str] = []
            host = "?"

            for p in parts[1:]:
                if p == "*":
                    times.append("*")
                elif p.endswith("ms"):
                    times.append(p)
                else:
                    host = p

            while len(times) < 3:
                times.append("")

            line = f"{hop}  {times[0]:<7} {times[1]:<7} {times[2]:<7} {host}"
            lines.append(line)

        return lines

    def start(self) -> None:
        self.stopEvent = threading.Event()

        self.writeTable(
            TableRow(
                host=self.hostKey,
                ip=None,
                source="ping",
                text="PING: ...",
                severity="info",
                ts=time.time(),
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
            self.writeLog(f"PING LOOP EXC {type(exc).__name__}: {exc}")
            self.writeTable(
                TableRow(
                    host=self.hostKey,
                    ip=None,
                    source="ping",
                    text="PING: EXC",
                    severity="bad",
                    ts=time.time(),
                )
            )

    def writePingRow(self, nowTs: float, ipVal: str | None, latencyMs: int | None) -> None:
        self.writeTable(
            TableRow(
                host=self.hostKey,
                ip=ipVal,
                source="ping",
                text=("PING: -" if latencyMs is None else f"PING: {latencyMs}ms"),
                severity=("bad" if latencyMs is None else "ok"),
                ts=nowTs,
            )
        )

    def loop(self) -> None:
        nextTs = 0.0
        hasSentInitial = False
        lastIsOnline = self.isOnline

        while self.stopEvent is not None and not self.stopEvent.is_set():
            nowTs = time.time()

            if nowTs >= nextTs:
                nextTs = nowTs + max(0.2, float(self.everySec))

                ipVal, latencyMs = self.ping.pingOnce()
                isOnlineNow = latencyMs is not None

                if (not hasSentInitial) or (isOnlineNow != lastIsOnline):
                    if isOnlineNow != lastIsOnline:
                        self.writeLog("is online" if isOnlineNow else "is offline")
                    self.writePingRow(nowTs, ipVal, latencyMs)
                    hasSentInitial = True

                lastIsOnline = isOnlineNow
                self.isOnline = isOnlineNow

            time.sleep(0.05)


def createPlugin(core: MonitorCore, hostKey: str, params: dict[str, Any]) -> PingPlugin:
    return PingPlugin(core, hostKey=hostKey, params=params)
