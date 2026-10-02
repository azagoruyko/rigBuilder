"""Module browser popup dialog with category sidebar, module card list, and doc preview."""

from __future__ import annotations

import os
import subprocess
import xml.etree.ElementTree as ET
from typing import Optional
import markdown
import asyncio

from .docBrowser import DocBrowser
from .qt import *
from ..core.uidManager import UidManager
from ..core.settings import settings, MODULE_EXTS, RIG_BUILDER_PATH, RIG_BUILDER_USER_PATH
from ..core.utils import relativePath
from ..core.logger import logger
from .fileTracker import DirectoryWatcher
from ..core.moduleIndexer import ModuleIndexer

_docCache = {}  # path: (mtime, content)
RECENT_MODULES_KEY = "moduleBrowser/recentModules"
RECENT_MODULES_LIMIT = 10
FOLDER_COLORS_KEY = "moduleBrowser/folderColors"


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
    def __init__(self, indexer: ModuleIndexer):
        super().__init__()
        self.setObjectName("IndexWorker")
        self.indexer = indexer

    def run(self):
        try:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            loop.run_until_complete(self.indexer.indexModules())
        except Exception as e:
            logger.error(f"Background Indexing Error: {e}")


def getCategoryColor(category: str) -> Optional[str]:
    """Return a folder's assigned color, if any."""
    return getFolderColor(os.path.join(settings.modulesPath, category))


def getFolderColor(folderPath: str) -> Optional[str]:
    """Return the saved color for a folder path."""
    folder = os.path.normcase(os.path.abspath(folderPath))
    savedColors = QSettings("RigBuilder").value(FOLDER_COLORS_KEY, {}) or {}
    return savedColors.get(folder)


def _getModuleLocation(filepath: str) -> Optional[tuple[bool, str, str]]:
    """Return whether a module is a dependency, its root, and its relative path."""
    filepath = os.path.normpath(filepath)
    for index, rootPath in enumerate([settings.modulesPath, *settings.moduleDependenciesPaths]):
        path = relativePath(filepath, rootPath)
        if path != filepath:
            return index > 0, rootPath, path
    return None


def getModuleDisplayPath(filepath: str) -> str:
    """Return a dependency's root-folder name and relative module path."""
    location = _getModuleLocation(filepath)
    isDependency, rootPath, path = location if location else (False, "", os.path.basename(filepath))
    path = os.path.splitext(path)[0].replace("\\", "/")
    if not isDependency:
        return path

    rootName = os.path.basename(os.path.normpath(rootPath)).replace("\\", "/")
    return f"{rootName}/{path}"


def isDependencyModuleFile(filepath: str) -> bool:
    """Return whether a module file belongs to a configured dependency root."""
    location = _getModuleLocation(filepath)
    return bool(location and location[0])


def getModuleFolderColor(filepath: str) -> Optional[str]:
    """Return the saved color for a module's folder or its dependency parent."""
    location = _getModuleLocation(filepath)
    if not location:
        return None

    isDependency, rootPath, relativeModulePath = location
    folderPath = os.path.dirname(relativeModulePath)
    if not isDependency:
        return getCategoryColor(folderPath.replace("\\", "/"))

    while folderPath not in ("", "."):
        color = getFolderColor(os.path.join(rootPath, folderPath))
        if color:
            return color
        folderPath = os.path.dirname(folderPath)

    return getFolderColor(rootPath)


# ---------------------------------------------------------------------------
# Simple Card Widget for Module List Items
# ---------------------------------------------------------------------------

class ModuleCardWidget(QWidget):
    def __init__(self, name: str, filepath: str, score: float = 0.0, parent=None, dependencyPath: str = ""):
        super().__init__(parent)
        self.name = name
        self.filepath = filepath
        self.setStyleSheet("background: transparent;")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(6, 4, 6, 4)
        layout.setSpacing(8)

        headerLayout = QHBoxLayout()
        if not dependencyPath:
            rel = os.path.relpath(filepath, settings.modulesPath)
            cat = os.path.dirname(rel)
            color = getCategoryColor(cat)
            if color:
                dot = QFrame()
                dot.setFixedSize(8, 8)
                dot.setStyleSheet(f"background-color: {color}; border-radius: 4px; border: none;")
                headerLayout.addWidget(dot)

        self.nameLabel = QLabel(name)

        headerLayout.addWidget(self.nameLabel)
        headerLayout.addStretch()

        if 0.0 < score < 1.0:
            self.scoreLabel = QLabel(f"{score:.0%}")
            headerLayout.addWidget(self.scoreLabel)

        layout.addLayout(headerLayout)

        if dependencyPath:
            self.pathLabel = QLabel(dependencyPath)
            self.pathLabel.setStyleSheet("color: #888888; font-size: 10px;")
            layout.addWidget(self.pathLabel)


class CategoryItemWidget(QWidget):
    """Category list item with a matching color dot."""
    contextMenuRequested = Signal(str, QPoint)

    def __init__(self, label: str, category: str, parent=None, folderPath: str = ""):
        super().__init__(parent)
        self.category = category
        self.setStyleSheet("background: transparent;")
        layout = QHBoxLayout(self)
        layout.setContentsMargins(4, 3, 4, 3)
        layout.setSpacing(6)

        if folderPath:
            color = getFolderColor(folderPath)
        elif category not in ("__recent__", "__workspace__", "__dependencies__") and not category.startswith("__dependency_root__:"):
            color = getCategoryColor(category)
        else:
            color = None
        if color:
            dot = QFrame()
            dot.setFixedSize(8, 8)
            dot.setStyleSheet(
                f"background-color: {color};"
                " border-radius: 4px; border: none;")
            layout.addWidget(dot)

        lbl = QLabel(label)
        lbl.setStyleSheet("background: transparent;")
        font = lbl.font()
        font.setBold(category in ("__recent__", "__workspace__", "__dependencies__"))
        lbl.setFont(font)
        layout.addWidget(lbl)
        layout.addStretch()

    def contextMenuEvent(self, event):
        """Forward a right-click on the visible folder row to the browser."""
        self.contextMenuRequested.emit(self.category, event.globalPos())
        event.accept()


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
        self.titleLabel.setStyleSheet("font-size: 11px; font-weight: bold; color: #8a92a3; background: transparent;")
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
    moduleRequested = Signal(str)
    folderColorsChanged = Signal()

    def __init__(self, parent=None, **kwargs):
        super().__init__(parent, **kwargs)

        self.setWindowFlags(Qt.Popup | Qt.FramelessWindowHint | Qt.NoDropShadowWindowHint)
        self.setAttribute(Qt.WA_TranslucentBackground)

        self.indexer = ModuleIndexer()
        self.semanticResults = []
        self._dependencyCategoryPaths = {}
        self._indexWorker = None
        self._indexRefreshPending = False
        self._currentSearchWorker = None
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
        self.sidebarWidget.setMinimumWidth(210)
        sidebarLayout = QVBoxLayout(self.sidebarWidget)
        sidebarLayout.setContentsMargins(0, 0, 0, 0)
        sidebarLayout.setSpacing(6)

        self.categoryList = QTreeWidget()
        self.categoryList.setHeaderHidden(True)
        self.categoryList.setIndentation(14)
        self.categoryList.itemSelectionChanged.connect(self._rebuildModulesList)
        sidebarLayout.addWidget(self.categoryList)

        self.refreshModulesBtn = QPushButton("↻ Refresh")
        self.refreshModulesBtn.setToolTip("Rescan owned and dependency module folders")
        self.refreshModulesBtn.clicked.connect(self.refreshModules)
        sidebarLayout.addWidget(self.refreshModulesBtn)

        self.openFolderBtn = QPushButton("📂 Open Folder")
        self.openFolderBtn.clicked.connect(self.openModulesFolder)
        sidebarLayout.addWidget(self.openFolderBtn)

        self.splitter.addWidget(self.sidebarWidget)

        # Center Panel: Modules List
        self.modulesList = QListWidget()
        self.modulesList.setMinimumWidth(220)
        self.modulesList.setContextMenuPolicy(Qt.CustomContextMenu)
        self.modulesList.customContextMenuRequested.connect(self._onModuleContextMenu)
        self.modulesList.itemSelectionChanged.connect(self._onModuleSelectionChanged)
        self.modulesList.itemDoubleClicked.connect(self.addSelectedModule)
        self.splitter.addWidget(self.modulesList)

        # Right Panel: Doc Browser
        self.docContainer = QWidget()
        docLayout = QVBoxLayout(self.docContainer)
        docLayout.setContentsMargins(0, 0, 0, 0)
        docLayout.setSpacing(8)

        self.docBrowser = DocBrowser(editable=False)        
        docLayout.addWidget(self.docBrowser)

        self.splitter.addWidget(self.docContainer)

        self.splitter.setSizes([220, 260, 360])


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
                    self._indexRefreshPending = True
                    return
            except RuntimeError:
                self._indexWorker = None

        self._indexWorker = IndexWorker(self.indexer)
        self._indexWorker.finished.connect(self._onIndexingFinished)
        self._launchThread(self._indexWorker)

    def _onIndexingFinished(self):
        """Run a refresh requested while indexing was already in progress."""
        self._indexWorker = None
        if self._indexRefreshPending:
            self._indexRefreshPending = False
            self._startIndexing()

    def refreshModules(self):
        """Syncs modules, trigger indexing, and rebuild the UI list."""
        self.modulesList.setCurrentRow(-1)
        self.docBrowser.setDoc("")

        UidManager.sync()

        self.indexer.filePath = os.path.join(settings.workspacePath, "moduleIndex.json")
        self.indexer.refresh()
        self._startIndexing()

        self._rebuildCategoryList()
        self._rebuildModulesList()
        self.modulesReloaded.emit()

    def _rebuildCategoryList(self):
        selected = self.categoryList.currentItem()
        selectedCat = selected.data(0, Qt.UserRole) if selected else "__workspace__"

        self.categoryList.clear()
        self._dependencyCategoryPaths = {}

        modules = self._getAvailableModules()
        def addCategory(label, category, parent=None, folderPath=""):
            item = QTreeWidgetItem()
            item.setData(0, Qt.UserRole, category)
            if parent:
                parent.addChild(item)
            else:
                self.categoryList.addTopLevelItem(item)

            widget = CategoryItemWidget(label, category, folderPath=folderPath)
            self.categoryList.setItemWidget(item, 0, widget)
            widget.contextMenuRequested.connect(self._onCategoryContextMenu)
            return item

        def addFolderBranches(parentItem, folders, rootPath, dependencyIndex=None):
            folderItems = {"": parentItem}
            for folder in sorted(folders):
                parent = parentItem
                currentFolder = ""
                for part in folder.split("/"):
                    currentFolder = f"{currentFolder}/{part}".strip("/")
                    if currentFolder not in folderItems:
                        category = (
                            currentFolder if dependencyIndex is None
                            else f"__dependency_root__:{dependencyIndex}:{currentFolder}"
                        )
                        folderItem = addCategory(
                            part, category, parent, os.path.join(rootPath, currentFolder)
                        )
                        folderItems[currentFolder] = folderItem
                        if dependencyIndex is not None:
                            self._dependencyCategoryPaths[category] = (rootPath, currentFolder)
                    parent = folderItems[currentFolder]
                parent.setExpanded(True)

        addCategory("Recent", "__recent__")
        ownedFolders = {
            module["category"]
            for module in modules.values()
            if not module["dependency"] and module["category"]
        }
        workspaceModulesItem = addCategory("Workspace Modules", "__workspace__")
        addFolderBranches(workspaceModulesItem, ownedFolders, settings.modulesPath)
        workspaceModulesItem.setExpanded(True)

        dependencyModules = [module for module in modules.values() if module["dependency"]]
        if dependencyModules:
            dependencyRoot = addCategory("Dependency Modules", "__dependencies__")
            dependencyRoot.setExpanded(True)

            for rootIndex, rootPath in enumerate(settings.moduleDependenciesPaths):
                rootModules = [
                    module for module in dependencyModules
                    if os.path.normcase(os.path.abspath(module["dependencyRoot"]))
                    == os.path.normcase(os.path.abspath(rootPath))
                ]
                if not rootModules:
                    continue

                rootName = os.path.basename(os.path.normpath(rootPath)) or rootPath
                rootCategory = f"__dependency_root__:{rootIndex}:"
                rootItem = addCategory(rootName, rootCategory, dependencyRoot, rootPath)
                rootItem.setToolTip(0, rootPath)
                rootItem.setExpanded(True)
                self._dependencyCategoryPaths[rootCategory] = (rootPath, "")

                folders = {module["category"] for module in rootModules if module["category"]}
                addFolderBranches(rootItem, folders, rootPath, rootIndex)

        # Restore selection
        items = [self.categoryList.topLevelItem(i) for i in range(self.categoryList.topLevelItemCount())]
        while items:
            item = items.pop(0)
            if item.data(0, Qt.UserRole) == selectedCat:
                self.categoryList.setCurrentItem(item)
                break
            items[0:0] = [item.child(i) for i in range(item.childCount())]
        else:
            self.categoryList.setCurrentItem(self.categoryList.topLevelItem(0))

    def _onCategoryContextMenu(self, category, globalPos):
        """Choose or disable the color of a folder in the category list."""
        if category in ("__recent__", "__workspace__", "__dependencies__"):
            return

        dependencyPath = self._dependencyCategoryPaths.get(category)
        folderPath = (
            os.path.join(dependencyPath[0], dependencyPath[1])
            if dependencyPath else os.path.join(settings.modulesPath, category)
        )
        folder = os.path.normcase(os.path.abspath(folderPath))
        menu = QMenu(self)
        chooseAction = menu.addAction("Choose color...")
        disableAction = menu.addAction("Disable color")
        disableAction.setEnabled(bool(getFolderColor(folderPath)))
        action = menu.exec(globalPos)
        if action not in (chooseAction, disableAction):
            return

        savedColors = QSettings("RigBuilder").value(FOLDER_COLORS_KEY, {}) or {}
        if action == chooseAction:
            color = QColorDialog.getColor(QColor(getFolderColor(folderPath) or "#c8c8c8"), self, "Choose color")
            if not color.isValid():
                return
            savedColors[folder] = color.name()
        else:
            savedColors.pop(folder, None)

        QSettings("RigBuilder").setValue(FOLDER_COLORS_KEY, savedColors)
        self._rebuildCategoryList()
        self._rebuildModulesList()
        self.folderColorsChanged.emit()

    def _getAvailableModules(self) -> dict[str, dict]:
        """Return dict mapping normpath -> module info dict."""
        modules = {}
        for filepath in UidManager.uids().values():
            location = _getModuleLocation(filepath)
            if not location:
                continue

            isDependency, rootPath, rel = location
            name = os.path.splitext(os.path.basename(filepath))[0]
            cat = os.path.dirname(rel).replace("\\", "/")
            norm = os.path.normpath(filepath)
            modules[norm] = {
                "name": name,
                "filepath": filepath,
                "path": filepath,
                "category": cat,
                "score": 0.0,
                "dependency": isDependency,
                "dependencyRoot": rootPath if isDependency else "",
                "dependencyPath": getModuleDisplayPath(filepath) if isDependency else "",
            }
        return modules

    def getRecentModules(self) -> list[str]:
        """Return recently added module paths in most-recent-first order."""
        recentModules = QSettings("RigBuilder").value(RECENT_MODULES_KEY, [])
        if isinstance(recentModules, str):
            recentModules = [recentModules]

        return [os.path.normpath(path) for path in recentModules]

    def recordRecentModule(self, filepath: str):
        """Move a module path to the front of the persistent recent list."""
        filepath = os.path.normpath(filepath)
        recentModules = [path for path in self.getRecentModules() if path != filepath]
        recentModules.insert(0, filepath)
        QSettings("RigBuilder").setValue(
            RECENT_MODULES_KEY,
            recentModules[:RECENT_MODULES_LIMIT],
        )

    def _rebuildModulesList(self):
        catItem = self.categoryList.currentItem()
        selectedCategory = catItem.data(0, Qt.UserRole) if catItem else None
        searchQuery = self.searchWidget.text().strip().lower()

        # Save current module selection
        curItem = self.modulesList.currentItem()
        selectedPath = curItem.data(Qt.UserRole) if curItem else None

        modulesMap = self._getAvailableModules()

        # 1. Category Filter
        if selectedCategory == "__recent__":
            modules = [modulesMap[p] for p in self.getRecentModules() if p in modulesMap]
        elif selectedCategory == "__dependencies__":
            modules = [m for m in modulesMap.values() if m["dependency"]]
        elif selectedCategory in self._dependencyCategoryPaths:
            rootPath, folder = self._dependencyCategoryPaths[selectedCategory]
            modules = [
                module for module in modulesMap.values()
                if module["dependency"]
                and module["dependencyRoot"] == rootPath
                and (
                    not folder
                    or module["category"] == folder
                    or module["category"].startswith(folder + "/")
                )
            ]
        elif selectedCategory and selectedCategory != "__workspace__":
            modules = [
                m for m in modulesMap.values()
                if not m["dependency"] and (
                    m["category"] == selectedCategory
                    or m["category"].startswith(selectedCategory + "/")
                )
            ]
        else:
            modules = [m for m in modulesMap.values() if not m["dependency"]]

        # 2. Search Filter & Sort
        if searchQuery:
            scores = {os.path.normpath(p).lower(): s for p, s in self.semanticResults if p}
            scored = []
            for m in modules:
                score = 1.0 if searchQuery in m["name"].lower() else scores.get(os.path.normpath(m["filepath"]).lower(), 0.0)
                if score >= 0.5:
                    m["score"] = score
                    scored.append(m)
            modules = sorted(scored, key=lambda m: (-m["score"], m["name"].lower()))

        elif selectedCategory != "__recent__":
            modules.sort(key=lambda m: m["name"].lower())

        # 3. Populate List Widget
        self.modulesList.clear()
        for m in modules:
            item = QListWidgetItem()
            item.setData(Qt.UserRole, m["filepath"])
            card = ModuleCardWidget(
                m["name"], m["filepath"], score=m["score"], dependencyPath=m["dependencyPath"]
            )
            item.setSizeHint(card.sizeHint())
            self.modulesList.addItem(item)
            self.modulesList.setItemWidget(item, card)

            if selectedPath and item.data(Qt.UserRole) == selectedPath:
                self.modulesList.setCurrentItem(item)

        if self.modulesList.count() == 0:
            self.docBrowser.clear()

    def _onModuleSelectionChanged(self):
        selectedItem = self.modulesList.currentItem()
        if not selectedItem:
            self.docBrowser.clear()
            return

        card = self.modulesList.itemWidget(selectedItem)
        if not card:
            self.docBrowser.clear()
            return

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
        self.recordRecentModule(filepath)
        self._rebuildModulesList()
        self.close()

        self.moduleRequested.emit(filepath)

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

    def _onSemanticSearchFinished(self, query: str, results: list[tuple[str, float]]):
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

    def showInExplorer(self, path: str):
        """Open specified file path in Windows Explorer."""
        if path and os.path.exists(path):
            subprocess.call(f'explorer /select,"{os.path.normpath(path)}"')

    def _onModuleContextMenu(self, pos: QPoint):
        """Show context menu for items in the module list."""
        item = self.modulesList.itemAt(pos)
        if not item or not item.data(Qt.UserRole):
            return

        self.modulesList.setCurrentItem(item)
        menu = QMenu(self)
        menu.addAction("Show in Explorer", lambda: self.showInExplorer(item.data(Qt.UserRole)))
        menu.exec(self.modulesList.mapToGlobal(pos))

#
