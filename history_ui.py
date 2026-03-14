"""UI for module history: dialogs and widgets (commit message, full file view)."""

from __future__ import annotations

import os
import subprocess
import xml.etree.ElementTree as ET
from typing import Tuple

from . import history
from .core import Module, getHistoryPath, MODULE_EXT, Settings
from .qt import (
    QCheckBox,
    QDialog,
    QPlainTextEdit,
    QPushButton,
    QFont,
    QLineEdit,
    QLabel,
    QDialogButtonBox,
    QMessageBox,
    QMenu,
    Qt,
    QUrl,
    QVBoxLayout,
    QWidget,
    QTextBrowser,
    QTextCursor,
    Signal,
    execFunc,
)
from .ui_utils import centerWindow


def showCommitMessageDialog(parent) -> Tuple[bool, str]:
    """Show optional commit message dialog before save. Returns (accepted, message)."""
    dlg = QDialog(parent)
    dlg.setWindowTitle("Save module")
    layout = QVBoxLayout(dlg)
    layout.addWidget(QLabel("Commit message (optional):"))
    lineEdit = QLineEdit()
    lineEdit.setPlaceholderText("e.g. update myModule.xml")
    layout.addWidget(lineEdit)
    bbox = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
    bbox.accepted.connect(dlg.accept)
    bbox.rejected.connect(dlg.reject)
    layout.addWidget(bbox)
    accepted = dlg.exec_() == QDialog.Accepted
    return (accepted, lineEdit.text().strip() if accepted else "")


class FullFileViewDialog(QDialog):
    """Modal dialog showing full file content at a given revision."""

    def __init__(self, content: str, rev: str, fileName: str, parent=None):
        super().__init__(parent)
        self.setWindowTitle("{} at {}".format(fileName, rev))
        self.setMinimumSize(600, 400)
        self.resize(800, 500)
        layout = QVBoxLayout(self)
        self.textEdit = QPlainTextEdit()
        self.textEdit.setReadOnly(True)
        self.textEdit.setFont(QFont("Consolas", 10))
        self.textEdit.setPlainText(content)
        layout.addWidget(self.textEdit)
        closeBtn = QPushButton("Close")
        closeBtn.clicked.connect(self.accept)
        layout.addWidget(closeBtn)
        centerWindow(self)


class ModuleHistoryWidget(QWidget):
    """Widget with filter and text browser showing module history (git log). Emits linkClicked(url) for link handling."""

    linkClicked = Signal(object)

    def __init__(self, mainWindow):
        super().__init__(parent=mainWindow)
        self.mainWindow = mainWindow

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self.trackHistoryCheckbox = QCheckBox("Track history")
        self.trackHistoryCheckbox.setChecked(Settings.get("trackHistory", True))
        self.trackHistoryCheckbox.setToolTip("When unchecked, saves are not committed to git history")
        self.trackHistoryCheckbox.stateChanged.connect(self._onTrackHistoryToggled)
        self.filterEdit = QLineEdit()
        self.filterEdit.setPlaceholderText("Filter by module name or UID")
        self.filterEdit.setClearButtonEnabled(True)
        self.filterEdit.textChanged.connect(self.updateModuleHistory)

        self.textBrowser = QTextBrowser()
        self.textBrowser.setOpenLinks(False)
        self.textBrowser.setContextMenuPolicy(Qt.CustomContextMenu)
        self.textBrowser.customContextMenuRequested.connect(self._onTextBrowserContextMenu)
        self.textBrowser.anchorClicked.connect(self._onAnchorClicked)

        layout.addWidget(self.filterEdit)
        layout.addWidget(self.textBrowser)
        layout.addWidget(self.trackHistoryCheckbox)
        self.updateModuleHistory()

    def isHistoryTrackingEnabled(self) -> bool:
        """Return True if git history tracking is enabled (saves will be committed)."""
        return self.trackHistoryCheckbox.isChecked()

    def _onTrackHistoryToggled(self, state):
        """Update in-memory track history setting; persisted when workspace is saved."""
        Settings["trackHistory"] = state == Qt.Checked

    def handleHistoryLink(self, url) -> bool:
        """
        Handle history links: history:rev:uid (diff), history:full:rev:uid (full),
        history:recover:rev:uid (add to tree). Return True if handled.
        """
        urlStr = QUrl(url).toString()
        if not urlStr.startswith(history.HISTORY_LINK_SCHEME + ":"):
            return False

        parts = urlStr[len(history.HISTORY_LINK_SCHEME) + 1 :].lstrip("/").split(":")
        action = parts[0] if len(parts) >= 3 else None
        if action in ("full", "recover"):
            rev, uid = parts[1], parts[2]
        elif len(parts) >= 2:
            rev, uid = parts[0], parts[1]
            action = None
        else:
            return False

        repo = history.getHistoryRepo()
        if not repo:
            return True

        fileName = uid + MODULE_EXT
        if action == "full":
            err, content = repo("show {}:{}".format(rev, fileName))
            if not err and content:
                dlg = FullFileViewDialog(content.strip(), rev, fileName, parent=self.mainWindow)
                execFunc(dlg)

        elif action == "recover":
            err, content = repo("show {}:{}".format(rev, fileName))
            if not err and content:
                try:
                    root = ET.fromstring(content.strip())
                    module = Module.fromXml(root)
                    self.mainWindow.addModule(module)

                except Exception:
                    pass

        else:
            err, diffText = repo("show --minimal {} -- {}".format(rev, fileName))
            if not err and diffText:
                self.mainWindow.showDiffView(diffText.strip(), "{}^".format(rev), rev)

        return True

    def _onAnchorClicked(self, url):
        if self.handleHistoryLink(url):
            return
        self.linkClicked.emit(url)

    def _onTextBrowserContextMenu(self, pos):
        menu = QMenu(self.textBrowser)
        menu.addAction("Squash history").triggered.connect(self._onSquashHistory)
        menu.addAction("Open history folder").triggered.connect(self._onOpenHistoryFolder)
        menu.exec_(self.textBrowser.mapToGlobal(pos))

    def _onOpenHistoryFolder(self):
        path = getHistoryPath()
        if os.path.isdir(path):
            subprocess.call("explorer \"{}\"".format(os.path.normpath(path)))

    def _onSquashHistory(self):
        if QMessageBox.question(
            self.mainWindow,
            "Squash history",
            "Squash all commits into one? This flushes the git history.",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        ) != QMessageBox.Yes:
            return
        success, errMsg = history.squashHistory("Initial squashed")
        if success:
            self.updateModuleHistory()
        else:
            QMessageBox.warning(
                self.mainWindow,
                "Squash history",
                "Squash failed: {}".format(errMsg),
            )

    def showCommitMessageDialog(self):
        """Show commit message dialog using the widget's main window. Returns (accepted, message)."""
        return showCommitMessageDialog(self.mainWindow)

    def updateModuleHistory(self):
        """Update the module history widget with the latest history."""
        filterText = self.filterEdit.text().strip() if hasattr(self, "filterEdit") else ""
        html = history.buildHistoryHtml(filterText)
        self.textBrowser.clear()
        self.textBrowser.insertHtml(html)
        self.textBrowser.moveCursor(QTextCursor.Start)
