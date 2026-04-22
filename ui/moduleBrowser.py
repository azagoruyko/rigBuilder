"""Module browser widget with filter, source options, and module tree."""

from __future__ import annotations

import os
import re
import time
import subprocess
import xml.etree.ElementTree as ET
from typing import Optional, List, Tuple
import markdown
import asyncio
import threading
from functools import partial

from ..qt import *
from ..core import Module, MODULE_EXTS, UidManager
from .. import workspace
from .. import settings as settings_module
from ..settings import settings
from ..logger import logger
from .fileTracker import DirectoryWatcher
from .utils import fontSize, setFontSize
from ..utils import clamp, getRelativeTimeString
from ..moduleIndexer import ModuleIndexer
from ..ai import engine

OLD_MODULE_THRESHOLD_DAYS = 7
_docCache: dict[str, Tuple[float, str]] = {} # path: (mtime, content)

def getDocFromFile(path: str) -> str:
    """Fetch doc content from file with caching based on mtime."""
    mtime = os.path.getmtime(path)
    if path in _docCache:
        cached_mtime, content = _docCache[path]
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
        
    _docCache[path] = (mtime, content)
    return content

class ModuleBrowserTree(QTreeWidget):
    """Tree widget for browsing module files on disk."""
    
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.middlePressPos = QPoint()

        self.setHeaderLabels(["Module", "Modification time", "Score"])
        self.header().setSectionResizeMode(QHeaderView.ResizeToContents)
        self.setColumnHidden(2, True) # Hide the Score column
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
        menu.addSeparator()
        menu.addAction("Refresh", self.parent().refreshModules)
        menu.popup(event.globalPos())

    def browseModuleDirectory(self):
        for item in self.selectedItems():
            if hasattr(item, "filePath"):
                subprocess.call("explorer /select,\"{}\"".format(os.path.normpath(item.filePath)))

    def openModulesFolder(self):
        folderPath = settings.modulesPath
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


# Background Workers for AI
class SearchWorker(QThread):
    finished = Signal(str, list)
    def __init__(self, indexer: ModuleIndexer, query: str, k: int = 5):
        super().__init__()
        self.setObjectName(f"SearchWorker_{query[:10]}")
        self.indexer = indexer
        self.query = query
        self.k = k

    def run(self):
        try:
            # We use a new event loop in the thread for asyncio
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            results = loop.run_until_complete(self.indexer.search(self.query, k=self.k))
            self.finished.emit(self.query, results)
        except Exception as e:
            logger.error(f"Semantic Search Error: {e}")
            self.finished.emit(self.query, [])

class IndexWorker(QThread):
    def __init__(self, indexer: ModuleIndexer, folder: str):
        super().__init__()
        self.setObjectName("IndexWorker")
        self.indexer = indexer
        self.folder = folder

    def run(self):
        try:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            loop.run_until_complete(self.indexer.indexModules(self.folder))
        except Exception as e:
            logger.error(f"Background Indexing Error: {e}")

class ModuleBrowser(QWidget):
    """Embeddable module selector with filter, source options, and module tree."""
    
    modulesReloaded = Signal()

    def __init__(self, **kwargs):
        super().__init__(**kwargs)

        # AI Semantic Search setup
        self.indexer = ModuleIndexer()
        self.semanticResults: List[Tuple[str, float]] = []
        self._indexWorker: Optional[QThread] = None

        self._fileItems: List[QTreeWidgetItem] = []
        self._currentSearchWorker: Optional[SearchWorker] = None
        self._activeThreads = set() # Instance-level thread registry

        layout = QVBoxLayout()
        layout.setContentsMargins(0, 0, 0, 0)
        self.setLayout(layout)

        self.pathLabel = QLabel()
        self.pathLabel.setWordWrap(True)
        self.pathLabel.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.pathLabel.setStyleSheet("color: #AAAAAA; font-style: italic; background-color: rgba(255, 255, 255, 0.05); padding: 5px; border-radius: 4px; margin-top: 5px;")

        self.searchWidget = QLineEdit()
        self.searchWidget.setPlaceholderText("Module name or description...")
        self.searchWidget.textChanged.connect(self.applyMask)
        self.searchWidget.returnPressed.connect(self._runSemanticSearch)

        self.clearFilterButton = QPushButton("🧹 Clear")
        self.clearFilterButton.clicked.connect(self.searchWidget.clear)
        self.clearFilterButton.hide()
        self.searchWidget.textChanged.connect(self._onMaskTextChanged)

        filterLayout = QHBoxLayout()
        filterLayout.addWidget(QLabel("Search"))
        filterLayout.addWidget(self.searchWidget)
        filterLayout.addWidget(self.clearFilterButton)
        layout.addLayout(filterLayout)

        self.treeWidget = ModuleBrowserTree()

        layout.addWidget(self.treeWidget)
        layout.addWidget(self.pathLabel)
        
        self.searchTimer = QTimer(self)
        self.searchTimer.setSingleShot(True)
        self.searchTimer.timeout.connect(self._runSemanticSearch)

        self.indexTimer = QTimer(self)
        self.indexTimer.setSingleShot(True)
        self.indexTimer.timeout.connect(self._doIndexing)

        # Mask debounce timer
        self.maskTimer = QTimer(self)
        self.maskTimer.setSingleShot(True)
        self.maskTimer.timeout.connect(self._applyMaskInternal)

        self._setupAutoReloadWatcher()
        self.refreshModules()

    def _launchThread(self, worker: QThread):
        """Safely start a thread and keep a reference in the registry until it finishes."""
        if not worker.objectName():
            worker.setObjectName(worker.__class__.__name__)
            
        self._activeThreads.add(worker)
        worker.finished.connect(lambda *_: self._activeThreads.discard(worker))
        worker.finished.connect(worker.deleteLater)
        worker.start()

    def _startIndexing(self):
        """Schedule background indexing with a debounce to prevent multiple triggers."""
        self.indexTimer.start(100)

    def _doIndexing(self):
        """Actual background indexing trigger."""
        if self._indexWorker:
            try:
                if self._indexWorker.isRunning():
                    return
            except RuntimeError:
                # Handle case where C++ object was already deleted
                self._indexWorker = None

        self._indexWorker = IndexWorker(self.indexer, settings.modulesPath)
        self._indexWorker.finished.connect(lambda: setattr(self, "_indexWorker", None))
        self._launchThread(self._indexWorker)

    def _runSemanticSearch(self):
        """Perform background semantic search using the current filter text."""
        self.searchTimer.stop() # Ensure timer is stopped if triggered manually
        query = self.searchWidget.text().strip()
        if not query or query.startswith("/"):
            self.semanticResults = []
            self.applyMask()
            return

        # Single Search Policy: Abort previous worker to prevent thread spam
        if self._currentSearchWorker:
             try:
                 # Cleanly disconnect and terminate to avoid double-processing
                 self._currentSearchWorker.finished.disconnect()
                 if self._currentSearchWorker.isRunning():
                     self._currentSearchWorker.terminate()
                     self._currentSearchWorker.wait()
             except (RuntimeError, TypeError):
                 pass
             self._currentSearchWorker = None

        self._currentSearchWorker = SearchWorker(self.indexer, query, k=15)
        self._currentSearchWorker.finished.connect(self._onSemanticSearchFinished)
        self._launchThread(self._currentSearchWorker)
        
        # Trigger immediate feedback that we are searching
        self.semanticResults = [] 
        self.applyMask()

    def _onSemanticSearchFinished(self, query: str, results: List[Tuple[str, float]]):
        """Handle results from the semantic search thread."""
        # Only apply results if they match the current search text (prevents out-of-order results)
        if query != self.searchWidget.text().strip():
            return

        self.semanticResults = results
        self.applyMask()

    def _updatePathLabel(self):
        """Update the path label with the current modules directory."""
        path = os.path.normpath(settings.modulesPath)
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
        watchRoots = [settings.modulesPath]
        self.modulesAutoReloadWatcher = DirectoryWatcher(
            watchRoots,
            filePatterns=["*" + ext for ext in MODULE_EXTS],
            debounceMs=700,
            recursive=True,
            parent=self)

        self.modulesAutoReloadWatcher.fileChanged.connect(lambda _: self.refreshModules())

    def refreshModules(self):
        """Internal refresh used by startup and auto-reload flows. Builds the persistent tree."""
        self._updatePathLabel()
        UidManager.sync()

        # Update indexer for current workspace and trigger background scan
        self.indexer.filePath = os.path.join(workspace.currentWorkspace.folderPath(), "moduleIndex.json")
        self.indexer.refresh()
        self._startIndexing()

        # Build persistent tree
        self._buildTree()
        self.applyMask()

    def _buildTree(self):
        """Build the full module tree once. Items are stored in self._fileItems for visibility filtering."""
        def findChildByText(text: str, parent: QTreeWidgetItem, column: int = 0):
            for i in range(parent.childCount()):
                ch = parent.child(i)
                if text == ch.text(column):
                    return ch

        modulesDirectory = settings.modulesPath
        modules = sorted(UidManager.uids().values())

        self.treeWidget.clear()
        self._fileItems = []

        for f in modules:
            absF = os.path.normpath(f)
            relativePath = os.path.relpath(f, modulesDirectory)
            relativeDir = os.path.dirname(relativePath)
            name, _ = os.path.splitext(os.path.basename(f))

            dirItem = self.treeWidget.invisibleRootItem()
            if relativeDir:
                for p in relativeDir.split("\\"):
                    ch = findChildByText(p, dirItem)
                    if not ch:
                        ch = QTreeWidgetItem([p, "", "0"]) # 3rd column is for score
                        ch.setFlags((ch.flags() | Qt.ItemIsEnabled | Qt.ItemIsSelectable) & ~Qt.ItemIsDragEnabled)
                        font = ch.font(0)
                        font.setBold(True)
                        ch.setForeground(0, QColor(130, 130, 230))
                        ch.setFont(0, font)
                        dirItem.addChild(ch)
                    dirItem = ch

            mtime = os.path.getmtime(f)
            timeLabel = getRelativeTimeString(mtime)
            item = QTreeWidgetItem([name, timeLabel, "0"])
            item.setFlags(item.flags() | Qt.ItemIsDragEnabled)
            item.filePath = os.path.abspath(f).lower()
            
            # Highlight old modification dates
            if time.time() - mtime > OLD_MODULE_THRESHOLD_DAYS * 24 * 60 * 60:
                item.setForeground(1, QColor("#888888"))

            dirItem.addChild(item)
            self._fileItems.append(item)

    def _onMaskTextChanged(self, text: str):
        self.clearFilterButton.setVisible(bool(text))
        
        # Reset semantic results and trigger search timer only on REAL text changes
        # This prevents infinite loops when _onSemanticSearchFinished calls applyMask
        if not text.strip():
            self.searchTimer.stop()
            self.semanticResults = []
            self.applyMask()
        else:
            self.searchTimer.start(500)
            self.applyMask()

    def applyMask(self, *_):
        """Schedule a debounced tree visibility update."""
        self.maskTimer.start(50)

    def _applyMaskInternal(self):
        """Update visibility of tree items. Implements exclusive semantic filtering."""
        maskText = self.searchWidget.text().strip()
        
        # Determine filtering matches
        # Threshold 0.5 ensures only relevant results are shown
        semanticMatches = {p.lower() for p, s in self.semanticResults if s >= 0.5} if self.semanticResults else None
        isSearching = bool(maskText)

        # 1. Update file scores and visibility
        scores = {p.lower(): s for p, s in self.semanticResults} if self.semanticResults else {}
        
        for item in self._fileItems:
            absF = item.filePath
            
            # Score assignment for ranking
            score = 0.0
            if isSearching:
                moduleName = os.path.splitext(os.path.basename(absF))[0]
                # Direct match gets a high baseline score to stay relevant
                if all(m in moduleName.lower() for m in maskText.lower().split()):
                    score = 1.0
                else:
                    # Semantic score is used only if there's no direct name match
                    score = scores.get(absF, 0.0)

            item.setText(2, f"{score:.4f}")
            
            if not isSearching:
                showItem = True
            else:
                # Show if score is above 0.5 (includes direct name matches @ 0.8)
                showItem = score >= 0.5 or (semanticMatches is not None and absF in semanticMatches)
            
            item.setHidden(not showItem)

        def updateFolderVisibilityAndScore(item: QTreeWidgetItem) -> float:
            """Recursively update folder visibility and return its highest child score."""
            visibleChildren = 0
            maxChildScore = 0.0
            
            for i in range(item.childCount()):
                child = item.child(i)
                if child.childCount() > 0: # It's a folder
                    childScore = updateFolderVisibilityAndScore(child)
                    maxChildScore = max(maxChildScore, childScore)
                else:
                    # It's a file, get its score from column 2
                    maxChildScore = max(maxChildScore, float(child.text(2)))
                
                if not child.isHidden():
                    visibleChildren += 1
            
            if item != self.treeWidget.invisibleRootItem():
                item.setHidden(visibleChildren == 0)
                item.setText(2, f"{maxChildScore:.4f}")
                if maskText and visibleChildren > 0:
                    item.setExpanded(True)
            
            return maxChildScore

        updateFolderVisibilityAndScore(self.treeWidget.invisibleRootItem())

        # 3. Dynamic Sorting
        if isSearching and (self.semanticResults or self.searchWidget.text().strip()):
            self.treeWidget.sortItems(2, Qt.DescendingOrder) # Sort by score
        else:
            self.treeWidget.sortItems(1, Qt.DescendingOrder) # Sort by modification time
