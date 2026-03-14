"""Local module edit history: git-tracked saves and info-browser UI."""

from __future__ import annotations

import os
import re
from typing import Any, Dict, List, Optional, Tuple
import xml.etree.ElementTree as ET
from xml.sax.saxutils import escape

from .core import getHistoryPath, Module, MODULE_EXT
from .gitrepo import GitRepo


# --- Constants ---

GIT_INSTALL_URL = "https://git-scm.com/downloads"
HISTORY_LINK_SCHEME = "history"
DEFAULT_COMMIT_LIMIT = 30
FILTERED_COMMIT_LIMIT = 100


# --- Repo and module ---

def _getHistoryRepo() -> Optional[GitRepo]:
    """Return GitRepo for history directory, or None if git unavailable or init fails."""
    if not GitRepo.isAvailable():
        return None
    path = getHistoryPath()
    repo = GitRepo(path)
    if not GitRepo.exists(path) and not repo.init():
        return None
    return repo


def getHistoryRepo() -> Optional[GitRepo]:
    """Return GitRepo for history directory (for UI link handling)."""
    return _getHistoryRepo()


def getModuleNameForUid(uid: str) -> str:
    """Display name for a module UID from its history file."""
    path = os.path.join(getHistoryPath(), uid + MODULE_EXT)
    if not os.path.isfile(path):
        return uid or "unknown"
    try:
        root = ET.parse(path).getroot()
        name = root.attrib.get("name", "")
        if name:
            return name
    except Exception:
        pass
    return os.path.splitext(os.path.basename(path))[0] or "unknown"


# --- Recording saves ---

def recordModuleSave(module: Module, commitMessage: str) -> bool:
    """Write module XML to history and commit. Commit message must be set by callee. Returns True on success."""
    repo = _getHistoryRepo()
    if not repo:
        return False
    uid = module.uid()
    if not uid:
        return False

    historyFile = os.path.join(getHistoryPath(), uid + MODULE_EXT)
    try:
        with open(historyFile, "w", encoding="utf-8") as f:
            f.write(module.toXml(keepConnections=False))
    except OSError:
        return False

    message = (commitMessage or "").strip()
    if not message:
        base = module.getSavePath() or module.name() + MODULE_EXT
        baseName = os.path.basename(base)
        if not baseName.lower().endswith(MODULE_EXT):
            baseName += MODULE_EXT

        message = "update {}".format(baseName)

    err, _ = repo.commit(message, [historyFile])
    return not err


# --- Squash ---

def squashHistory(message: str = "Initial squashed") -> Tuple[bool, str]:
    """
    Squash entire history into a single commit using an orphan branch. The repo
    will have one commit with the current tree. Returns (success, errorMessage).
    """
    repo = _getHistoryRepo()
    if not repo:
        return False, "History repo not available."

    _, out = repo("branch --list main master")
    branch = "master" if (out and "master" in out) else "main" if (out and "main" in out) else None
    if not branch:
        return False, "No main or master branch found."

    tempBranch = "squashed-main"
    repo("checkout {}".format(branch))
    repo("branch -D {}".format(tempBranch))
    err, _ = repo("checkout --orphan {}".format(tempBranch))
    if err:
        repo("checkout {}".format(branch))
        return False, "Failed to create orphan branch: {}".format(err)
    msg = (message or "Squashed history").strip()
    err, _ = repo.commit(msg, [])
    if err:
        repo("checkout {}".format(branch))
        repo("branch -D {}".format(tempBranch))
        return False, "Commit failed: {}".format(err)
    repo("checkout {}".format(branch))
    repo("reset --hard {}".format(tempBranch))
    repo("branch -D {}".format(tempBranch))
    return True, ""


# --- Git log ---

def getModuleHistoryEntries(
    limit: int = DEFAULT_COMMIT_LIMIT,
    filterUid: Optional[str] = None,
    filterName: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """Return history entries from git log; optional filter by UID or module name."""
    repo = _getHistoryRepo()
    if not repo:
        return []

    if filterUid or filterName:
        limit = min(limit, FILTERED_COMMIT_LIMIT)

    err, out = repo('log -n {} --pretty=format:"%h %ai %s" --name-only'.format(limit))
    if err or not out:
        return []

    entries = []
    for block in out.replace("\r", "").strip().split("\n\n"):
        lines = [s.strip() for s in block.strip().split("\n") if s.strip()]
        if not lines:
            continue

        parts = lines[0].split()
        if len(parts) < 5:
            continue

        rev, dateStr, subject = parts[0], " ".join(parts[1:4]), " ".join(parts[4:])
        files = []
        for line in lines[1:]:
            if not line.endswith(MODULE_EXT):
                continue

            uid = line[:-len(MODULE_EXT)]
            if filterUid and uid != filterUid:
                continue

            if filterName and filterName.lower() not in getModuleNameForUid(uid).lower():
                continue

            files.append(uid)

        if (filterUid or filterName) and not files:
            continue

        entries.append({"rev": rev, "subject": subject, "date": dateStr, "files": files})
    
    return entries


# --- Info browser HTML ---

def buildHistoryHtml(filterText: str = "") -> str:
    """Build HTML for the module history widget: install-Git message or filtered history list."""
    if not GitRepo.isAvailable():
        reason = "Git is required for module history."
        return (
            "<h2>📜 Module history</h2><p>{}</p>"
            "<p><a style='color: #55aaee' href='{}'>Install Git</a></p>"
        ).format(escape(reason), escape(GIT_INSTALL_URL))

    repo = _getHistoryRepo()
    if not repo:
        reason = "Could not initialize history (check git user.name and user.email)."
        return (
            "<h2>📜 Module history</h2><p>{}</p>"
            "<p><a style='color: #55aaee' href='{}'>Install Git</a></p>"
        ).format(escape(reason), escape(GIT_INSTALL_URL))

    s = filterText.strip()
    filterUid = s if s and re.match(r"^[a-f0-9]{32}$", s) else None
    filterName = None if filterUid else (s if s else None)
    limit = FILTERED_COMMIT_LIMIT if (filterUid or filterName) else DEFAULT_COMMIT_LIMIT
    entries = getModuleHistoryEntries(limit=limit, filterUid=filterUid, filterName=filterName)
    parts = ["<h2>📜 Module history</h2>"]

    if not entries:
        parts.append("<p>No history yet. Save a module to create the first commit.</p>")
    else:
        for entry in entries:
            rev, subject, dateStr = entry["rev"], entry["subject"], entry["date"]
            dateTimeParts = (dateStr or "").split()[:2]
            datePart = dateTimeParts[0] if dateTimeParts else ""
            timePart = dateTimeParts[1] if len(dateTimeParts) > 1 else ""
            for uid in entry["files"]:
                moduleFile = escape(getModuleNameForUid(uid) + MODULE_EXT)
                diffUrl = "{}:{}:{}".format(HISTORY_LINK_SCHEME, rev, uid)
                fullUrl = "{}:full:{}:{}".format(HISTORY_LINK_SCHEME, rev, uid)
                recoverUrl = "{}:recover:{}:{}".format(HISTORY_LINK_SCHEME, rev, uid)
                diffLink = "<a style='color:#55aaee' href='{}' title='View diff for this commit'>diff</a>".format(diffUrl)
                fullLink = " <a style='color:#55aaee' href='{}' title='View full file at this commit'>full</a>".format(fullUrl)
                recoverLink = " <a style='color:#55aaee' href='{}' title='Add module from this revision to the tree'>recover</a>".format(recoverUrl)
                line = "{}, {}, <b>{}</b>: {} {}{}{}".format(
                    escape(datePart), escape(timePart), moduleFile, escape(subject), diffLink, fullLink, recoverLink
                )
                parts.append("<p>{}</p>".format(line))
    return "".join(parts)

