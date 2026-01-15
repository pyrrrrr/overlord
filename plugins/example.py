from __future__ import annotations
import time
import threading
import random
from typing import Any

from lib.core import MonitorCore
from lib.pluginApi import PluginMeta, TableRow
from lib.pluginBase import PluginBase

typeName = "example"

pluginMeta = PluginMeta(
    typeName="example",
    defaultParams={
        "everySec": 3.0,
    },
    exposeStatus=True,
    showInTable=True,
)


class ExamplePlugin(PluginBase):
    typeName = "example"

    def __init__(self, core: MonitorCore, *, hostKey: str, params: dict[str, Any]) -> None:
        super().__init__(core, hostKey=hostKey, params=params)
        self.everySec = float(params.get("everySec", 3.0))
        self.stopEvent: threading.Event | None = None

    def start(self) -> None:
        self.stopEvent = threading.Event()
        threading.Thread(target=self.loop, daemon=True).start()

    def stop(self) -> None:
        if self.stopEvent:
            self.stopEvent.set()

    def loop(self) -> None:
        states = [
            ("ok", "EXAMPLE: OK"),
            ("warn", "EXAMPLE: WARN"),
            ("bad", "EXAMPLE: FAIL"),
        ]


        while self.stopEvent and not self.stopEvent.is_set():
            sev, text = random.choice(states)

            self.writeTable(
                TableRow(
                    host=self.hostKey,
                    source="example",
                    text=text,
                    severity=sev,
                    ts=time.time(),
                )
            )

            time.sleep(self.everySec)


def createPlugin(core: MonitorCore, hostKey: str, params: dict[str, Any]) -> ExamplePlugin:
    return ExamplePlugin(core, hostKey=hostKey, params=params)