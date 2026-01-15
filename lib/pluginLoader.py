
from __future__ import annotations

import importlib
import pkgutil
from dataclasses import dataclass
from typing import Any, Callable

from .pluginApi import PluginMeta

CreatePluginFn = Callable[[Any, str, dict[str, Any]], Any]


@dataclass(frozen=True)
class LoadedPlugin:
    moduleName: str
    meta: PluginMeta
    createPlugin: CreatePluginFn


class PluginRegistry:
    def __init__(self) -> None:
        self.pluginsByType: dict[str, LoadedPlugin] = {}

    def resolve(self, typeName: str) -> LoadedPlugin | None:
        key = str(typeName or "").strip().lower()
        return self.pluginsByType.get(key)

    def loadPluginModule(self, moduleName: str) -> None:
        mod = importlib.import_module(moduleName)

        metaObj = getattr(mod, "pluginMeta", None)
        if not isinstance(metaObj, PluginMeta):
            typeName = str(getattr(mod, "typeName", "") or "").strip()
            defaultParams = getattr(mod, "defaultParams", None)
            if not typeName:
                return
            metaObj = PluginMeta(
                typeName=typeName,
                defaultParams=dict(defaultParams) if isinstance(defaultParams, dict) else {},
            )

        createPluginFn = getattr(mod, "createPlugin", None)
        if not callable(createPluginFn):
            return

        key = str(metaObj.typeName or "").strip().lower()
        if not key:
            return

        self.pluginsByType[key] = LoadedPlugin(
            moduleName=moduleName,
            meta=metaObj,
            createPlugin=createPluginFn,
        )

    def loadPluginsFromPackage(self, packageName: str) -> None:
        pkg = importlib.import_module(packageName)
        pkgPath = getattr(pkg, "__path__", None)
        if pkgPath is None:
            return

        for modInfo in pkgutil.iter_modules(pkgPath, pkg.__name__ + "."):
            self.loadPluginModule(modInfo.name)

    def listTypes(self) -> list[str]:
        return sorted(self.pluginsByType.keys())