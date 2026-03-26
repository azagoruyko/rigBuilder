import os
import time
import fnmatch
from typing import List, Optional, Callable

from ..qt import *

trackFileChangesThreads = {} # by file path

class TrackFileChangesThread(QThread):
    somethingChanged = Signal()

    def __init__(self, filePath: str):
        super().__init__()
        self.filePath = filePath
        self._running = True

    def stop(self):
        self._running = False

    def run(self):
        try:
            lastModified = os.path.getmtime(self.filePath)
        except Exception:
            lastModified = 0

        while self._running:
            try:
                if not os.path.exists(self.filePath):
                    time.sleep(1)
                    continue

                currentModified = os.path.getmtime(self.filePath)
                if currentModified != lastModified:
                    self.somethingChanged.emit()
                    lastModified = currentModified
            except Exception:
                pass # ignore temporary file access errors
            
            time.sleep(1)

class DirectoryWatcher(QObject):
    """Watch directories recursively and emit debounced change events."""
    somethingChanged = Signal()

    def __init__(self, roots: List[str], *, debounceMs: int = 700, filePatterns: Optional[List[str]] = None, recursive: bool = True, parent: Optional[QObject] = None):
        super().__init__(parent=parent)
        self.roots = [os.path.normpath(p) for p in roots if os.path.exists(p)]
        self.debounceMs = debounceMs
        self.filePatterns = [p.lower() for p in (filePatterns or [])]
        self.recursive = recursive
        self.watcher = QFileSystemWatcher(self)
        self.debounceTimer = QTimer(self)
        self.debounceTimer.setSingleShot(True)

        self.watcher.directoryChanged.connect(self._onFilesystemChanged)
        self.watcher.fileChanged.connect(self._onFilesystemChanged)
        self.debounceTimer.timeout.connect(self._onDebounceTimeout)

        self.refreshWatchedPaths()

    def refreshWatchedPaths(self):
        paths = set()
        for root in self.roots:
            walkIterator = os.walk(root)
            for dirPath, _, fileNames in walkIterator:
                paths.add(os.path.normpath(dirPath))
                for fileName in fileNames:
                    fileNameLower = fileName.lower()
                    if not self.filePatterns or any(fnmatch.fnmatch(fileNameLower, p) for p in self.filePatterns):
                        paths.add(os.path.normpath(os.path.join(dirPath, fileName)))
                if not self.recursive:
                    break

        if not paths:
            return

        oldPaths = set(self.watcher.files() + self.watcher.directories())
        toRemove = list(oldPaths - paths)
        toAdd = list(paths - oldPaths)
        if toRemove:
            self.watcher.removePaths(toRemove)
        if toAdd:
            self.watcher.addPaths(toAdd)

    def _onFilesystemChanged(self, _path: str):
        self.debounceTimer.start(self.debounceMs)

    def _onDebounceTimeout(self):
        # File watchers can drop updated paths on some platforms, so refresh first.
        self.refreshWatchedPaths()
        self.somethingChanged.emit()
