
from __future__ import annotations

from typing import Any

from .config import *
from .core import *
from .pluginLoader import *
from .ui import *


class MonitorApp:
    def __init__(self, config: MonitorConfig, *, pluginPackage: str = "plugins") -> None:

        self.config = config
        self.pluginRegistry = PluginRegistry()
        self.pluginRegistry.loadPluginsFromPackage(pluginPackage)
        self.core = MonitorCore(pluginRegistry=self.pluginRegistry)
        self.plugins: list[Any] = []
        self.ui = RichUi(self.core, refreshRateSec=float(self.config.refreshRateSec))

    
    def buildPluginsFromConfig(self) -> None:
        self.plugins.clear()

        hostOrderMap: dict[str, int] = {}

        for elCfg in self.config.elements:
            if not elCfg.enabled:
                continue

            loaded = self.pluginRegistry.resolve(elCfg.type)
            if loaded is None:
                raise RuntimeError(f"Unknown plugin type '{elCfg.type}'")

            params = dict(elCfg.params or {})
            pluginObj = loaded.createPlugin(self.core, elCfg.name, params)

            self.plugins.append(pluginObj)
            self.core.registerPlugin(pluginObj)

            hostKey = str(elCfg.name).strip() or "?"
            prev = hostOrderMap.get(hostKey)
            hostOrderMap[hostKey] = int(elCfg.order) if prev is None else min(prev, int(elCfg.order))

        self.core.hostOrder = sorted(
            self.core.hostOrder,
            key=lambda h: (hostOrderMap.get(h, 1000), h.lower()),
        )

        if self.core.hostOrder:
            self.core.selectedIndex = max(0, min(self.core.selectedIndex, len(self.core.hostOrder) - 1))
        else:
            self.core.selectedIndex = 0

    def start(self) -> None:
        for p in self.plugins:
            if hasattr(p, "start"):
                p.start()

    def stop(self) -> None:
        for p in self.plugins:
            if hasattr(p, "stop"):
                try:
                    p.stop()
                except Exception:
                    pass

    def tick(self) -> None:
        for p in self.plugins:
            if hasattr(p, "tick"):
                try:
                    p.tick()
                except Exception:
                    pass

    def run(self) -> None:



        self.buildPluginsFromConfig()
        self.start()
        try:
            self.ui.runLoop(self.tick)
        except KeyboardInterrupt:
            pass
        finally:
            self.stop()