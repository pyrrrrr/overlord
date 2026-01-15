#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import socket
import subprocess
from typing import Any


def isProcessRunning(processName: str) -> bool:
    procName = processName.strip().lower()
    if not procName:
        return False

    proc = subprocess.run(["tasklist", "/FO", "CSV", "/NH"], capture_output=True, text=True)
    if proc.returncode != 0:
        raise RuntimeError(proc.stderr.strip() or "tasklist failed")

    for line in proc.stdout.splitlines():
        line = line.strip()
        if not line:
            continue
        imageName = line.split('","', 1)[0].strip('"').lower()
        if imageName == procName:
            return True
    return False


def createUdpSocket(bindIp: str, port: int) -> socket.socket:
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)

    # Safe defaults
    try:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    except Exception:
        pass

    # Windows-specific: prevent UDP "connection reset" exceptions (WinError 10054)
    # Only available on Windows builds of Python / Winsock.
    if os.name == "nt":
        try:
            sock.ioctl(socket.SIO_UDP_CONNRESET, False)  # type: ignore[attr-defined]
        except Exception:
            # If not supported, we still handle it via try/except around recvfrom.
            pass

    sock.bind((bindIp, int(port)))
    return sock


def runUdpServer(bindIp: str, port: int) -> None:
    sock = createUdpSocket(bindIp, port)

    while True:
        try:
            dataBytes, addr = sock.recvfrom(64 * 1024)
        except ConnectionResetError:
            # Windows: remote endpoint disappeared -> keep server alive
            continue
        except OSError:
            # Defensive: keep server alive on transient socket errors
            continue

        respObj: dict[str, Any]
        try:
            reqObj = json.loads(dataBytes.decode("utf-8", errors="replace"))
            if not isinstance(reqObj, dict):
                continue

            cmd = str(reqObj.get("cmd", "")).strip().lower()
            if cmd == "health":
                respObj = {"ok": True}

            elif cmd == "check":
                nameVal = str(reqObj.get("name", "")).strip()
                if not nameVal:
                    respObj = {"ok": False, "error": "missing name"}
                else:
                    runningVal = isProcessRunning(nameVal)
                    respObj = {"ok": True, "process": nameVal, "running": runningVal}

            else:
                respObj = {"ok": False, "error": "bad cmd"}

        except Exception as exc:
            respObj = {"ok": False, "error": f"{type(exc).__name__}: {exc}"}

        try:
            sock.sendto(json.dumps(respObj, ensure_ascii=False).encode("utf-8"), addr)
        except OSError:
            # If client is gone, ignore; next recvfrom may otherwise trigger reset (handled above / ioctl)
            continue


def main() -> int:
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--bind", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args()

    runUdpServer(args.bind, int(args.port))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
