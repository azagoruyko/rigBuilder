"""Module browser widget with filter, source options, and module tree."""

from __future__ import annotations

import os
import subprocess
import xml.etree.ElementTree as ET
from typing import Optional, List, Tuple
import markdown
import asyncio

from .qt import *
from ..core.uidManager import UidManager
from ..core.settings import settings, MODULE_EXT, MODULE_EXTS, RIG_BUILDER_PATH, RIG_BUILDER_USER_PATH
from ..core.logger import logger
from .fileTracker import DirectoryWatcher
from .utils import fontSize, setFontSize
from ..core.utils import clamp
from ..core.moduleIndexer import ModuleIndexer

_docCache: dict[str, Tuple[float, str]] = {} # path: (mtime, content)

# Column indices
COL_NAME = 0
COL_SCORE = 1

# Data roles
FILEPATH_ROLE = Qt.UserRole     # absolute file path on COL_NAME
IS_DIR_ROLE = Qt.UserRole + 1   # bool: True for folder rows
_HIDDEN_ROLE = Qt.UserRole + 2  # bool: True = hidden by filter
SCORE_ROLE = Qt.UserRole + 3    # float score, stored on COL_NAME for sorting
UID_ROLE = Qt.UserRole + 4      # module UID string, stored on COL_NAME


def getDocFromFile(path: str) -> str:
    """Fetch doc content from file with caching based on mtime."""
    if not os.path.exists(path):
        return ""
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


# ---------------------------------------------------------------------------
# Model
# ---------------------------------------------------------------------------

class ModuleBrowserModel(QStandardItemModel):
    """Standard item model for the module browser.

    Columns:
        0 – Module name   (FILEPATH_ROLE = abs path, IS_DIR_ROLE = bool,
                           UID_ROLE = uid string, SCORE_ROLE = float)
        1 – Score         (float as str, for semantic ranking; always hidden)
    """

    def __init__(self, parent=None):
        super().__init__(0, 2, parent)

    # ------------------------------------------------------------------
    # Build helpers
    # ------------------------------------------------------------------

    def _makeFolderRow(self, name: str) -> List[QStandardItem]:
        """Return [nameItem, scoreItem] for a folder."""
        nameItem = QStandardItem(name)
        nameItem.setData(True, IS_DIR_ROLE)
        nameItem.setData("", FILEPATH_ROLE)
        nameItem.setFlags(Qt.ItemIsEnabled | Qt.ItemIsSelectable)
        font = nameItem.font()
        font.setBold(True)
        nameItem.setFont(font)
        nameItem.setForeground(QColor(130, 130, 230))

        scoreItem = QStandardItem("0")
        scoreItem.setFlags(Qt.ItemIsEnabled)

        return [nameItem, scoreItem]

    def _makeFileRow(self, name: str, filePath: str) -> List[QStandardItem]:
        """Return [nameItem, scoreItem] for a file."""
        nameItem = QStandardItem(name)
        nameItem.setData(False, IS_DIR_ROLE)
        nameItem.setData(filePath, FILEPATH_ROLE)
        nameItem.setData(UidManager.getUidFromFile(filePath), UID_ROLE)
        nameItem.setFlags(Qt.ItemIsEnabled | Qt.ItemIsSelectable | Qt.ItemIsDragEnabled)

        scoreItem = QStandardItem("0.00")
        scoreItem.setFlags(Qt.ItemIsEnabled)

        return [nameItem, scoreItem]

    def rebuild(self, modulesDirectory: str, modules: List[str]):
        """Clear and repopulate the model from a list of file paths."""
        self.clear()
        self.setHorizontalHeaderLabels(["Module", "Score"])

        # Map folder path -> QStandardItem (name column of the folder row)
        folderItems: dict[str, QStandardItem] = {}

        for f in modules:
            relativePath = os.path.relpath(f, modulesDirectory)
            relativeDir = os.path.dirname(relativePath)
            name = os.path.splitext(os.path.basename(f))[0]
            absF = os.path.abspath(f).lower()

            # Ensure all ancestor folder items exist
            parentItem = self.invisibleRootItem()
            if relativeDir and relativeDir != ".":
                # Normalize and split by the native separator
                relativeDir = os.path.normpath(relativeDir)
                parts = relativeDir.split(os.sep)
                cumPath = ""
                for part in parts:
                    cumPath = os.path.join(cumPath, part) if cumPath else part
                    if cumPath not in folderItems:
                        row = self._makeFolderRow(part)
                        parentItem.appendRow(row)
                        folderItems[cumPath] = row[COL_NAME]
                    parentItem = folderItems[cumPath]

            row = self._makeFileRow(name, absF)
            parentItem.appendRow(row)

    def setScore(self, nameItem: QStandardItem, score: float):
        """Update the score column display and store score on the name item for sorting."""
        row = nameItem.row()
        parent = nameItem.parent() or self.invisibleRootItem()
        scoreItem = parent.child(row, COL_SCORE)
        if scoreItem:
            scoreItem.setData(f"{score:.2f}" if score > 0.1 else "", Qt.DisplayRole)
        # Store on the name item itself so the proxy can sort by it
        # even though the score column is hidden
        nameItem.setData(score, SCORE_ROLE)

    def fileItems(self) -> List[QStandardItem]:
        """Return all leaf (file) name-column items in the model."""
        result = []

        def _collect(parentItem: QStandardItem):
            for r in range(parentItem.rowCount()):
                child = parentItem.child(r, COL_NAME)
                if child is None:
                    continue
                if child.data(IS_DIR_ROLE):
                    _collect(child)
                else:
                    result.append(child)

        _collect(self.invisibleRootItem())
        return result


# ---------------------------------------------------------------------------
# Proxy model — sorting + filtering
# ---------------------------------------------------------------------------

class ModuleBrowserProxy(QSortFilterProxyModel):
    """Proxy that hides the score column and sorts numerically when needed.

    Filtering is done externally (items are hidden via _HIDDEN_ROLE on the
    source model), so filterAcceptsRow delegates to that flag.
    """

    def lessThan(self, left: QModelIndex, right: QModelIndex) -> bool:
        """Sort by score descending when non-zero, otherwise alphabetically by name."""
        if left.column() == COL_NAME:
            ls = left.data(SCORE_ROLE) or 0.0
            rs = right.data(SCORE_ROLE) or 0.0
            if ls != rs:
                # Higher score = comes first  →  lessThan means "ls > rs"
                return float(ls) > float(rs)
        return super().lessThan(left, right)

    def filterAcceptsRow(self, sourceRow: int, sourceParent: QModelIndex) -> bool:
        """Delegate visibility to the IS_HIDDEN flag stored by the browser."""
        model = self.sourceModel()
        idx = model.index(sourceRow, COL_NAME, sourceParent)
        item = model.itemFromIndex(idx)
        if item is None:
            return True
        # _HIDDEN_ROLE is stored as a custom role; default False = visible
        return not item.data(_HIDDEN_ROLE)

    def filterAcceptsColumn(self, sourceColumn, sourceParent):
        # Score column is always hidden from the view
        if sourceColumn == COL_SCORE:
            return False
        return True
# ---------------------------------------------------------------------------
# View
# ---------------------------------------------------------------------------

class ModuleBrowserTree(QTreeView):
    """Tree view for browsing module files on disk."""

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.middlePressPos = QPoint()

        self.browserModel = ModuleBrowserModel()
        self.proxyModel = ModuleBrowserProxy()
        self.proxyModel.setSourceModel(self.browserModel)
        self.setModel(self.proxyModel)

        self.header().setSectionResizeMode(QHeaderView.ResizeToContents)

        self.setSortingEnabled(True)
        self.sortByColumn(COL_NAME, Qt.AscendingOrder)

        self.setDragEnabled(True)
        self.setAcceptDrops(False)
        self.setDropIndicatorShown(False)
        self.setDragDropMode(QAbstractItemView.DragOnly)
        self.setDefaultDropAction(Qt.CopyAction)
        self.setMinimumHeight(100)
        self.setSelectionMode(QAbstractItemView.ExtendedSelection)

    # ------------------------------------------------------------------
    # Drag
    # ------------------------------------------------------------------

    def selectedModulePaths(self) -> List[str]:
        """Return a list of file paths for all selected module leaf items."""
        paths = []
        for proxyIdx in self.selectionModel().selectedRows(COL_NAME):
            srcIdx = self.proxyModel.mapToSource(proxyIdx)
            item = self.browserModel.itemFromIndex(srcIdx)
            if item and not item.data(IS_DIR_ROLE):
                fp = item.data(FILEPATH_ROLE)
                if fp:
                    paths.append(fp)
        return paths

    def _startModuleDrag(self):
        paths = self.selectedModulePaths()
        if not paths:
            return
        mimeData = QMimeData()
        mimeData.setUrls([QUrl.fromLocalFile(p) for p in paths])
        drag = QDrag(self)
        drag.setMimeData(mimeData)
        drag.exec(Qt.CopyAction)

    def startDrag(self, supportedActions: Qt.DropActions):
        del supportedActions
        self._startModuleDrag()

    def mousePressEvent(self, event: QMouseEvent):
        if event.button() == Qt.MiddleButton:
            self.middlePressPos = event.pos()
            proxyIdx = self.indexAt(event.pos())
            if proxyIdx.isValid():
                if not (event.modifiers() & (Qt.ControlModifier | Qt.ShiftModifier)):
                    self.clearSelection()
                self.selectionModel().select(
                    proxyIdx, QItemSelectionModel.Select | QItemSelectionModel.Rows)
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

    # ------------------------------------------------------------------
    # Context menu
    # ------------------------------------------------------------------

    def contextMenuEvent(self, event: QContextMenuEvent):
        menu = QMenu(self)
        
        selectedPaths = self.selectedModulePaths()

        renameAction = menu.addAction("Rename")
        renameAction.triggered.connect(self.renameModule)
        renameAction.setEnabled(len(selectedPaths) == 1)
        
        deleteAction = menu.addAction("Delete")
        deleteAction.triggered.connect(self.deleteModule)
        deleteAction.setEnabled(len(selectedPaths) > 0)
        
        menu.addSeparator()

        browseAction = menu.addAction("Show in Explorer")
        browseAction.triggered.connect(self.browseModuleDirectory)
        browseAction.setEnabled(len(selectedPaths) > 0)

        menu.addAction("Open modules folder", self.openModulesFolder)
        menu.addSeparator()
        menu.addAction("Refresh", self.parent().refreshModules)
        menu.popup(event.globalPos())

    def renameModule(self):
        paths = self.selectedModulePaths()
        if not paths:
            return
            
        fp = paths[0]
        oldName = os.path.splitext(os.path.basename(fp))[0]
        newName, ok = QInputDialog.getText(
            self, "Rename Module", "New module name:", QLineEdit.Normal, oldName)

        if ok and newName and newName != oldName:
            newFp = os.path.join(os.path.dirname(fp), newName + MODULE_EXT)
            try:
                os.rename(fp, newFp)
            except Exception as e:
                QMessageBox.critical(self, "Rename Error", f"Failed to rename:\n{e}")

    def deleteModule(self):
        paths_to_delete = self.selectedModulePaths()
        if not paths_to_delete:
            return
            
        msg = f"Are you sure you want to delete {len(paths_to_delete)} module(s)?"
        if len(paths_to_delete) == 1:
            msg = f"Are you sure you want to delete the module '{os.path.basename(paths_to_delete[0])}'?"
            
        reply = QMessageBox.question(
            self, "Delete Module", msg, QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
            
        if reply == QMessageBox.Yes:
            for fp in paths_to_delete:
                try:
                    os.remove(fp)
                except Exception as e:
                    QMessageBox.critical(self, "Delete Error", f"Failed to delete {fp}:\n{e}")

    def browseModuleDirectory(self):
        for fp in self.selectedModulePaths():
            subprocess.call("explorer /select,\"{}\"".format(os.path.normpath(fp)))

    def openModulesFolder(self):
        subprocess.call("explorer \"{}\"".format(settings.modulesPath))

    # ------------------------------------------------------------------
    # Wheel — font zoom
    # ------------------------------------------------------------------

    def wheelEvent(self, event: QWheelEvent):
        if event.modifiers() & Qt.ControlModifier:
            delta = event.angleDelta().y()
            if delta == 0:
                return
            d = delta / abs(delta)
            font = self.font()
            sz = clamp(fontSize(font) + d, 6, 20)
            setFontSize(font, sz)
            self.setFont(font)
            self.setIndentation(sz * 1.5)
            event.accept()
        else:
            super().wheelEvent(event)

    # ------------------------------------------------------------------
    # Convenience: current file path
    # ------------------------------------------------------------------

    def currentFilePath(self) -> Optional[str]:
        """Return the file path of the currently selected leaf item, or None."""
        proxyIdx = self.currentIndex()
        if not proxyIdx.isValid():
            return None
        srcIdx = self.proxyModel.mapToSource(
            self.proxyModel.index(proxyIdx.row(), COL_NAME, proxyIdx.parent()))
        item = self.browserModel.itemFromIndex(srcIdx)
        if item and not item.data(IS_DIR_ROLE):
            return item.data(FILEPATH_ROLE)
        return None


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
            

class DocViewer(QTextBrowser):
    """Doc viewer with Ctrl+wheel zoom."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setOpenExternalLinks(True)
        self.setReadOnly(True)
        self.setMaximumHeight(160)
        self.setMinimumHeight(60)
        self.hide()

    def setContent(self, html: str):
        """Display rendered HTML and show the panel."""
        self.setHtml(html)
        self.show()

    def clearContent(self):
        """Hide the panel."""
        self.hide()

    def wheelEvent(self, event: QWheelEvent):
        """Ctrl+wheel zooms the text."""
        if event.modifiers() & Qt.ControlModifier:
            delta = event.angleDelta().y()
            if delta > 0:
                self.zoomIn(1)
            elif delta < 0:
                self.zoomOut(1)
            event.accept()
        else:
            super().wheelEvent(event)


class ModuleBrowser(QWidget):
    """Embeddable module selector with filter, source options, and module tree."""

    modulesReloaded = Signal()

    def __init__(self, **kwargs):
        super().__init__(**kwargs)

        # AI Semantic Search setup
        self.indexer = ModuleIndexer()
        self.semanticResults: List[Tuple[str, float]] = []
        self._indexWorker: Optional[QThread] = None

        self._currentSearchWorker: Optional[SearchWorker] = None
        self._activeThreads = set()

        layout = QVBoxLayout()
        layout.setContentsMargins(0, 0, 0, 0)
        self.setLayout(layout)

        self.pathLabel = QLabel()
        self.pathLabel.setWordWrap(True)
        self.pathLabel.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.pathLabel.setStyleSheet(
            "color: #AAAAAA; font-style: italic; background-color: rgba(255, 255, 255, 0.05);"
            " padding: 5px; border-radius: 4px; margin-top: 5px;")

        self.searchWidget = QLineEdit()
        self.searchWidget.setPlaceholderText("Module name or description...")
        self.searchWidget.textChanged.connect(self._onMaskTextChanged)
        self.searchWidget.returnPressed.connect(self._runSemanticSearch)

        self.clearFilterButton = QPushButton("🧹 Clear")
        self.clearFilterButton.clicked.connect(self.searchWidget.clear)
        self.clearFilterButton.hide()

        filterLayout = QHBoxLayout()
        filterLayout.addWidget(QLabel("Search"))
        filterLayout.addWidget(self.searchWidget)
        filterLayout.addWidget(self.clearFilterButton)
        layout.addLayout(filterLayout)

        self.treeWidget = ModuleBrowserTree()
        layout.addWidget(self.treeWidget)

        self._docViewer = DocViewer()
        layout.addWidget(self._docViewer)

        layout.addWidget(self.pathLabel)

        # Setup timers
        self.searchTimer = QTimer(self)
        self.searchTimer.setSingleShot(True)
        self.searchTimer.timeout.connect(self._runSemanticSearch)

        self.indexTimer = QTimer(self)
        self.indexTimer.setSingleShot(True)
        self.indexTimer.timeout.connect(self._doIndexing)

        self.maskTimer = QTimer(self)
        self.maskTimer.setSingleShot(True)
        self.maskTimer.timeout.connect(self._applyMaskInternal)

        self.treeWidget.selectionModel().selectionChanged.connect(self._onSelectionChanged)

        self._setupAutoReloadWatcher()
        self.refreshModules()

    # ------------------------------------------------------------------
    # Thread management
    # ------------------------------------------------------------------

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

    # ------------------------------------------------------------------
    # Semantic search
    # ------------------------------------------------------------------

    def _runSemanticSearch(self):
        """Perform background semantic search using the current filter text."""
        self.searchTimer.stop()
        query = self.searchWidget.text().strip()
        if not query or query.startswith("/"):
            self.semanticResults = []
            self.applyMask()
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
        self.applyMask()

    def _onSemanticSearchFinished(self, query: str, results: List[Tuple[str, float]]):
        """Handle results from the semantic search thread."""
        if query != self.searchWidget.text().strip():
            return
        self.semanticResults = results
        self.applyMask()

    # ------------------------------------------------------------------
    # Doc panel
    # ------------------------------------------------------------------

    def _onSelectionChanged(self, *_):
        """Update the doc panel when the tree selection changes."""
        if not self.treeWidget.selectionModel().hasSelection():
            self._docViewer.clearContent()
            return

        fp = self.treeWidget.currentFilePath()
        doc = getDocFromFile(fp) if fp else ""
        if not doc:
            self._docViewer.clearContent()
            return

        html = markdown.markdown(
            doc,
            extensions=["fenced_code", "tables", "nl2br",
                        "sane_lists", "codehilite", "toc", "extra"],
            output_format="html5")
        self._docViewer.setContent(html)

    # ------------------------------------------------------------------
    # Path label
    # ------------------------------------------------------------------

    def _updatePathLabel(self):
        path = os.path.normpath(settings.modulesPath)
        userRoot = os.path.normpath(RIG_BUILDER_USER_PATH)
        appRoot = os.path.normpath(RIG_BUILDER_PATH)

        if path.lower().startswith(userRoot.lower()):
            rel = os.path.relpath(path, userRoot)
            displayText = "User" if rel == "." else os.path.join("User", rel)
        elif path.lower().startswith(appRoot.lower()):
            rel = os.path.relpath(path, appRoot)
            displayText = "App" if rel == "." else os.path.join("App", rel)
        else:
            displayText = path

        self.pathLabel.setText(displayText.replace("\\", "/"))

    # ------------------------------------------------------------------
    # Watcher
    # ------------------------------------------------------------------

    def _setupAutoReloadWatcher(self):
        self.modulesAutoReloadWatcher = DirectoryWatcher(
            [settings.modulesPath],
            filePatterns=["*" + ext for ext in MODULE_EXTS],
            debounceMs=700,
            recursive=True,
            parent=self)
        self.modulesAutoReloadWatcher.fileChanged.connect(lambda _: self.refreshModules())

    # ------------------------------------------------------------------
    # Refresh / build
    # ------------------------------------------------------------------

    def refreshModules(self):
        """Startup and auto-reload entry point. Rebuilds the model."""
        self._updatePathLabel()
        UidManager.sync()

        self.indexer.filePath = os.path.join(settings.workspacePath, "moduleIndex.json")
        self.indexer.refresh()
        self._startIndexing()

        self._buildTree()
        self.applyMask()

    def _buildTree(self):
        """Rebuild the model from disk. Proxy filtering is applied separately."""
        modulesDirectory = settings.modulesPath
        modules = sorted(UidManager.uids().values())
        self.treeWidget.browserModel.rebuild(modulesDirectory, modules)

    # ------------------------------------------------------------------
    # Filtering / masking
    # ------------------------------------------------------------------

    def _onMaskTextChanged(self, text: str):
        self.clearFilterButton.setVisible(bool(text))
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
        """Update model visibility flags and sorting via the proxy."""
        maskText = self.searchWidget.text().strip()
        isSearching = bool(maskText)

        scores = (
            {os.path.normpath(p).lower(): s for p, s in self.semanticResults if p}
            if self.semanticResults else {})

        model = self.treeWidget.browserModel
        foldersToExpand = []

        # 1. Assign scores and hidden flags to file items
        for nameItem in model.fileItems():
            absF = nameItem.data(FILEPATH_ROLE) or ""

            score = 0.0
            if isSearching:
                moduleName = os.path.splitext(os.path.basename(absF))[0]
                if all(m in moduleName.lower() for m in maskText.lower().split()):
                    score = 1.0
                else:
                    score = scores.get(absF, 0.0)

            model.setScore(nameItem, score)
            showItem = (not isSearching) or score >= 0.5
            nameItem.setData(not showItem, _HIDDEN_ROLE)

        # 2. Update folder visibility based on their children
        def updateFolder(parentItem: QStandardItem) -> float:
            maxScore = 0.0
            anyVisible = False
            for r in range(parentItem.rowCount()):
                child = parentItem.child(r, COL_NAME)
                if child is None:
                    continue

                childScore = 0.0
                if child.data(IS_DIR_ROLE):
                    childScore = updateFolder(child)
                else:
                    childScore = child.data(SCORE_ROLE) or 0.0

                maxScore = max(maxScore, childScore)
                anyVisible = anyVisible or not child.data(_HIDDEN_ROLE)

            if parentItem is not model.invisibleRootItem():
                parentItem.setData(not anyVisible, _HIDDEN_ROLE)
                model.setScore(parentItem, maxScore)
                if isSearching and anyVisible:
                    foldersToExpand.append(parentItem)

            return maxScore

        updateFolder(model.invisibleRootItem())

        # 3. Notify proxy to re-evaluate filter and re-sort
        self.treeWidget.proxyModel.invalidateFilter()

        # 4. Expand folders after filter update
        if isSearching:
            for item in foldersToExpand:
                proxyIdx = self.treeWidget.proxyModel.mapFromSource(
                    model.indexFromItem(item))
                if proxyIdx.isValid():
                    self.treeWidget.setExpanded(proxyIdx, True)

        self.treeWidget.sortByColumn(COL_NAME, Qt.AscendingOrder)
