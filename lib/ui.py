from __future__ import annotations

import os
import time
import textwrap
from typing import Any

from rich.console import Console
from rich.layout import Layout
from rich.live import Live
from rich.table import Table
from rich.text import Text
from rich import box
from rich.padding import Padding
from rich.panel import Panel
from rich.console import Group
from rich.align import Align

from .core import *
from .keyReader import KeyReader

class RichUi:
    def __init__(
        self,
        core: MonitorCore,
        *,
        refreshRateSec: float = 0.01,
        console: Console | None = None,
    ) -> None:
        

        self.core = core
        self.refreshRateSec = float(refreshRateSec)
        self.console = console or Console()
        self.keyReader = KeyReader()

        self.styleHeader = "bold black on magenta"
        self.styleFooter = "bright white on blue"
        self.styleFooterCmd = "black on white"
        self.styleTableHeader = "bold magenta"
        self.styleSelected = "bold on blue"

        self.showOverlay = False
        self.overlayScrollPos = 0




        self.styleTable = "bright"
        self.styleLog   = "dim"

        self.commandMode = False
        self.commandBuf = ""
        self.commandLast = ""

        self.focusPane: str = "table"  # "table" | "log"

        self.maximizeWindow = 0
        self.layoutChanged  = False

        self.scrollPos = 0  # <= 0 (0 == tail)
        self.cmdLogBottomPadding = 2
        self.lastCmdLogMaxStart = 0

        self.severityStyle = {
            "ok": "green",
            "warn": "yellow",
            "bad": "red",
            "info": "dim",
        }


    def toSingleLine(self, text: str) -> str:
        return " ".join(str(text).replace("\r", "").splitlines()).strip()

    def wrapLine(self, text: str, width: int) -> list[str]:

        clean = self.toSingleLine(text)
        if not clean:
            return [""]
        return textwrap.wrap(clean, width=width, break_long_words=True, break_on_hyphens=False) or [""]

    def setFocus(self, pane: str) -> None:
        if pane in ("table", "log"):
            self.focusPane = pane
            if "log" in pane:
                self.styleSelected = ""
                self.styleTable = "dim"
                self.styleLog   = "bright"

            else:
                self.styleSelected = "bold on blue"
                self.styleTable = "white"
                self.styleLog   = "dim"


    def moveSelection(self, delta: int) -> None:
        if not self.core.hostOrder:
            self.core.selectedIndex = 0
            return

        newIndex = int(self.core.selectedIndex) + int(delta)
        if newIndex < 0:
            newIndex = 0
        maxIndex = len(self.core.hostOrder) - 1
        if newIndex > maxIndex:
            newIndex = maxIndex
        self.core.selectedIndex = newIndex

    def scrollLog(self, delta: int) -> None:
        # delta: +1 => older (up), -1 => newer (down towards tail)
        if delta > 0:
            self.scrollPos -= 1
            if -self.scrollPos > self.lastCmdLogMaxStart:
                self.scrollPos = -self.lastCmdLogMaxStart
            return

        if delta < 0:
            self.scrollPos = min(0, self.scrollPos + 1)
            return

    def handleKeys(self) -> None:

        ch = self.keyReader.readCharNonBlocking()
        if ch is None:
            return
        
        self.core.writeLog(f"KEY: {repr(ch)}")
        
        overlayCheck = False
        if self.showOverlay: 
            self.showOverlay  = False
            overlayCheck = True

        

        if not self.commandMode:

            if ch ==  "KEY_F1" and overlayCheck == False:
                self.showOverlay = True
                return

            # TODO: commandBuf not clear on start commandMode
            if ch == ":":
                self.showOverlay = False
                self.commandMode = True
                self.keyReader.enableTyping = True
                #self.commandBuf = ""
                self.core.statusMsg = "cmd"
                return
            


            if ch in ("KEY_LEFT", "h"):
                self.setFocus("table")

                return

            if ch in ("KEY_RIGHT", "l"):
                self.setFocus("log")

                return

            
            #TODO: make left or write window active
            if ch == "CTRL_LEFT":
                self.maximizeWindow += 1
                return

            if ch == "CTRL_RIGHT":
                self.maximizeWindow -= 1
                return

            if ch in ("KEY_UP","k"):
                if self.focusPane == "log":
                    self.scrollLog(+1)
                else:
                    self.moveSelection(-1)
                return

            if ch in ("KEY_DOWN","j"):
                if self.focusPane == "log":
                    self.scrollLog(-1)
                else:
                    self.moveSelection(+1)
                return

            if ch == "g":
                if self.focusPane == "log":
                    self.scrollPos = 0
                else:
                    self.core.selectedIndex = 0
                return

            if ch == "G":
                if self.focusPane == "log":
                    self.scrollPos = -self.lastCmdLogMaxStart
                else:
                    if self.core.hostOrder:
                        self.core.selectedIndex = max(0, len(self.core.hostOrder) - 1)
                return

            ########### shortcuts for core commands #########################

            if ch == "+":

                self.commandBuf ="ls+"
                self.core.execCommand(self.commandBuf)
                self.commandLast = self.commandBuf
                self.commandBuf = ""
                return


            if ch == "-":

                self.commandBuf ="ls-"
                self.core.execCommand(self.commandBuf)
                self.commandLast = self.commandBuf
                self.commandBuf = ""
                return

            if ch == ".":

                self.commandBuf = self.commandLast
                self.core.execCommand(self.commandBuf)
                self.commandLast = self.commandBuf
                self.commandBuf = ""


            return

        if ch in ("\r", "\n"):
            # TODO: commandBuf replace only if command is not empty ?
            self.core.execCommand(self.commandBuf)
            self.commandMode = False
            self.keyReader.enableTyping = False
            self.commandLast = self.commandBuf
            self.commandBuf = ""

            return

        if ch in ("\x08", "\x7f"):  # backspace
            self.commandBuf = self.commandBuf[:-1]
            return


        if ch == "\x1b": # ESC
            self.commandMode = False
            self.commandBuf = ""
            self.keyReader.enableTyping = False
            self.showOverlay = False

            return

        if ch.isprintable():
            self.commandBuf += ch

        


    def buildHelpLine(self) -> str:
        cmds = self.core.getCommandsForSelectedHost()
        parts: list[str] = []
        for c in cmds:
            labelStr = c.label.strip() if c.label else c.key
            parts.append(f":{c.key} {labelStr}")
        return "  " + "   ".join(parts) + "  "

    def panelBox(self, pane: str):
        return box.DOUBLE if self.focusPane == pane else box.SQUARE

    def renderHeader(self) -> Text:
        width = self.console.size.width
        nowStr = time.strftime("%H:%M:%S")

        left = "  OVERLORD"
        right = f"{nowStr}  "

        fill = max(1, width - len(left) - len(right))
        return Text(left + (" " * fill) + right, style=self.styleHeader)

    def renderFooter(self) -> Text:
        width = self.console.size.width
        promptStr = f":{self.commandBuf}" if self.commandMode else ""
        promptStr = promptStr[:width]

        helpStr = self.buildHelpLine()
        

        right = helpStr
        fill = max(1, width - len(promptStr) - len(right))

        footerStyle = self.styleFooterCmd if self.commandMode else self.styleFooter

        t = Text(promptStr, style=footerStyle)
        if not self.commandMode:
            t.append(right, style=footerStyle)
        if fill:
            t.append(" " * fill, style=footerStyle)
        if self.commandMode:
            t.append(right, style=footerStyle)
        return t
    

    def renderOverlay(self) -> Panel:
        helpText = """
    OVERLORD — Help / Man Page

    Global
    --------------------------------    
    F1           toggle help
    ESC          close help

    Focus
    --------------------------------
    h / LEFT     focus table
    l / RIGHT    focus log

    Table
    --------------------------------
    k / UP       select prev host
    j / DOWN     select next host
    g            jump top
    G            jump bottom

    Log
    --------------------------------
    k / UP       scroll older
    j / DOWN     scroll newer
    g            tail
    G            oldest visible

    Layout
    --------------------------------
    CTRL+h       widen table
    CTRL+l       widen log

    Command Mode
    --------------------------------
    :            enter command mode
    ENTER        execute
    BACKSPACE    edit
    ESC          cancel

    Shortcuts
    +            exec 'ls+'
    -            exec 'ls-'
    .            repeat last command

    
    
    
    
    ────────────────────────────────
    (c) 2026 https://github.com/pyrrrrr

    Licensed under the GNU General Public License v3.0
    https://www.gnu.org/licenses/gpl-3.0.html


    """.strip("\n")

        txt = Text(helpText)

        return Panel(
            Padding(txt, (1, 2)),
            title="HELP",
            subtitle="PRESS ANY KEY TO CLOSE",
            box=box.DOUBLE,
            style="bright_white on black",
        )




    def getLogPaneWidth(self) -> int:
        totalWidth = int(self.console.size.width)

        # ratios like buildLayout()
        self.maximizeWindow = max(-3, min(3, int(self.maximizeWindow)))
        tableRatio = 5 + self.maximizeWindow * 2
        logRatio = 5 - self.maximizeWindow * 2

        # clamp to keep sane
        tableRatio = max(1, int(tableRatio))
        logRatio = max(1, int(logRatio))
        denom = tableRatio + logRatio

        # approximate available width for log pane (minus some gutters/borders)
        paneWidth = int(totalWidth * (logRatio / float(denom)))
        paneWidth = max(20, paneWidth)

        # Panel border + padding + some safety
        innerWidth = max(10, paneWidth - 4)
        return innerWidth


    def renderCmdLog(self) -> Panel:
        windowHeight = max(1, self.console.size.height - 4 - self.cmdLogBottomPadding)


        displayLines: list[str] = []
        logWrapWidth = self.getLogPaneWidth()

        for ln in self.core.commandLog:
            displayLines.extend(self.wrapLine(ln, logWrapWidth))

        total = len(displayLines)
        endBase = total
        startBase = max(0, endBase - windowHeight)

        self.lastCmdLogMaxStart = startBase

        start = max(0, startBase + self.scrollPos)  # scrollPos <= 0
        if start > startBase:
            start = startBase

        end = min(total, start + windowHeight)

        visible = displayLines[start:end]
        padded = visible + [""] * self.cmdLogBottomPadding

        logText = Text("\n".join(padded))
        title = f""

        return Panel(
            logText,
            title=title,
            expand=True,
            box=self.panelBox("log"),
            style=self.styleLog
        )

    def formatStatusLines(self, statusLines: list[Any]) -> Text:
        outText = Text()
        if not statusLines:
            outText.append("PING: -", style="dim")
            return outText

        for idx, ln in enumerate(statusLines):
            if idx:
                outText.append("\n")

            sev = str(getattr(ln, "severity", "info") or "info").lower()
            style = self.severityStyle.get(sev, "white")

            lineText = str(getattr(ln, "text", "") or "").strip() or "-"
            outText.append(lineText, style=style)

        return outText

    def renderTable(self) -> Table:
        # Breiten dynamisch aus verfügbarer Panel-Breite ableiten
        contentWidth = max(40, (self.console.size.width // 2) - 6)

        numWidth = 4
        hostMin = 16
        ipMin = 12

        remaining = contentWidth - (numWidth + hostMin + ipMin)
        if remaining < 10:
            remaining = 10

        hostWidth = hostMin + max(0, remaining // 4)  # ~25%
        ipWidth = ipMin + max(0, remaining // 3)      # ~33%

        tableObj = Table(
            expand=True,
            show_header=True,
            header_style=self.styleTableHeader,
            show_lines=False,
            pad_edge=False,
            box=box.SQUARE,
            style=self.styleTable
        )

        tableObj.add_column("#", ratio=1, justify="right", no_wrap=True)
        tableObj.add_column("HOST",ratio=2, no_wrap=True, overflow="ellipsis")
        tableObj.add_column("IP", ratio=2, no_wrap=True, overflow="ellipsis")
        tableObj.add_column("STATUS", ratio=3)
        tableObj.add_column("LOG" ,ratio=1)

        if not self.core.hostOrder:
            tableObj.add_row("-", "-", "-", "-")
            return tableObj

        for hostIdx, hostKey in enumerate(self.core.hostOrder):
            st = self.core.hostsByName[hostKey]
            rowStyle = self.styleSelected if hostIdx == self.core.selectedIndex else self.styleTable

            statusText = self.formatStatusLines(st.statusLines)
            statusLog = "True" if st.getLogMessageState() else "False"
            tableObj.add_row(
                str(hostIdx + 1),
                st.host,
                st.ip or "-",
                statusText,
                statusLog,
                style=rowStyle,
            )

            if hostIdx < len(self.core.hostOrder) - 1:
                tableObj.add_section()

        return tableObj


    def renderTablePanel(self) -> Panel:
        return Panel(
            self.renderTable(),
            expand=True,
            box=self.panelBox("table"),
        )

    def buildLayout(self) -> Layout:
        layoutObj = Layout(name="root")
        content = Layout(name="content")

        self.maximizeWindow = max(-3, min(3, self.maximizeWindow))

        if self.showOverlay:
            content.update(self.renderOverlay())
        else:
            content.split_row(
                Layout(self.renderTablePanel(), name="table", ratio=5 + self.maximizeWindow * 2),
                Layout(self.renderCmdLog(), name="cmdLog", ratio=5 - self.maximizeWindow * 2),
            )

        layoutObj.split_column(
            Layout(self.renderHeader(), name="header", size=1),
            content,
            Layout(self.renderFooter(), name="footer", size=1),
        )

        return layoutObj




    def runLoop(self, tickFn) -> None:
        with Live(console=self.console, auto_refresh=False, screen=True) as live:
            while True:
                nowTs = time.time()

                self.handleKeys()
                tickFn()

                
                

                live.update(self.buildLayout(), refresh=True)
                time.sleep(self.refreshRateSec)