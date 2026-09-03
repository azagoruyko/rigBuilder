from __future__ import annotations

import os
import re
import glob
from .settings import settings, MODULE_EXTS
from typing import Optional

class UidManager:
    _uids = {} # uid: path
    _mtimeCache = {} # path: (mtime, uid)

    @classmethod
    def sync(cls):
        """Sync cached UIDs from modules directory."""
        cls._uids = cls.findUids(settings.modulesPath)

    @classmethod
    def get(cls, uid: str) -> Optional[str]:
        """Get file path by UID."""
        return cls._uids.get(uid)

    @classmethod
    def uids(cls) -> dict[str, str]:
        """Get all cached UIDs."""
        return cls._uids

    @classmethod
    def resolve(cls, spec: str) -> str:
        """Resolve spec (path or uid) to module file path, or empty string if not found."""
        if not spec:
            return ""
            
        modulePath = cls.get(spec)
        if not modulePath:
            root = settings.modulesPath
            spec = os.path.expandvars(spec)

            specPaths = [
                root + spec + ext
                for root in ("", f"{root}/")
                for ext in ("",) + MODULE_EXTS
            ]

            for path in specPaths:
                if os.path.exists(path):
                    modulePath = path
                    break

        return os.path.normpath(modulePath) if modulePath else ""

    @classmethod
    def getUidFromFile(cls, path: str) -> str:
        """Extract UID from a module file (.rb or .xml) using mtime cache."""
        if not any(path.endswith(ext) for ext in MODULE_EXTS):
            return ""

        mtime = os.path.getmtime(path)

        if path in cls._mtimeCache:
            cachedMtime, cachedUid = cls._mtimeCache[path]
            if cachedMtime == mtime and cachedUid:
                return cachedUid

        with open(path, "r", encoding="utf-8", errors="ignore") as f:
            content = f.read(4096)  # Read first 4KB to locate uid attribute

        r = re.search(r'uid="(\w+)"', content)
        uid = r.group(1) if r else ""

        if uid:
            cls._mtimeCache[path] = (mtime, uid)
        return uid

    @classmethod
    def findUids(cls, path: str) -> dict[str, str]:
        """Find all UIDs and their file paths in directory."""
        uids = {}
        if not os.path.exists(path):
            return uids

        for root, _, files in os.walk(path):
            for file in sorted(files):
                if any(file.endswith(ext) for ext in MODULE_EXTS):
                    fpath = os.path.join(root, file)
                    uid = cls.getUidFromFile(fpath)
                    if uid:
                        uids[uid] = os.path.normpath(fpath)
        return uids
