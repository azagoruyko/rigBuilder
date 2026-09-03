from __future__ import annotations

import os
import fnmatch
from typing import Optional

from .qt import *


class DirectoryWatcher(QObject):
    """Watch directories recursively and emit debounced change events."""
    fileChanged = Signal(str)

    def __init__(
        self,
        roots: list[str],
        *,
        debounceMs: int = 700,
        filePatterns: Optional[list[str]] = None,
        recursive: bool = True,
        parent: Optional[QObject] = None,
    ):
        super().__init__(parent=parent)
        self.debounceMs = debounceMs
        self.filePatterns = [p.lower() for p in (filePatterns or [])]
        self.recursive = recursive
        self.roots = []

        self.watcher = QFileSystemWatcher(self)
        self.debounceTimer = QTimer(self)
        self.debounceTimer.setSingleShot(True)
        self._changedPaths = set()

        self.watcher.directoryChanged.connect(self._onFilesystemChanged)
        self.watcher.fileChanged.connect(self._onFilesystemChanged)
        self.debounceTimer.timeout.connect(self._onDebounceTimeout)

        self.setRoots(roots)

    def setRoots(self, roots: list[str]):
        """Update monitored roots and refresh watcher."""
        self.roots = [os.path.normpath(p) for p in roots if os.path.exists(p)]
        self.refreshWatchedPaths()

    def refreshWatchedPaths(self):
        """Re-scan filesystem trees and update QFileSystemWatcher subscriptions."""
        paths = set()
        for root in self.roots:
            if not os.path.exists(root):
                continue
            paths.add(root)
            for dirPath, _, filenames in os.walk(root):
                normDir = os.path.normpath(dirPath)
                paths.add(normDir)

                for filename in filenames:
                    filePath = os.path.normpath(os.path.join(dirPath, filename))
                    if self._matchesPatterns(filePath):
                        paths.add(filePath)

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
        for path in list(self._changedPaths):
            if os.path.isdir(path) or self._matchesPatterns(path):
                self.fileChanged.emit(path)
        self._changedPaths.clear()

    def _matchesPatterns(self, path: str) -> bool:
        """Check if path matches configured glob patterns."""
        if not self.filePatterns:
            return True
        filename = os.path.basename(path).lower()
        pathLower = path.lower()
        return any(fnmatch.fnmatch(filename, pat) or fnmatch.fnmatch(pathLower, pat) for pat in self.filePatterns)
