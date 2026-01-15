from __future__ import annotations

import threading
import time
import urllib.error
import urllib.request
from typing import Any

from lib.core import MonitorCore
from lib.pluginApi import PluginMeta, TableRow
from lib.pluginBase import PluginBase
from lib.utils import parseBool, parseFloat, parseInt, parseStr

typeName = "http"

pluginMeta = PluginMeta(
    typeName="http",
    defaultParams={
        "host": None,
        "port": None,
        "url": "/",
        "forceHttps": False,
        "everySec": 5.0,
        "timeoutSec": 2.0,
    },
    exposeStatus=True,
    showInTable=True,
)


def buildUrl(host: str, port: int | None, path: str, forceHttps: bool) -> str:
    if not host or not path:
        return ""

    scheme = "https" if forceHttps else "http"
    host = host.strip()
    path = path.strip()

    if port:
        base = f"{scheme}://{host}:{int(port)}"
    else:
        base = f"{scheme}://{host}"

    if path.startswith("/"):
        return base + path
    return base + "/" + path


def fetch(url: str, timeoutSec: float) -> tuple[int | None, str]:
    req = urllib.request.Request(url, method="HEAD", headers={"User-Agent": "Overlord/1.0"})
    try:
        with urllib.request.urlopen(req, timeout=max(0.1, timeoutSec)) as resp:
            return int(resp.status), ""
    except urllib.error.HTTPError as exc:
        return int(exc.code), str(exc.reason or "").strip()
    except Exception as exc:
        return None, f"{type(exc).__name__}: {exc}"


def classify(code: int | None) -> tuple[str, str]:
    if code is None:
        return "bad", "HTTP: ERR"
    if 200 <= code <= 399:
        return "ok", f"HTTP: {code}"
    if 400 <= code <= 499:
        return "warn", f"HTTP: {code}"
    return "bad", f"HTTP: {code}"


class HttpPlugin(PluginBase):
    typeName: str = "http"

    def __init__(self, core: MonitorCore, *, hostKey: str, params: dict[str, Any]) -> None:
        super().__init__(core, hostKey=hostKey, params=params)

        host = parseStr(params.get("host")) or self.hostKey
        port = parseInt(params.get("port"), 0)
        url = parseStr(params.get("url")) or "/"
        forceHttps = parseBool(params.get("forceHttps"), False)

        self.url = buildUrl(host, port if port > 0 else None, url, forceHttps)
        self.everySec = parseFloat(params.get("everySec"), 5.0)
        self.timeoutSec = parseFloat(params.get("timeoutSec"), 2.0)

        self.stopEvent: threading.Event | None = None
        self.threadObj: threading.Thread | None = None
        self.lastSev: str | None = None
        self.sentInitial = False

    def start(self) -> None:
        self.stopEvent = threading.Event()
        self.writeTable(
            TableRow(
                host=self.hostKey,
                ip=None,
                source="http",
                text=("HTTP: -" if not self.url else "HTTP: ..."),
                severity="info",
                ts=time.time(),
            )
        )
        self.threadObj = threading.Thread(target=self.loopSafe, daemon=True)
        self.threadObj.start()

    def stop(self) -> None:
        if self.stopEvent:
            self.stopEvent.set()
        self.stopEvent = None
        self.threadObj = None

    def loopSafe(self) -> None:
        try:
            self.loop()
        except Exception as exc:
            self.writeLog(f"HTTP LOOP EXC {type(exc).__name__}: {exc}")

    def loop(self) -> None:
        nextTs = 0.0
        while self.stopEvent and not self.stopEvent.is_set():
            now = time.time()
            if now >= nextTs:
                nextTs = now + max(0.2, self.everySec)

                code, err = fetch(self.url, self.timeoutSec)
                sev, text = classify(code)
                if err and sev != "ok":
                    text = f"{text} ({err})"

                if not self.sentInitial or sev != self.lastSev:
                    if self.sentInitial and sev != self.lastSev:
                        self.writeLog(f"HTTP: {self.lastSev or 'none'} -> {sev}")

                    self.writeTable(
                        TableRow(
                            host=self.hostKey,
                            ip=None,
                            source="http",
                            text=text,
                            severity=sev,
                            ts=now,
                        )
                    )
                    self.sentInitial = True
                    self.lastSev = sev

            time.sleep(0.05)


def createPlugin(core: MonitorCore, hostKey: str, params: dict[str, Any]) -> HttpPlugin:
    return HttpPlugin(core, hostKey=hostKey, params=params)
