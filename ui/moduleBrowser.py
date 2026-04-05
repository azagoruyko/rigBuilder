"""Module browser widget with filter, source options, and module tree."""

from __future__ import annotations

import os
import re
import time
import subprocess
from typing import Optional, List, Dict

from ..qt import *
from ..core import Module, getPublicModulesPath, getPrivateModulesPath, Settings
from .logger import logger

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
            filePath = getattr(item, "filePath", "")
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
        menu.addAction("Open public folder", self.openPublicModulesFolder)
        menu.addAction("Open private folder", self.openPrivateModulesFolder)
        menu.addSeparator()
        menu.addAction("Set public modules folder...", self.parent().browsePublicModulesPath)
        menu.addAction("Reset public modules folder", self.parent().resetPublicModulesPath)
        menu.addSeparator()
        menu.addAction("Refresh", self.parent().refreshModules)
        menu.popup(event.globalPos())

    def browseModuleDirectory(self):
        for item in self.selectedItems():
            if item.childCount() == 0:
                subprocess.call("explorer /select,\"{}\"".format(os.path.normpath(item.filePath)))

    def openPublicModulesFolder(self):
        folderPath = getPublicModulesPath()
        subprocess.call("explorer \"{}\"".format(folderPath))

    def openPrivateModulesFolder(self):
        folderPath = getPrivateModulesPath()
        subprocess.call("explorer \"{}\"".format(folderPath))


class ModuleBrowser(QWidget):
    """Embeddable module selector with filter, source options, and module tree."""
    
    modulesReloaded = Signal()

    def __init__(self, **kwargs):
        super().__init__(**kwargs)

        layout = QVBoxLayout()
        layout.setContentsMargins(0, 0, 0, 0)
        self.setLayout(layout)

        self.updateSourceWidget = QComboBox()
        self.updateSourceWidget.addItems(["All", "Public", "Private", "None"])
        self.updateSourceWidget.setCurrentIndex({"all": 0, "public": 1, "private": 2, "": 3}[Module.UpdateSource])
        self.updateSourceWidget.currentIndexChanged.connect(lambda *_: self.updateSource())

        self.modulesFromButtonGroup = QButtonGroup(self)
        self.modulesFromPublicRadio = QRadioButton("Public")
        self.modulesFromPrivateRadio = QRadioButton("Private")
        self.modulesFromButtonGroup.addButton(self.modulesFromPublicRadio, 0)
        self.modulesFromButtonGroup.addButton(self.modulesFromPrivateRadio, 1)
        self.modulesFromPublicRadio.setChecked(True)
        self.modulesFromButtonGroup.buttonClicked.connect(self.applyMask)

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

        controlsLayout = QHBoxLayout()
        controlsLayout.addWidget(QLabel("Modules from"))
        controlsLayout.addWidget(self.modulesFromPublicRadio)
        controlsLayout.addWidget(self.modulesFromPrivateRadio)
        controlsLayout.addStretch()
        controlsLayout.addWidget(QLabel("Update source"))
        controlsLayout.addWidget(self.updateSourceWidget)

        layout.addWidget(self.treeWidget)
        layout.addLayout(controlsLayout)

        self.refreshModules()

    def refreshModules(self):
        """Internal refresh used by startup and auto-reload flows."""
        Module.updateUidsCache()
        self.applyMask()

    def updateSource(self):
        updateSource = self.updateSourceWidget.currentIndex()
        UpdateSourceFromInt = {0: "all", 1: "public", 2: "private", 3: ""}
        Module.UpdateSource = UpdateSourceFromInt[updateSource]

    def browsePublicModulesPath(self):
        current = getPublicModulesPath()
        folder = QFileDialog.getExistingDirectory(self, "Public modules folder", current)
        if folder:
            Settings["publicModulesPath"] = folder
            Module.updateUidsCache()
            self.applyMask()

    def resetPublicModulesPath(self):
        Settings["publicModulesPath"] = ""
        Module.updateUidsCache()
        self.applyMask()

    def getModulesRootDirectory(self) -> str:
        modulesFrom = self.modulesFromButtonGroup.checkedId()
        return getPublicModulesPath() if modulesFrom == 0 else getPrivateModulesPath()

    def _onMaskTextChanged(self, text: str):
        self.clearFilterButton.setVisible(bool(text))

    def applyMask(self, *_):
        """Rebuild module tree from mask and source settings. Accepts optional args from Qt signals."""
        def findChildByText(text: str, parent: QTreeWidgetItem, column: int = 0):
            for i in range(parent.childCount()):
                ch = parent.child(i)
                if text == ch.text(column):
                    return ch

        modulesFrom = self.modulesFromButtonGroup.checkedId()
        modulesDirectory = self.getModulesRootDirectory()
        modules = list(Module.PublicUids.values()) if modulesFrom == 0 else list(Module.PrivateUids.values())
        modules = sorted(modules)

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
