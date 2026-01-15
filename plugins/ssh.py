from __future__ import annotations

import subprocess
import threading
from typing import Any

from lib.core import MonitorCore
from lib.pluginApi import CommandSpec, PluginMeta
from lib.pluginBase import PluginBase
from lib.utils import parseInt, parseStr, parseStrList

typeName = "ssh"

pluginMeta = PluginMeta(
    typeName= "ssh",
    defaultParams={
        "host": None,
        "user": "root",
        "port": 22,
        "timeoutSec": 5,
        "extraArgs": [],
        "commands": [],
    },
    exposeStatus=False,
    showInTable=False,
)


class SSH:
    def __init__(
        self,
        *,
        host: str,
        user: str | None,
        port: int | None,
        timeoutSec: int,
        extraArgs: list[str],
    ) -> None:
        self.host = host
        self.user = user
        self.port = port
        self.timeoutSec = timeoutSec
        self.extraArgs = extraArgs

    def buildArgs(self, cmdStr: str) -> list[str]:
        target = f"{self.user}@{self.host}" if self.user else self.host

        argsList: list[str] = [
            "ssh",
            "-o",
            "BatchMode=yes",
            "-o",
            "StrictHostKeyChecking=no",
            "-o",
            f"ConnectTimeout={int(self.timeoutSec)}",
        ]

        if isinstance(self.port, int) and self.port > 0:
            argsList += ["-p", str(int(self.port))]

        if self.extraArgs:
            argsList += list(self.extraArgs)

        argsList += [target, cmdStr]
        return argsList

    def run(self, cmdStr: str) -> tuple[int | None, str]:
        argsList = self.buildArgs(cmdStr)

        try:
            resObj = subprocess.run(
                argsList,
                capture_output=True,
                text=True,
                stdin=subprocess.DEVNULL,  # <<< wichtig
                timeout=max(1, int(self.timeoutSec) + 2),
            )
            outStr = ((resObj.stderr or "") + "\n" + (resObj.stdout or "")).strip()
            return int(resObj.returncode), outStr
        except Exception:
            return None, ""


class SSHPlugin(PluginBase):
    typeName: str = "ssh"

    def __init__(self, core: MonitorCore, *, hostKey: str, params: dict[str, Any]) -> None:
        super().__init__(core, hostKey=hostKey, params=params)

        host = parseStr(params.get("host")) or self.hostKey
        user = parseStr(params.get("user"))
        portRaw = params.get("port")
        port = parseInt(portRaw, 0) if parseStr(portRaw) is not None or isinstance(portRaw, (int, float)) else 0
        portVal: int | None = port if port > 0 else None

        timeoutSec = parseInt(params.get("timeoutSec"), 5)
        extraArgs = parseStrList(params.get("extraArgs"))

        cmdsVal = params.get("commands")
        self.commandsRaw = list(cmdsVal) if isinstance(cmdsVal, list) else []

        self.ssh = SSH(
            host=host,
            user=user,
            port=portVal,
            timeoutSec=timeoutSec,
            extraArgs=extraArgs,
        )

    def toggleLogMessages(self, enable: bool = False) -> None:
        return  # SSH LOGS ALWAYS

    def commands(self) -> list[CommandSpec]:
        outCmds: list[CommandSpec] = []
        for item in self.commandsRaw or []:
            if not isinstance(item, dict):
                continue

            keyStr = parseStr(item.get("key"))
            cmdStr = parseStr(item.get("command"))
            if not keyStr or not cmdStr:
                continue

            labelStr = parseStr(item.get("label")) or keyStr
            outCmds.append(CommandSpec(key=keyStr, label=labelStr, payload={"command": cmdStr, "label": labelStr}))
        return outCmds

    def start(self) -> None:
        return

    def stop(self) -> None:
        return

    def execCommand(self, cmd: CommandSpec) -> None:
        payloadObj = cmd.payload if isinstance(cmd.payload, dict) else {}
        cmdStr = parseStr(payloadObj.get("command"))
        labelStr = parseStr(payloadObj.get("label")) or "SSH"
        if not cmdStr:
            return

        threading.Thread(target=self._runCommandThread, args=(labelStr, cmdStr), daemon=True).start()

    def _runCommandThread(self, labelStr: str, cmdStr: str) -> None:
        self.writeLog(f"{labelStr} -> {cmdStr}")

        try:
            rc, outStr = self.ssh.run(cmdStr)

            if rc == 0:
                self.writeLog(f"{labelStr} OK")
            elif rc is None:
                self.writeLog(f"{labelStr} FAIL")
            else:
                self.writeLog(f"{labelStr} FAIL({rc})")

            if outStr:
                self.writeLog(outStr)

        except Exception as exc:
            self.writeLog(f"{labelStr} EXC {type(exc).__name__}: {exc}")


def createPlugin(core: MonitorCore, hostKey: str, params: dict[str, Any]) -> SSHPlugin:
    return SSHPlugin(core, hostKey=hostKey, params=params)
