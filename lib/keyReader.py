# lib/keyReader.py
from __future__ import annotations

import queue
import threading
from dataclasses import dataclass
from typing import Optional

from readchar import readkey, key


@dataclass(frozen=True)
class KeyEvent:
    raw: str
    mapped: str


class KeyReader:
    def __init__(self) -> None:
        self.enableTyping = False

        self._q: queue.Queue[str] = queue.Queue()
        self._stopEvent = threading.Event()

        self._t = threading.Thread(target=self._loop, daemon=True, name="KeyReader")
        self._t.start()

        
        self._rawMap: dict[str, str] = {
            "\x1b[A": "KEY_UP",
            "\x1b[B": "KEY_DOWN",
            "\x1b[D": "KEY_LEFT",
            "\x1b[C": "KEY_RIGHT",
            "\x1b": "KEY_ESC",

            "\x1bOP": "KEY_F1",
            "\x1b[11~": "KEY_F1",

            "\x08": "CTRL_LEFT",   #
            "\x0c": "CTRL_RIGHT", 

            
            "\x00H": "KEY_UP",
            "\x00P": "KEY_DOWN",
            "\x00K": "KEY_LEFT",
            "\x00M": "KEY_RIGHT",

            "\x00s": "CTRL_LEFT",   
            "\x00t": "CTRL_RIGHT", 

            "\x00;": "KEY_F1",   

            
            "\xe0H": "KEY_UP",
            "\xe0P": "KEY_DOWN",
            "\xe0K": "KEY_LEFT",
            "\xe0M": "KEY_RIGHT",
            "\xe0s": "CTRL_LEFT",
            "\xe0t": "CTRL_RIGHT",
            "\xe0;": "KEY_F1",
        }

        
        self._keyConstMap: dict[str, str] = {
            key.UP: "KEY_UP",
            key.DOWN: "KEY_DOWN",
            key.LEFT: "KEY_LEFT",
            key.RIGHT: "KEY_RIGHT",
            key.ESC: "KEY_ESC",
            key.F1: "KEY_F1",
            key.BACKSPACE: "KEY_BACKSPACE",
            key.ENTER: "KEY_ENTER",
            "\x1b[1;5D": "CTRL_LEFT",
            "\x1b[1;5C": "CTRL_RIGHT",
            "\x1b[1;5A": "CTRL_UP",
            "\x1b[1;5B": "CTRL_DOWN",
        }

    def stop(self) -> None:
        self._stopEvent.set()

    def _loop(self) -> None:
        while not self._stopEvent.is_set():
            try:
                k = readkey()
            except Exception:
                continue

            
            if k == "\x1b[1;":
                try:
                    k2 = readkey()
                    k3 = readkey()
                    k = f"{k}{k2}{k3}"
                except Exception:
                    pass

            try:
                self._q.put_nowait(k)
            except Exception:
                pass

    def readCharNonBlocking(self) -> Optional[str]:
        try:
            raw = self._q.get_nowait()
        except queue.Empty:
            return None

        if self.enableTyping:
            return raw

        # First: key-constants (wenn readchar das liefert)
        mapped = self._keyConstMap.get(raw)
        if mapped:
            return self._normalize(mapped)

        # Second: raw escape sequences
        mapped = self._rawMap.get(raw)
        if mapped:
            return self._normalize(mapped)

        # Normalize enter/backspace if raw char
        if raw in ("\r", "\n"):
            return "KEY_ENTER"
        if raw in ("\x7f", "\x08"):
            return "KEY_BACKSPACE"

        return raw

    def _normalize(self, mapped: str) -> str:
        # Keep current names used by your UI
        if mapped == "KEY_ENTER":
            return "\n"
        if mapped == "KEY_BACKSPACE":
            return "\x08"
        if mapped == "KEY_ESC":
            return "\x1b"
        return mapped
