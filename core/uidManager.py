import os
import re
import glob
from .settings import settings, MODULE_EXTS
from typing import Optional

class UidManager:
    _uids: dict[str, str] = {} # uid: path
    _mtimeCache: dict[str, tuple[float, str]] = {} # path: (mtime, uid)

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
            if cachedMtime == mtime:
                return cachedUid

        with open(path, "r", encoding="utf-8") as f:
            l = f.readline()  # read first line
        r = re.search("uid=\"(\\w*)\"", l)
        uid = r.group(1) if r else ""

        cls._mtimeCache[path] = (mtime, uid)
        return uid

    @classmethod
    def findUids(cls, path: str) -> dict[str, str]:
        """Find all UIDs and their file paths in directory."""
        uids = {}
        for fpath in sorted(glob.iglob(path + "/*")):
            if os.path.isdir(fpath):
                uids.update(cls.findUids(fpath))
            elif any(fpath.endswith(ext) for ext in MODULE_EXTS):
                uid = cls.getUidFromFile(fpath)
                if uid:
                    uids[uid] = fpath
        return uids
