"""Module browser popup dialog with category sidebar, module card list, and doc preview."""

from __future__ import annotations

import os
import subprocess
import xml.etree.ElementTree as ET
from typing import Optional, List, Tuple
import markdown
import asyncio

from .docBrowser import DocBrowser
from .qt import *
from ..core.uidManager import UidManager
from ..core.settings import settings, MODULE_EXTS, RIG_BUILDER_PATH, RIG_BUILDER_USER_PATH
from ..core.logger import logger
from .fileTracker import DirectoryWatcher
from ..core.moduleIndexer import ModuleIndexer

_docCache: dict[str, Tuple[float, str]] = {}  # path: (mtime, content)


def getDocFromFile(path: str) -> str:
    """Fetch doc content from file with caching based on mtime."""
    if not os.path.exists(path):
        return ""
    mtime = os.path.getmtime(path)
    if path in _docCache:
        cachedMtime, content = _docCache[path]
        if cachedMtime == mtime:
            return content

    content = ""
    try:
        tree = ET.parse(path)
        root = tree.getroot()
        docEl = root.find("doc")
        if docEl is not None:
            content = docEl.text or ""
    except Exception:
        pass

    _docCache[path] = (mtime, content)
    return content


# ---------------------------------------------------------------------------
# Background Workers for AI
# ---------------------------------------------------------------------------

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
            results = asyncio.run(self.indexer.search(self.query, k=self.k))
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


def getCategoryColor(category: str) -> str:
    """Return a stable color string for a category name."""
    if not category or category in (".", ""):
        return "#6ea7ff"  # accent blue for root
    hashVal = sum(ord(c) for c in category)
    colors = ["#4e54c8", "#11998e", "#fc4a1a", "#ee0979", "#00c6ff",
              "#f7b733", "#38ef7d", "#ff6a00", "#b5179e", "#7209b7"]
    return colors[hashVal % len(colors)]


# ---------------------------------------------------------------------------
# Simple Card Widget for Module List Items
# ---------------------------------------------------------------------------

class ModuleCardWidget(QWidget):
    def __init__(self, name: str, filepath: str, score: float = 0.0, parent=None):
        super().__init__(parent)
        self.name = name
        self.filepath = filepath
        self.setStyleSheet("background: transparent;")

        layout = QHBoxLayout(self)
        layout.setContentsMargins(6, 4, 6, 4)
        layout.setSpacing(8)

        # Color dot indicating category
        self.dot = QFrame()
        self.dot.setFixedSize(8, 8)

        # Determine dot color by hashing category name
        rel = os.path.relpath(filepath, settings.modulesPath)
        cat = os.path.dirname(rel)
        color = getCategoryColor(cat)
        self.dot.setStyleSheet(f"background-color: {color}; border-radius: 4px; border: none;")

        self.nameLabel = QLabel(name)
        self.nameLabel.setStyleSheet("font-family: Consolas, monospace; font-size: 12px; font-weight: bold; color: #e8eaed; background: transparent;")

        layout.addWidget(self.dot)
        layout.addWidget(self.nameLabel)
        layout.addStretch()

        if 0.0 < score < 1.0:
            self.scoreLabel = QLabel(f"{score:.0%}")
            self.scoreLabel.setStyleSheet(
                "font-family: Consolas; font-size: 10px; color: #6ea7ff; background: transparent;")
            layout.addWidget(self.scoreLabel)

    def getCategoryColor(self, category: str) -> str:
        return getCategoryColor(category)


class CategoryItemWidget(QWidget):
    """Category list item with a matching color dot."""

    def __init__(self, label: str, category: str, parent=None):
        super().__init__(parent)
        self.setStyleSheet("background: transparent;")
        layout = QHBoxLayout(self)
        layout.setContentsMargins(4, 3, 4, 3)
        layout.setSpacing(6)

        if category:
            dot = QFrame()
            dot.setFixedSize(8, 8)
            dot.setStyleSheet(
                f"background-color: {getCategoryColor(category)};"
                " border-radius: 4px; border: none;")
            layout.addWidget(dot)

        lbl = QLabel(label)
        lbl.setStyleSheet("font-family: Consolas, monospace; background: transparent;")
        layout.addWidget(lbl)
        layout.addStretch()


# ---------------------------------------------------------------------------
# Module Browser Popup Dialog
# ---------------------------------------------------------------------------

class ModuleBrowserHeader(QWidget):
    def __init__(self, title: str, parentDialog: QDialog, parent=None):
        super().__init__(parent)
        self.parentDialog = parentDialog
        self.dragPosition = QPoint()

        self.setStyleSheet("background-color: #1a1e24; border-top-left-radius: 9px; border-top-right-radius: 9px;")
        self.setFixedHeight(32)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(12, 0, 12, 0)

        self.titleLabel = QLabel(title)
        self.titleLabel.setStyleSheet("font-family: Consolas, monospace; font-size: 11px; font-weight: bold; color: #8a92a3; background: transparent;")
        layout.addWidget(self.titleLabel)
        layout.addStretch()

        self.closeBtn = QPushButton("×")
        self.closeBtn.setFixedSize(16, 16)
        self.closeBtn.setStyleSheet("""
            QPushButton {
                background: transparent;
                color: #8a92a3;
                border: none;
                font-size: 16px;
                font-weight: bold;
                padding: 0;
            }
            QPushButton:hover {
                color: #ff5555;
            }
        """)
        self.closeBtn.clicked.connect(self.parentDialog.close)
        layout.addWidget(self.closeBtn)

    def mousePressEvent(self, event: QMouseEvent):
        if event.button() == Qt.LeftButton:
            self.dragPosition = event.globalPosition().toPoint() - self.parentDialog.frameGeometry().topLeft()
            event.accept()

    def mouseMoveEvent(self, event: QMouseEvent):
        if event.buttons() == Qt.LeftButton:
            self.parentDialog.move(event.globalPosition().toPoint() - self.dragPosition)
            event.accept()


class ModuleBrowser(QDialog):
    """Refactored module browser dialog triggered by pressing Tab."""
    modulesReloaded = Signal()

    def __init__(self, parent=None, **kwargs):
        super().__init__(parent, **kwargs)

        self.setWindowFlags(Qt.Popup | Qt.FramelessWindowHint | Qt.NoDropShadowWindowHint)
        self.setAttribute(Qt.WA_TranslucentBackground)

        self.indexer = ModuleIndexer()
        self.semanticResults: List[Tuple[str, float]] = []
        self._indexWorker: Optional[QThread] = None
        self._currentSearchWorker: Optional[SearchWorker] = None
        self._activeThreads = set()

        # Dialog main layout
        self.dialogLayout = QVBoxLayout(self)
        self.dialogLayout.setContentsMargins(10, 10, 10, 10)

        # Styled Container
        self.container = QWidget()

        self.dialogLayout.addWidget(self.container)

        # Layout inside the container
        containerLayout = QVBoxLayout(self.container)
        containerLayout.setContentsMargins(0, 0, 0, 12)
        containerLayout.setSpacing(10)

        # Header bar
        self.headerBar = ModuleBrowserHeader("Module Browser", self)
        containerLayout.addWidget(self.headerBar)

        # Content layout inside the container (with margins)
        contentLayout = QVBoxLayout()
        contentLayout.setContentsMargins(12, 0, 12, 0)
        contentLayout.setSpacing(10)
        containerLayout.addLayout(contentLayout)

        # Header: search widget
        self.searchWidget = QLineEdit()
        self.searchWidget.setPlaceholderText("Search modules...")
        self.searchWidget.textChanged.connect(self._onMaskTextChanged)
        self.searchWidget.returnPressed.connect(self.addSelectedModule)
        contentLayout.addWidget(self.searchWidget)

        # Body: splitter
        self.splitter = QSplitter(Qt.Horizontal)
        contentLayout.addWidget(self.splitter)

        # Left Panel: Categories Sidebar & Action Buttons
        self.sidebarWidget = QWidget()
        sidebarLayout = QVBoxLayout(self.sidebarWidget)
        sidebarLayout.setContentsMargins(0, 0, 0, 0)
        sidebarLayout.setSpacing(6)

        self.categoryList = QListWidget()
        self.categoryList.itemSelectionChanged.connect(self._onCategoryChanged)
        sidebarLayout.addWidget(self.categoryList)

        self.openFolderBtn = QPushButton("📂 Open Folder")
        self.openFolderBtn.clicked.connect(self.openModulesFolder)
        sidebarLayout.addWidget(self.openFolderBtn)

        self.splitter.addWidget(self.sidebarWidget)

        # Center Panel: Modules List
        self.modulesList = QListWidget()
        self.modulesList.setMinimumWidth(220)
        self.modulesList.itemSelectionChanged.connect(self._onModuleSelectionChanged)
        self.modulesList.itemDoubleClicked.connect(self.addSelectedModule)
        self.splitter.addWidget(self.modulesList)

        # Right Panel: Doc Browser & Add Button
        self.docContainer = QWidget()
        docLayout = QVBoxLayout(self.docContainer)
        docLayout.setContentsMargins(0, 0, 0, 0)
        docLayout.setSpacing(8)

        self.docBrowser = DocBrowser(editable=False)        
        docLayout.addWidget(self.docBrowser)

        self.addButton = QPushButton("➕ Add Module")
        self.addButton.clicked.connect(self.addSelectedModule)
        docLayout.addWidget(self.addButton)

        self.splitter.addWidget(self.docContainer)

        self.splitter.setSizes([140, 240, 360])


        # Setup Timers
        self.searchTimer = QTimer(self)
        self.searchTimer.setSingleShot(True)
        self.searchTimer.timeout.connect(self._runSemanticSearch)

        self.indexTimer = QTimer(self)
        self.indexTimer.setSingleShot(True)
        self.indexTimer.timeout.connect(self._doIndexing)

        # Install event filter on search widget to intercept Up/Down arrows
        self.searchWidget.installEventFilter(self)

        # Resize grip for frameless window resizing
        self.sizeGrip = QSizeGrip(self)
        self.sizeGrip.setStyleSheet("background: transparent;")

        self._setupAutoReloadWatcher()
        self.refreshModules()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        # Position the size grip in the bottom right corner, accounting for dialog margins (10px)
        self.sizeGrip.move(self.width() - self.sizeGrip.width() - 10, self.height() - self.sizeGrip.height() - 10)

    def eventFilter(self, watched, event):
        if watched == self.searchWidget and event.type() == QEvent.KeyPress:
            key = event.key()
            if key in (Qt.Key_Down, Qt.Key_Up):
                rowCount = self.modulesList.count()
                if rowCount > 0:
                    currentRow = self.modulesList.currentRow()
                    if key == Qt.Key_Down:
                        newRow = (currentRow + 1) % rowCount
                    else:
                        newRow = (currentRow - 1 + rowCount) % rowCount
                    self.modulesList.setCurrentRow(newRow)
                return True
            elif key == Qt.Key_Escape:
                self.close()
                return True
        return super().eventFilter(watched, event)

    def _launchThread(self, worker: QThread):
        """Safely start a thread and keep a reference until it finishes."""
        if not worker.objectName():
            worker.setObjectName(worker.__class__.__name__)
        self._activeThreads.add(worker)
        worker.finished.connect(lambda *_: self._activeThreads.discard(worker))
        worker.finished.connect(worker.deleteLater)
        worker.start()

    def _startIndexing(self):
        """Schedule background indexing with a debounce."""
        self.indexTimer.start(100)

    def _doIndexing(self):
        """Actual background indexing trigger."""
        if self._indexWorker:
            try:
                if self._indexWorker.isRunning():
                    return
            except RuntimeError:
                self._indexWorker = None

        self._indexWorker = IndexWorker(self.indexer, settings.modulesPath)
        self._indexWorker.finished.connect(lambda: setattr(self, "_indexWorker", None))
        self._launchThread(self._indexWorker)

    def refreshModules(self):
        """Syncs modules, trigger indexing, and rebuild the UI list."""
        UidManager.sync()

        self.indexer.filePath = os.path.join(settings.workspacePath, "moduleIndex.json")
        self.indexer.refresh()
        self._startIndexing()

        self._rebuildCategoryList()
        self._rebuildModulesList()

    def _rebuildCategoryList(self):
        selected = self.categoryList.currentItem()
        selectedCat = selected.data(Qt.UserRole) if selected else None  # None = All Modules

        self.categoryList.clear()

        categories = set()
        for filepath in UidManager.uids().values():
            rel = os.path.relpath(filepath, settings.modulesPath)
            cat = os.path.dirname(rel)
            if cat and cat != ".":
                categories.add(cat.replace("\\", "/"))

        sortedCats = sorted(list(categories))

        # Add "All Modules" first
        allItem = QListWidgetItem()
        allWidget = CategoryItemWidget("All Modules", "")
        self.categoryList.addItem(allItem)
        self.categoryList.setItemWidget(allItem, allWidget)

        for cat in sortedCats:
            item = QListWidgetItem()
            widget = CategoryItemWidget(cat, cat)
            item.setData(Qt.UserRole, cat)
            self.categoryList.addItem(item)
            self.categoryList.setItemWidget(item, widget)

        # Restore selection
        for i in range(self.categoryList.count()):
            item = self.categoryList.item(i)
            if item.data(Qt.UserRole) == selectedCat:
                self.categoryList.setCurrentItem(item)
                break
        else:
            self.categoryList.setCurrentRow(0)

    def _rebuildModulesList(self):
        selectedCatItem = self.categoryList.currentItem()
        selectedCategory = selectedCatItem.data(Qt.UserRole) if selectedCatItem else None

        searchQuery = self.searchWidget.text().strip().lower()

        # Get all modules with an initial score of 0.0
        allModules = []
        for filepath in UidManager.uids().values():
            name = os.path.splitext(os.path.basename(filepath))[0]
            rel = os.path.relpath(filepath, settings.modulesPath)
            cat = os.path.dirname(rel).replace("\\", "/")
            if not cat or cat == ".":
                cat = ""
            allModules.append((name, filepath, cat, 0.0))

        # Filter by category
        if selectedCategory:  # None = "All Modules"
            allModules = [m for m in allModules if m[2] == selectedCategory or m[2].startswith(selectedCategory + "/")]

        # Filter and rank by search query
        if searchQuery:
            scores = {os.path.normpath(p).lower(): s for p, s in self.semanticResults if p}
            scoredModules = []
            for name, filepath, cat, _ in allModules:
                if searchQuery in name.lower():
                    score = 1.0
                else:
                    score = scores.get(os.path.normpath(filepath).lower(), 0.0)

                if score >= 0.5:
                    scoredModules.append((name, filepath, cat, score))
            scoredModules.sort(key=lambda x: (-x[3], x[0].lower()))
            allModules = scoredModules
        else:
            allModules.sort(key=lambda x: x[0].lower())

        self.modulesList.clear()

        for name, filepath, cat, score in allModules:
            item = QListWidgetItem()
            card = ModuleCardWidget(name, filepath, score=score)
            item.setSizeHint(card.sizeHint())
            self.modulesList.addItem(item)
            self.modulesList.setItemWidget(item, card)

        if self.modulesList.count() > 0:
            self.modulesList.setCurrentRow(0)
        else:
            self.docBrowser.clear()
            self.addButton.setEnabled(False)

    def _onCategoryChanged(self):
        self._rebuildModulesList()

    def _onModuleSelectionChanged(self):
        selectedItem = self.modulesList.currentItem()
        if not selectedItem:
            self.docBrowser.clear()
            self.addButton.setEnabled(False)
            return

        card = self.modulesList.itemWidget(selectedItem)
        if not card:
            self.docBrowser.clear()
            self.addButton.setEnabled(False)
            return

        self.addButton.setEnabled(True)
        doc = getDocFromFile(card.filepath)
        self.docBrowser.setDoc(doc)

    def addSelectedModule(self):
        selectedItem = self.modulesList.currentItem()
        if not selectedItem:
            return

        card = self.modulesList.itemWidget(selectedItem)
        if not card or not card.filepath:
            return

        filepath = card.filepath
        self.close()

        mainWindow = self.parent()
        mainWindow.addModuleBySpec(filepath)

    def _runSemanticSearch(self):
        """Perform background semantic search using the current filter text."""
        self.searchTimer.stop()
        query = self.searchWidget.text().strip()
        if not query or query.startswith("/"):
            self.semanticResults = []
            self._rebuildModulesList()
            return

        if self._currentSearchWorker:
            try:
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

        self.semanticResults = []
        self._rebuildModulesList()

    def _onSemanticSearchFinished(self, query: str, results: List[Tuple[str, float]]):
        """Handle results from the semantic search thread."""
        if query != self.searchWidget.text().strip():
            return
        self.semanticResults = results
        self._rebuildModulesList()

    def _onMaskTextChanged(self, text: str):
        if not text.strip():
            self.searchTimer.stop()
            self.semanticResults = []
            self._rebuildModulesList()
        else:
            self.searchTimer.start(300)
            self._rebuildModulesList()

    def _setupAutoReloadWatcher(self):
        self.modulesAutoReloadWatcher = DirectoryWatcher(
            [settings.modulesPath],
            filePatterns=["*" + ext for ext in MODULE_EXTS],
            debounceMs=700,
            recursive=True,
            parent=self)
        self.modulesAutoReloadWatcher.fileChanged.connect(lambda _: self.refreshModules())

    def openModulesFolder(self):
        """Open the modules directory in default file browser."""
        if os.path.exists(settings.modulesPath):
            subprocess.call(f'explorer "{os.path.normpath(settings.modulesPath)}"')
