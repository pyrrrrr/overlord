# plugins/udp.py  (new PluginApi style)

from __future__ import annotations

import json
import socket
import threading
import time
from typing import Any

from lib.core import MonitorCore
from lib.pluginApi import CommandSpec, PluginMeta, TableRow
from lib.pluginBase import PluginBase
from lib.utils import parseBool, parseFloat, parseInt, parseStr, parseStrList

typeName = "udp"

pluginMeta = PluginMeta(
    typeName= "udp",
    defaultParams={
        "bindIp": "0.0.0.0",
        "port": 5000,
        "emitEverySec": 0.25,
        "okAfterSec": 1.0,
        "offlineAfterSec": 10.0,
        "serviceName": "UDP",
        "showPacketStats": True,
        "aliases": [],
    },
    exposeStatus=True,
    showInTable=True,
)


class HostStats:
    def __init__(self) -> None:
        self.lastSeenTs: float = 0.0
        self.packetCount: int = 0
        self.byteCount: int = 0

        self.lastRateTs: float = 0.0
        self.lastRatePacketCount: int = 0
        self.pps: float = 0.0


class UdpListener:
    def __init__(self, *, bindIp: str, port: int, emitEverySec: float) -> None:
        self.bindIp = str(bindIp)
        self.port = int(port)
        self.emitEverySec = float(emitEverySec)

        self.sockObj: socket.socket | None = None
        self.stopEvent: threading.Event | None = None
        self.threadObj: threading.Thread | None = None

        self.lockObj = threading.Lock()

        self.keyMapLower: dict[str, str] = {}  # incoming name/alias -> canonical hostKey
        self.statsByHost: dict[str, HostStats] = {}  # canonical hostKey -> stats
        self.subsByHost: dict[str, list["UdpPlugin"]] = {}

    def start(self) -> None:
        if self.threadObj is not None:
            return
        self.stopEvent = threading.Event()
        self.threadObj = threading.Thread(target=self.loop, daemon=True)
        self.threadObj.start()

    def stopIfIdle(self) -> None:
        with self.lockObj:
            hasSubs = bool(self.subsByHost)
        if hasSubs:
            return

        if self.stopEvent is not None:
            self.stopEvent.set()

        if self.sockObj is not None:
            try:
                self.sockObj.close()
            except Exception:
                pass

        self.sockObj = None
        self.stopEvent = None
        self.threadObj = None

    def addSub(self, pluginObj: "UdpPlugin", *, aliases: list[str]) -> None:
        hostKey = pluginObj.hostKey

        aliasList: list[str] = []
        for a in aliases or []:
            s = parseStr(a)
            if s:
                aliasList.append(s)

        with self.lockObj:
            self.subsByHost.setdefault(hostKey, []).append(pluginObj)

            self.keyMapLower[hostKey.lower()] = hostKey
            for a in aliasList:
                self.keyMapLower[a.lower()] = hostKey

            self.statsByHost.setdefault(hostKey, HostStats())

        self.start()

    def removeSub(self, pluginObj: "UdpPlugin") -> None:
        hostKey = pluginObj.hostKey
        with self.lockObj:
            lst = self.subsByHost.get(hostKey, [])
            lst = [p for p in lst if p is not pluginObj]
            if lst:
                self.subsByHost[hostKey] = lst
                return

            # last subscriber removed -> cleanup
            self.subsByHost.pop(hostKey, None)
            self.statsByHost.pop(hostKey, None)

            # remove all aliases mapping to hostKey
            toDelete = [k for k, v in self.keyMapLower.items() if v == hostKey]
            for k in toDelete:
                self.keyMapLower.pop(k, None)

    def updateRatesLocked(self, nowTs: float) -> None:
        for st in self.statsByHost.values():
            if st.lastRateTs <= 0.0:
                st.lastRateTs = nowTs
                st.lastRatePacketCount = int(st.packetCount)
                st.pps = 0.0
                continue

            dt = float(nowTs - st.lastRateTs)
            if dt <= 0.0:
                continue

            dp = int(st.packetCount) - int(st.lastRatePacketCount)
            st.pps = max(0.0, float(dp) / dt)
            st.lastRateTs = nowTs
            st.lastRatePacketCount = int(st.packetCount)

    def parseIncomingKey(self, rawStr: str, senderIp: str | None) -> str | None:
        incomingKey: str | None = None

        try:
            msgObj = json.loads(rawStr)
            if isinstance(msgObj, dict):
                hostVal = msgObj.get("name") or msgObj.get("host")
                incomingKey = parseStr(hostVal)
        except Exception:
            incomingKey = None

        if incomingKey is None:
            incomingKey = parseStr(senderIp)

        return incomingKey

    def loop(self) -> None:
        sockObj = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sockObj = sockObj

        sockObj.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            sockObj.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEPORT, 1)
        except Exception:
            pass

        sockObj.bind((self.bindIp, int(self.port)))
        sockObj.settimeout(0.2)

        nextEmitTs = 0.0

        while self.stopEvent is not None and not self.stopEvent.is_set():
            nowTs = time.time()

            # recv
            try:
                dataBytes, addr = sockObj.recvfrom(65535)
                senderIp = addr[0] if isinstance(addr, tuple) and addr else None

                rawStr = dataBytes.decode("utf-8", errors="replace").strip()

                canonical: str | None = None
                subsSnap: list["UdpPlugin"] = []
                logEnabled = False

                with self.lockObj:
                    # match strictly by source IP
                    if senderIp:
                        canonical = self.keyMapLower.get(senderIp.lower())

                    if canonical:
                        st = self.statsByHost.setdefault(canonical, HostStats())
                        st.lastSeenTs = nowTs
                        st.packetCount += 1
                        st.byteCount += len(dataBytes)

                        subsSnap = list(self.subsByHost.get(canonical, []))
                        logEnabled = any(p.logMessages for p in subsSnap)


                if canonical and subsSnap and logEnabled:
                    for p in subsSnap:
                        if p.logMessages:
                            p.writeLog(rawStr)

            except socket.timeout:
                pass
            except Exception:
                pass

            # emit
            if nowTs >= nextEmitTs:
                nextEmitTs = nowTs + float(self.emitEverySec)

                with self.lockObj:
                    self.updateRatesLocked(nowTs)
                    statsSnap = dict(self.statsByHost)
                    subsByHostSnap = {k: list(v) for k, v in self.subsByHost.items()}

                for hostKey, subs in subsByHostSnap.items():
                    st = statsSnap.get(hostKey) or HostStats()
                    for p in subs:
                        p.emitStatus(nowTs, st)


_udpLockObj = threading.Lock()
_udpListenersByKey: dict[tuple[str, int], UdpListener] = {}


class UdpPlugin(PluginBase):
    typeName: str = "udp"

    def __init__(self, core: MonitorCore, *, hostKey: str, params: dict[str, Any]) -> None:
        super().__init__(core, hostKey=hostKey, params=params)

        self.bindIp = parseStr(params.get("bindIp")) or "0.0.0.0"
        self.port = parseInt(params.get("port"), 5000)
        self.emitEverySec = parseFloat(params.get("emitEverySec"), 0.25)
        self.okAfterSec = parseFloat(params.get("okAfterSec"), 1.0)
        self.offlineAfterSec = parseFloat(params.get("offlineAfterSec"), 10.0)
        self.serviceName = parseStr(params.get("serviceName")) or "UDP"
        self.showPacketStats = parseBool(params.get("showPacketStats"), True)

        self.aliases = parseStrList(params.get("aliases"))

        hostStr = parseStr(params.get("host"))
        nameStr = parseStr(params.get("name"))

        aliasLowerSet = {a.lower() for a in self.aliases if a}

        for s in (hostStr, nameStr):
            if s and s.lower() not in aliasLowerSet:
                self.aliases.append(s)
                aliasLowerSet.add(s.lower())

        self.listener: UdpListener | None = None

    def commands(self) -> list[CommandSpec]:
        return []

    def start(self) -> None:
        txt = f"{self.serviceName}: OFFLINE"
        if self.showPacketStats:
            txt += " (udpPps=0.0)"

        self.writeTable(
            TableRow(
                host=self.hostKey,
                ip=None,
                source="udp",
                text=txt,
                severity="bad",
                ts=0.0,
            )
        )

        key = (self.bindIp, int(self.port))
        with _udpLockObj:
            listener = _udpListenersByKey.get(key)
            if listener is None:
                listener = UdpListener(bindIp=self.bindIp, port=int(self.port), emitEverySec=float(self.emitEverySec))
                _udpListenersByKey[key] = listener
            self.listener = listener
            listener.addSub(self, aliases=list(self.aliases or []))

    def stop(self) -> None:
        if self.listener is None:
            return

        key = (self.bindIp, int(self.port))
        with _udpLockObj:
            listener = _udpListenersByKey.get(key)
            if listener is not None:
                listener.removeSub(self)
                listener.stopIfIdle()
                if listener.threadObj is None:
                    _udpListenersByKey.pop(key, None)

        self.listener = None

    def execCommand(self, cmd: CommandSpec) -> None:
        return

    def emitStatus(self, nowTs: float, st: HostStats) -> None:
        lastSeen = float(st.lastSeenTs or 0.0)

        if lastSeen <= 0.0:
            sev = "bad"
            txt = "OFFLINE"
            tsVal = 0.0
        else:
            age = nowTs - lastSeen
            if age >= float(self.offlineAfterSec):
                sev = "bad"
                txt = "OFFLINE"
            elif age >= float(self.okAfterSec):
                sev = "warn"
                txt = "WARN"
            else:
                sev = "ok"
                txt = "OK"
            tsVal = lastSeen

        suffix = ""
        if self.showPacketStats:
            suffix = f" (udpPps={st.pps:.1f})"

        self.writeTable(
            TableRow(
                host=self.hostKey,
                ip=None,
                source="udp",
                text=f"{self.serviceName}: {txt}{suffix}",
                severity=sev,
                ts=tsVal,
            )
        )


def createPlugin(core: MonitorCore, hostKey: str, params: dict[str, Any]) -> UdpPlugin:
    return UdpPlugin(core, hostKey=hostKey, params=params)
