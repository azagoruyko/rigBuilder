"""Git repository wrapper for running git commands in a given working directory."""

from __future__ import annotations

import os
import shlex
import shutil
import sys
import subprocess
from pathlib import Path
from typing import List, Optional, Tuple


if sys.platform == "win32":
    _startupinfo = subprocess.STARTUPINFO()
    _startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
else:
    _startupinfo = None


class GitRepo:
    """Wrapper for git commands in a given working directory."""

    def __init__(self, path: str) -> None:
        """Initialize with the repository working directory (file or directory path)."""
        self.workingDirectory = Path(path)

    @staticmethod
    def findRepo(path: str) -> Optional[GitRepo]:
        """Search upward from path for a directory containing .git; return GitRepo or None."""
        path = Path(path)
        if not path.is_dir():
            path = path.parent

        if not path or path.parent == path:
            return None

        if (path / ".git").exists():
            return GitRepo(path)
        return GitRepo.findRepo(path.parent)

    @staticmethod
    def exists(path: str) -> bool:
        """Return True if path contains a .git directory."""
        return (Path(path) / ".git").exists()

    @staticmethod
    def isAvailable() -> bool:
        """Return True if git executable is found on PATH."""
        return shutil.which("git") is not None

    def init(self) -> bool:
        """Ensure repo exists (run git init if needed). Return False if user/email not set in config."""
        _, user = self("config user.name")
        _, email = self("config user.email")
        if not user or not email:
            print("Set user name and email in .gitconfig")
            return False

        if not self.exists(self.workingDirectory):
            self("init")

        return True

    def empty(self) -> bool:
        """Return True if the repo has no branches."""
        _, out = self("branch -l")
        return not any(line.strip() for line in out.splitlines())

    def __call__(self, cmd: str) -> Tuple[str, str]:
        """Run git with the given command string (split into args, no shell). Return (stderr, stdout)."""
        kwargs = {
            "cwd": os.fspath(self.workingDirectory),
            "stdin": subprocess.DEVNULL,
            "stdout": subprocess.PIPE,
            "stderr": subprocess.PIPE,
            "text": True,
            "encoding": "utf-8",
            "errors": "replace",
            "shell": False,
        }
        if _startupinfo is not None:
            kwargs["startupinfo"] = _startupinfo
        
        args = shlex.split(cmd)
        result = subprocess.run(["git"] + args, **kwargs)
        
        out = (result.stdout or "").strip()
        err = (result.stderr or "").strip() if result.returncode != 0 else ""
        return err, out

    def commit(
        self,
        message: str,
        files: List[str],
        amend: bool = False,
    ) -> Tuple[str, str]:
        """Stage files (if any), then commit with message. If amend, append to previous message. Return (err, out)."""
        workDir = os.fspath(self.workingDirectory)
        files = [os.path.relpath(os.fspath(f), workDir) for f in files]

        if files:
            # Quote files to handle spaces in paths
            filesStr = " ".join(['"{}"'.format(f.replace('"', '\\"')) for f in files])
            err, out = self("add " + filesStr)
            if err and not err.startswith("warning:"):
                print(err)
                return err, out

        if amend:
            _, prevMessage = self("log -1 --pretty=%B")
            message = "\n\n".join([message, prevMessage])

        # Use multiple -m flags and quote content to handle spaces and special characters
        msgArgs = ['-m "{}"'.format(m.replace('"', '\\"')) for m in message.split("\n")]
        return self("commit " + " ".join(msgArgs))

    def __repr__(self) -> str:
        return "<GitRepo at '{}'>".format(self.workingDirectory)
