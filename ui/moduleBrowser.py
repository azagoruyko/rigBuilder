"""Module browser widget with filter, source options, and module tree."""

from __future__ import annotations

import os
import re
import time
import subprocess
import xml.etree.ElementTree as ET
from typing import Optional, List, Dict, Tuple
import markdown

from ..qt import *
from ..core import Module, MODULE_EXTS, UidManager
from .. import settings as settings_module
from ..settings import settings, appState
from .logger import logger
from .fileTracker import DirectoryWatcher
from .utils import fontSize, setFontSize
from ..utils import clamp

_DOC_CACHE: Dict[str, Tuple[float, str]] = {} # path: (mtime, content)

def getDocFromFile(path: str) -> str:
    """Fetch doc content from file with caching based on mtime."""
    mtime = os.path.getmtime(path)
    if path in _DOC_CACHE:
        cached_mtime, content = _DOC_CACHE[path]
        if cached_mtime == mtime:
            return content
            
    content = ""
    try:
        tree = ET.parse(path)
        root = tree.getroot()
        doc_el = root.find("doc")
        if doc_el is not None:
            content = doc_el.text or ""
    except Exception:
        pass
        
    _DOC_CACHE[path] = (mtime, content)
    return content

OLD_MODULE_THRESHOLD_DAYS = 7

class ModuleBrowserTree(QTreeWidget):
    """Tree widget for browsing module files on disk."""
    
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.middlePressPos = QPoint()

        self.setHeaderLabels(["Module", "Modification time"])
        self.header().setSectionResizeMode(QHeaderView.ResizeToContents)
        self.setSortingEnabled(True)
        self.sortItems(1, Qt.DescendingOrder)

        self.setDragEnabled(True)
        self.setAcceptDrops(False)
        self.setDropIndicatorShown(False)
        self.setDragDropMode(QAbstractItemView.DragOnly)
        self.setDefaultDropAction(Qt.CopyAction)
        self.setMinimumHeight(100)

    def _collectDraggedModulePaths(self) -> List[str]:
        modulePaths = []
        for item in self.selectedItems():
            if hasattr(item, "filePath"):
                filePath = item.filePath
                if filePath:
                    modulePaths.append(filePath)
        return modulePaths

    def _startModuleDrag(self):
        modulePaths = self._collectDraggedModulePaths()
        if not modulePaths:
            return

        mimeData = QMimeData()
        mimeData.setUrls([QUrl.fromLocalFile(path) for path in modulePaths])

        drag = QDrag(self)
        drag.setMimeData(mimeData)
        drag.exec(Qt.CopyAction)

    def startDrag(self, supportedActions: Qt.DropActions):
        del supportedActions
        self._startModuleDrag()

    def mousePressEvent(self, event: QMouseEvent):
        if event.button() == Qt.MiddleButton:
            self.middlePressPos = event.pos()
            item = self.itemAt(event.pos())
            if item:
                if not (event.modifiers() & (Qt.ControlModifier | Qt.ShiftModifier)):
                    self.clearSelection()
                item.setSelected(True)
                self.setCurrentItem(item)
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event: QMouseEvent):
        if event.buttons() & Qt.MiddleButton:
            if (event.pos() - self.middlePressPos).manhattanLength() >= QApplication.startDragDistance():
                self._startModuleDrag()
                self.middlePressPos = QPoint()
                event.accept()
                return
        super().mouseMoveEvent(event)

    def contextMenuEvent(self, event: QContextMenuEvent):
        menu = QMenu(self)
        menu.addAction("Locate", self.browseModuleDirectory)
        menu.addAction("Open modules folder", self.openModulesFolder)
        menu.addAction("Set modules folder...", self.parent().browseModulesPath)
        menu.addAction("Reset modules folder", self.parent().resetModulesPath)
        menu.addSeparator()
        menu.addAction("Refresh", self.parent().refreshModules)
        menu.popup(event.globalPos())

    def browseModuleDirectory(self):
        for item in self.selectedItems():
            if hasattr(item, "filePath"):
                subprocess.call("explorer /select,\"{}\"".format(os.path.normpath(item.filePath)))

    def openModulesFolder(self):
        folderPath = settings.getModulesPath()
        subprocess.call("explorer \"{}\"".format(folderPath))
        
    def viewportEvent(self, event: QEvent) -> bool:
        if event.type() == QEvent.ToolTip:
            item = self.itemAt(event.pos())
            if item and hasattr(item, "filePath"):
                doc = getDocFromFile(item.filePath)
                if doc:
                    tooltip = markdown.markdown(
                        doc,
                        extensions=["fenced_code", "tables", "nl2br", "sane_lists", "codehilite", "toc", "extra"],
                        output_format="html5"
                    )
                    if not tooltip.startswith("<html>") and not tooltip.startswith("<!DOCTYPE"):
                        tooltip = "<html><body>" + tooltip + "</body></html>"
                    QToolTip.showText(event.globalPos(), tooltip, self)
                else:
                    QToolTip.showText(event.globalPos(), "No documentation", self)
                return True
        return super().viewportEvent(event)

    def wheelEvent(self, event: QWheelEvent):
        ctrl = event.modifiers() & Qt.ControlModifier

        if ctrl:
            delta = event.angleDelta().y()
            if delta == 0:
                return
                
            d = delta / abs(delta)
            font = self.font()
            sz = clamp(fontSize(font) + d, 6, 20)
            setFontSize(font, sz)
            self.setFont(font)
            
            # Scale indentation proportionally
            self.setIndentation(sz * 1.5)
            event.accept()
        else:
            super().wheelEvent(event)


class ModuleBrowser(QWidget):
    """Embeddable module selector with filter, source options, and module tree."""
    
    modulesReloaded = Signal()

    def __init__(self, **kwargs):
        super().__init__(**kwargs)

        layout = QVBoxLayout()
        layout.setContentsMargins(0, 0, 0, 0)
        self.setLayout(layout)

        self.pathLabel = QLabel()
        self.pathLabel.setWordWrap(True)
        self.pathLabel.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.pathLabel.setStyleSheet("color: #AAAAAA; font-style: italic; background-color: rgba(255, 255, 255, 0.05); padding: 5px; border-radius: 4px; margin-top: 5px;")

        self.maskWidget = QLineEdit()
        self.maskWidget.setPlaceholderText("Filter modules...")
        self.maskWidget.textChanged.connect(self.applyMask)

        self.clearFilterButton = QPushButton("🧹 Clear")
        self.clearFilterButton.clicked.connect(self.maskWidget.clear)
        self.clearFilterButton.hide()
        self.maskWidget.textChanged.connect(self._onMaskTextChanged)

        filterLayout = QHBoxLayout()
        filterLayout.addWidget(QLabel("Filter"))
        filterLayout.addWidget(self.maskWidget)
        filterLayout.addWidget(self.clearFilterButton)
        layout.addLayout(filterLayout)

        self.treeWidget = ModuleBrowserTree()

        layout.addWidget(self.treeWidget)
        layout.addWidget(self.pathLabel)

        self._setupAutoReloadWatcher()
        self._updatePathLabel()
        self.refreshModules()

    def _updatePathLabel(self):
        """Update the path label with the current modules directory."""
        path = os.path.normpath(settings.getModulesPath())
        userRoot = os.path.normpath(settings_module.RIG_BUILDER_USER_PATH)
        appRoot = os.path.normpath(settings_module.RIG_BUILDER_PATH)

        if path.lower().startswith(userRoot.lower()):
            rel = os.path.relpath(path, userRoot)
            displayText = "User" if rel == "." else os.path.join("User", rel)
        elif path.lower().startswith(appRoot.lower()):
            rel = os.path.relpath(path, appRoot)
            displayText = "App" if rel == "." else os.path.join("App", rel)
        else:
            displayText = path

        self.pathLabel.setText(displayText.replace('\\', '/'))

    def _setupAutoReloadWatcher(self):
        """Setup the modules auto-reload watcher."""
        watchRoots = [settings.getModulesPath()]
        self.modulesAutoReloadWatcher = DirectoryWatcher(
            watchRoots,
            filePatterns=["*" + ext for ext in MODULE_EXTS],
            debounceMs=700,
            recursive=True,
            parent=self)

        self.modulesAutoReloadWatcher.somethingChanged.connect(self.refreshModules)

    def refreshModules(self):
        """Internal refresh used by startup and auto-reload flows."""
        self._updatePathLabel()
        UidManager.update()
        self.applyMask()

    def browseModulesPath(self):
        current = settings.getModulesPath()
        folder = QFileDialog.getExistingDirectory(self, "Modules folder", current)
        if folder:
            settings.modulesPath = folder
            wsPath = settings.getCurrentWorkspacePath()
            if wsPath:
                settings.save(os.path.join(wsPath, "settings.json"))
            self.modulesAutoReloadWatcher.setRoots([folder])
            self._updatePathLabel()
            UidManager.update()
            self.applyMask()

    def resetModulesPath(self):
        settings.modulesPath = ""
        wsPath = settings.getCurrentWorkspacePath()
        if wsPath:
            settings.save(os.path.join(wsPath, "settings.json"))
        self.modulesAutoReloadWatcher.setRoots([settings.getModulesPath()])
        self._updatePathLabel()
        UidManager.update()
        self.applyMask()

    def _onMaskTextChanged(self, text: str):
        self.clearFilterButton.setVisible(bool(text))

    def applyMask(self, *_):
        """Rebuild module tree from mask and source settings. Accepts optional args from Qt signals."""
        def findChildByText(text: str, parent: QTreeWidgetItem, column: int = 0):
            for i in range(parent.childCount()):
                ch = parent.child(i)
                if text == ch.text(column):
                    return ch

        modulesDirectory = settings.getModulesPath()
        modules = sorted(UidManager.uids().values())

        self.treeWidget.clear()

        mask = self.maskWidget.text().split() # split by spaces, '/folder mask /other mask'

        # make tree dict from module files
        for f in modules:
            relativePath = os.path.relpath(f, modulesDirectory)
            relativeDir = os.path.dirname(relativePath)
            name, _ = os.path.splitext(os.path.basename(f))

            okMask = True
            dirMask = "/"+relativePath.replace("\\", "/")+"/"
            for m in mask:
                if not re.search(re.escape(m), dirMask, re.IGNORECASE):
                    okMask = False
                    break

            if not okMask:
                continue

            dirItem = self.treeWidget.invisibleRootItem()
            if relativeDir:
                for p in relativeDir.split("\\"):
                    ch = findChildByText(p, dirItem)
                    if ch:
                        dirItem = ch
                    else:
                        ch = QTreeWidgetItem([p, ""])
                        ch.setFlags((ch.flags() | Qt.ItemIsEnabled | Qt.ItemIsSelectable) & ~Qt.ItemIsDragEnabled)
                        font = ch.font(0)
                        font.setBold(True)
                        ch.setForeground(0, QColor(130, 130, 230))
                        ch.setFont(0, font)

                        dirItem.addChild(ch)
                        dirItem.setExpanded(True if mask else False)
                        dirItem = ch

            mtime = os.path.getmtime(f)
            modtime = time.strftime("%Y/%m/%d %H:%M", time.localtime(mtime))
            item = QTreeWidgetItem([name, modtime])
            item.setFlags(item.flags() | Qt.ItemIsDragEnabled)
            item.filePath = f
            
            # Highlight old modification dates
            if time.time() - mtime > OLD_MODULE_THRESHOLD_DAYS * 24 * 60 * 60:
                item.setForeground(1, QColor("#888888"))

            dirItem.addChild(item)
            dirItem.setExpanded(True if mask else False)
