from __future__ import annotations

from pathlib import Path

from .config import *
from .pluginLoader import *
from .utils import *



def loadConfigDir(configDir: str, *, pluginRegistry: PluginRegistry) -> MonitorConfig:
    cfgDirPath = Path(configDir)
    refreshRateSec = 0.05
    reservedKeys = {"host", "name", "refreshRateSec", "enabled", "order"}
    elementsList: list[ElementConfig] = []

    for filePath in sorted(cfgDirPath.glob("*.toml")):
        hostCfg = loadToml(filePath)

        identityHost = str(hostCfg.get("host", "")).strip()
        identityName = str(hostCfg.get("name", "")).strip()
        identityKey = identityName or identityHost
        if not identityKey:
            raise RuntimeError(f"{filePath.name}: missing 'host' or 'name'")

        enabledVal = hostCfg.get("enabled", True)
        if (enabledVal is False) or (
            enabledVal not in (True, 1) and str(enabledVal).strip().lower() in ("0", "false", "no", "off")
        ):
            continue

        try:
            hostOrder = int(hostCfg.get("order", 1000))
        except Exception:
            hostOrder = 1000

        rrVal = hostCfg.get("refreshRateSec")
        try:
            if rrVal is not None and str(rrVal).strip():
                refreshRateSec = float(rrVal)
        except Exception:
            pass

        for sectionName, sectionVal in hostCfg.items():
            if sectionName in reservedKeys or not isinstance(sectionVal, dict):
                continue

            loaded = pluginRegistry.resolve(sectionName)
            if loaded is None:
                continue

            mergedParams = deepMerge(dict(loaded.meta.defaultParams or {}), dict(sectionVal))

            if not (isinstance(mergedParams.get("host"), str) and mergedParams["host"].strip()):
                mergedParams["host"] = identityHost or identityKey
            if not (isinstance(mergedParams.get("name"), str) and mergedParams["name"].strip()):
                mergedParams["name"] = identityKey

            elementsList.append(
                ElementConfig(
                    type=str(sectionName),
                    name=str(identityKey),
                    params=mergedParams,
                    enabled=True,
                    order=hostOrder,
                )
            )

    return MonitorConfig(refreshRateSec=refreshRateSec, elements=elementsList)



