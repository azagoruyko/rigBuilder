import os
import time
import fnmatch
from typing import List, Optional, Callable

from .qt import *

trackFileChangesThreads = {} # by file path

class TrackFileChangesThread(QThread):
    fileChanged = Signal(str)

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
                    self.fileChanged.emit(self.filePath)
                    lastModified = currentModified
            except Exception:
                pass # ignore temporary file access errors
            
            time.sleep(1)

class DirectoryWatcher(QObject):
    """Watch directories recursively and emit debounced change events."""
    fileChanged = Signal(str)

    def __init__(self, roots: List[str], *, debounceMs: int = 700, filePatterns: Optional[List[str]] = None, recursive: bool = True, parent: Optional[QObject] = None):
        super().__init__(parent=parent)
        self.roots = [os.path.normpath(p) for p in roots if os.path.exists(p)]
        self.debounceMs = debounceMs
        self.filePatterns = [p.lower() for p in (filePatterns or [])]
        self.recursive = recursive
        self.watcher = QFileSystemWatcher(self)
        self.debounceTimer = QTimer(self)
        self.debounceTimer.setSingleShot(True)
        self._changedPaths = set()

        self.watcher.directoryChanged.connect(self._onFilesystemChanged)
        self.watcher.fileChanged.connect(self._onFilesystemChanged)
        self.debounceTimer.timeout.connect(self._onDebounceTimeout)

        self.refreshWatchedPaths()

    def setRoots(self, roots: List[str]):
        """Update monitored roots and refresh watcher."""
        self.roots = [os.path.normpath(p) for p in roots if os.path.exists(p)]
        self.refreshWatchedPaths()

    def refreshWatchedPaths(self):
        paths = set()
        for root in self.roots:
            if not os.path.exists(root):
                continue
            
            normRoot = os.path.normpath(root)
            paths.add(normRoot)
            
            for dirPath, _, _ in os.walk(normRoot):
                paths.add(os.path.normpath(dirPath))
                if not self.recursive:
                    break

        oldPaths = set(os.path.normpath(p) for p in (self.watcher.files() + self.watcher.directories()))
        if not paths and not oldPaths:
            return

        toRemove = list(oldPaths - paths)
        toAdd = list(paths - oldPaths)
        if toRemove:
            self.watcher.removePaths(toRemove)
        if toAdd:
            self.watcher.addPaths(toAdd)

    def _onFilesystemChanged(self, path: str):
        self._changedPaths.add(os.path.normpath(path))
        self.debounceTimer.start(self.debounceMs)

    def _onDebounceTimeout(self):
        self.refreshWatchedPaths()
        for p in self._changedPaths:
            self.fileChanged.emit(p)
        self._changedPaths.clear()
