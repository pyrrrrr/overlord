# plugins/watchdog.py  (new PluginApi style)

from __future__ import annotations

import subprocess
import threading
import time
from typing import Any

from lib.core import MonitorCore
from lib.pluginApi import PluginMeta
from lib.pluginBase import PluginBase
from lib.utils import parseBool, parseFloat, parseStr, parseStrList

typeName = "watchdog"

pluginMeta = PluginMeta(
    typeName= "watchdog",
    defaultParams={
        "serviceName": "WATCHDOG",
        "watchSource": None,
        "watchWhen": ["bad"],
        # canonical:
        "rescueCommand": None,
        # backward-compatible legacy key:
        "rescureCommand": None,
        "recheckAfterSec": 10.0,
        "cooldownSec": 60.0,
        "runOnFirst": False,
        "pollEverySec": 0.25,
    },
    exposeStatus=False,
    showInTable=False,
)


class Watchdog:
    def __init__(
        self,
        *,
        core: MonitorCore,
        hostKey: str,
        serviceName: str,
        watchSource: str,
        watchWhen: list[str],
        rescueCommand: str,
        recheckAfterSec: float,
        cooldownSec: float,
        runOnFirst: bool,
        pollEverySec: float,
    ) -> None:
        self.core = core
        self.hostKey = hostKey

        self.serviceName = serviceName
        self.watchSource = watchSource
        self.watchWhen = watchWhen
        self.rescueCommand = rescueCommand

        self.recheckAfterSec = recheckAfterSec
        self.cooldownSec = cooldownSec
        self.runOnFirst = runOnFirst
        self.pollEverySec = pollEverySec

        self.lastSeenSeverity: str | None = None
        self.cooldownUntilTs: float = 0.0
        self.runningRescue: bool = False

    def getSeverity(self) -> str | None:
        sev = self.core.getLastSeverity(self.hostKey, self.watchSource)
        return str(sev).strip().lower() if sev else None

    def canRun(self) -> bool:
        return bool(self.watchSource and self.rescueCommand)

    def shouldTrigger(self, sevStr: str | None) -> bool:
        return sevStr in self.watchWhen

    def maybeTrigger(self, nowTs: float, *, reason: str, logFn) -> None:
        if self.runningRescue:
            return
        if self.cooldownUntilTs > nowTs:
            return

        self.runningRescue = True
        threading.Thread(
            target=self._runRescueThread,
            args=(reason, logFn),
            daemon=True,
        ).start()

    def _runRescueThread(self, reason: str, logFn) -> None:
        try:
            logFn(f"{self.serviceName}: trigger ({reason}) -> {self.rescueCommand}")

            resObj = subprocess.run(
                self.rescueCommand,
                shell=True,
                capture_output=True,
                text=True,
            )

            logFn(f"{self.serviceName}: rescue rc={int(resObj.returncode)}")

            outStr = ((resObj.stderr or "") + "\n" + (resObj.stdout or "")).strip()
            if outStr:
                logFn(outStr)

            if self.recheckAfterSec > 0.0:
                time.sleep(self.recheckAfterSec)

            sevAfter = self.getSeverity()
            logFn(f"{self.serviceName}: recheck [{self.watchSource}] -> {sevAfter or 'none'}")

        finally:
            self.cooldownUntilTs = time.time() + self.cooldownSec
            self.runningRescue = False
            logFn(f"{self.serviceName}: cooldown {int(self.cooldownSec)}s")


class WatchdogPlugin(PluginBase):
    typeName: str = "watchdog"

    def __init__(self, core: MonitorCore, *, hostKey: str, params: dict[str, Any]) -> None:
        super().__init__(core, hostKey=hostKey, params=params)

        self.serviceName = parseStr(params.get("serviceName")) or "WATCHDOG"

        watchSource = parseStr(params.get("watchSource"))
        self.watchSource = watchSource.lower() if watchSource else ""

        watchWhenRaw = params.get("watchWhen")
        self.watchWhen = [s.lower() for s in parseStrList(watchWhenRaw)] or ["bad"]

        rescueCommand = parseStr(params.get("rescueCommand"))
        if not rescueCommand:
            rescueCommand = parseStr(params.get("rescureCommand"))
        self.rescueCommand = rescueCommand or ""

        self.recheckAfterSec = parseFloat(params.get("recheckAfterSec"), 10.0)
        self.cooldownSec = parseFloat(params.get("cooldownSec"), 60.0)
        self.runOnFirst = parseBool(params.get("runOnFirst"), False)
        self.pollEverySec = parseFloat(params.get("pollEverySec"), 0.25)

        self.wd = Watchdog(
            core=self.core,
            hostKey=self.hostKey,
            serviceName=self.serviceName,
            watchSource=self.watchSource,
            watchWhen=self.watchWhen,
            rescueCommand=self.rescueCommand,
            recheckAfterSec=self.recheckAfterSec,
            cooldownSec=self.cooldownSec,
            runOnFirst=self.runOnFirst,
            pollEverySec=self.pollEverySec,
        )

        self.stopEvent: threading.Event | None = None
        self.threadObj: threading.Thread | None = None

    def start(self) -> None:
        self.stopEvent = threading.Event()
        self.threadObj = threading.Thread(target=self.loopSafe, daemon=True)
        self.threadObj.start()

        if not self.wd.canRun():
            self.writeLog(f"{self.serviceName}: disabled (missing watchSource/rescueCommand)")

    def stop(self) -> None:
        if self.stopEvent is not None:
            self.stopEvent.set()
        self.stopEvent = None
        self.threadObj = None

    def loopSafe(self) -> None:
        try:
            self.loop()
        except Exception as exc:
            self.writeLog(f"{self.serviceName}: LOOP EXC {type(exc).__name__}: {exc}")

    def loop(self) -> None:
        while self.stopEvent is not None and not self.stopEvent.is_set():
            if not self.wd.canRun():
                time.sleep(self.pollEverySec)
                continue

            nowTs = time.time()
            sevStr = self.wd.getSeverity()

            if self.wd.lastSeenSeverity is None:
                self.wd.lastSeenSeverity = sevStr
                if self.wd.runOnFirst and self.wd.shouldTrigger(sevStr):
                    self.wd.maybeTrigger(nowTs, reason="first", logFn=self.writeLog)
                time.sleep(self.wd.pollEverySec)
                continue

            if sevStr != self.wd.lastSeenSeverity:
                prev = self.wd.lastSeenSeverity or "none"
                cur = sevStr or "none"
                self.writeLog(f"{self.serviceName}: [{self.watchSource}] {prev} -> {cur}")
                self.wd.lastSeenSeverity = sevStr

                if self.wd.shouldTrigger(sevStr):
                    self.wd.maybeTrigger(nowTs, reason="transition", logFn=self.writeLog)

            time.sleep(self.wd.pollEverySec)


def createPlugin(core: MonitorCore, hostKey: str, params: dict[str, Any]) -> WatchdogPlugin:
    return WatchdogPlugin(core, hostKey=hostKey, params=params)
