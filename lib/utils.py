from __future__ import annotations
from pathlib import Path
from typing import Any

import tomli

def safeStr(val: Any) -> str:
    try:
        return str(val)
    except Exception:
        return ""


def parseStr(val: Any) -> str | None:
    if val is None:
        return None
    s = safeStr(val).strip()
    return s if s else None


def parseStrLower(val: Any) -> str | None:
    s = parseStr(val)
    return s.lower() if s else None


def parseInt(val: Any, defaultVal: int) -> int:
    if val is None:
        return int(defaultVal)
    try:
        s = safeStr(val).strip()
        if not s:
            return int(defaultVal)
        return int(float(s)) if any(ch in s for ch in ".eE") else int(s)
    except Exception:
        return int(defaultVal)


def parseFloat(val: Any, defaultVal: float) -> float:
    if val is None:
        return float(defaultVal)
    try:
        s = safeStr(val).strip()
        if not s:
            return float(defaultVal)
        return float(s)
    except Exception:
        return float(defaultVal)


def parseBool(val: Any, defaultVal: bool) -> bool:
    if isinstance(val, bool):
        return bool(val)
    if isinstance(val, (int, float)):
        return bool(val)

    s = parseStrLower(val)
    if not s:
        return bool(defaultVal)

    if s in ("1", "true", "yes", "y", "on", "enabled"):
        return True
    if s in ("0", "false", "no", "n", "off", "disabled"):
        return False
    return bool(defaultVal)


def parseStrList(val: Any) -> list[str]:
    if isinstance(val, list):
        out: list[str] = []
        for x in val:
            s = parseStr(x)
            if s:
                out.append(s)
        return out

    s = parseStr(val)
    return [s] if s else []


def loadToml(pathObj: Path) -> dict[str, Any]:
    dataObj = tomli.loads(pathObj.read_text(encoding="utf-8"))
    if isinstance(dataObj, dict):
        return dataObj
    raise RuntimeError(f"{pathObj.name}: invalid toml root")


def deepMerge(baseObj: dict[str, Any], overrideObj: dict[str, Any]) -> dict[str, Any]:
    outObj = dict(baseObj)
    for k, v in overrideObj.items():
        a = outObj.get(k)
        outObj[k] = deepMerge(dict(a), v) if isinstance(a, dict) and isinstance(v, dict) else v
    return outObj
