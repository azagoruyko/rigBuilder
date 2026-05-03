from __future__ import annotations
import html
import os
import xml.etree.ElementTree as ET
import shutil
from typing import List, Protocol, Optional

from .settings import (
    Settings, 
    RIG_BUILDER_USER_PATH, 
    RIG_BUILDER_PATH,
    RIG_BUILDER_WORKSPACES_PATH
)

from .core import Module, UidManager
from .gitrepo import GitRepo
from .utils import replaceSpecialChars, forceRemove

def flattenModules(roots: List[Module]) -> List[Module]:
    """Return all modules in depth-first order (roots and every descendant)."""
    flat = []
    stack = list(reversed(roots))
    while stack:
        m = stack.pop()
        flat.append(m)
        stack.extend(reversed(m.children()))
    return flat

class Workspace:
    """Represents a local project workspace with its own modules and settings."""
    def __init__(self, name: str = ""):            
        self.name = replaceSpecialChars(name)
        
        self.modules: List[Module] = []
        self.expanded: List[bool] = []
        
        self.settings = Settings()
        self.settings.modulesPath = os.path.join(self.folderPath(), "modules")
        self.settings.historyPath = os.path.join(self.folderPath(), "history")

    def folderPath(self) -> str:
        return os.path.join(RIG_BUILDER_WORKSPACES_PATH, replaceSpecialChars(self.name))

    def toXml(self) -> str:
        lines = [
            '<workspace>',
        ]

        lines.append("<modules>")
        for module in self.modules:
            lines.append(module.toXml(keepConnections=True).strip())
        lines.append("</modules>")

        if self.expanded:
            value = ",".join(str(int(x)) for x in self.expanded)
            lines.append('<expanded value="{}"/>'.format(value))

        lines.append("</workspace>")
        return "\n".join(lines)

    def save(self) -> None:
        """Save workspace state."""
        os.makedirs(self.folderPath(), exist_ok=True)
        filePath = os.path.join(self.folderPath(), "workspace.rbws")
        with open(filePath, "w", encoding="utf-8") as f:
            f.write(self.toXml())
        
        self.settings.save(os.path.join(self.folderPath(), "settings.json"))

    @classmethod
    def load(cls, name: str) -> Optional[Workspace]:
        """Load workspace data."""
        folderPath = os.path.join(RIG_BUILDER_WORKSPACES_PATH, replaceSpecialChars(name))

        workspaceFilePath = os.path.join(folderPath, "workspace.rbws")

        try:
            tree = ET.parse(workspaceFilePath)
            root = tree.getroot()
        except ET.ParseError as e:
            print(f"Cannot parse workspace: {e}")
            return None

        workspace = cls(name)

        # Modules
        modulesEl = root.find("modules")
        if modulesEl is not None:
            for child in modulesEl:
                if child.tag == "module":
                    try:
                        workspace.modules.append(Module.fromXml(child))
                    except Exception as e:
                        print(f"Failed to load module: {e}")

        # Expanded states
        expandedEl = root.find("expanded")
        if expandedEl is not None:
            raw = expandedEl.attrib.get("value", "")
            if raw:
                workspace.expanded = [x == "1" for x in raw.split(",")]

        workspace.settings.load(os.path.join(folderPath, "settings.json"))

        # Fix empty paths
        if not os.path.exists(workspace.settings.historyPath):
            workspace.settings.historyPath = os.path.join(folderPath, "history")

        if not os.path.exists(workspace.settings.modulesPath):
            workspace.settings.modulesPath = os.path.join(folderPath, "modules")

        return workspace

    def activate(self) -> bool:
        """Core activation: populate runtime Settings from this workspace."""        
        # Ensure directories and repos exist
        for p in [self.settings.historyPath, self.settings.modulesPath]:
            os.makedirs(p, exist_ok=True)

        repo = GitRepo(self.settings.historyPath)
        repo.init()
        
        # Refresh UID Manager
        UidManager.sync()

        # Update global settings from workspace settings
        from .settings import settings
        settings.fromDict(self.settings.toDict())

        # Update current global workspace instance
        global currentWorkspace
        currentWorkspace = self

        return True

    def delete(self) -> bool:
        """Delete the entire workspace folder."""
        try:
            forceRemove(self.folderPath())
            return True
        except Exception as e:
            print(f"Failed to delete workspace folder: {e}")
            return False

    @classmethod
    def list(cls) -> List[Workspace]:
        """List all available workspaces in the standard directory."""
        workspaces = []
        for d in os.listdir(RIG_BUILDER_WORKSPACES_PATH):
            dirPath = os.path.join(RIG_BUILDER_WORKSPACES_PATH, d)
            if os.path.isdir(dirPath):
                ws = cls.load(d)
                if ws:
                    workspaces.append(ws)
        
        return sorted(workspaces, key=lambda x: x.name.lower())

    @classmethod
    def exists(cls, name: str) -> bool:
        """Check if a workspace with the given name exists."""
        folderPath = os.path.join(RIG_BUILDER_WORKSPACES_PATH, replaceSpecialChars(name))
        return os.path.exists(folderPath)

    @classmethod
    def create(cls, name: str) -> Optional[Workspace]:
        """Create a new workspace directory structure."""        
        if cls.exists(name):
            return

        ws = cls(name)
        ws.save()
        return ws

def createDefaultWorkspace():
    ws = Workspace.create("default")
    if not ws:
        return
    
    ws.settings.modulesPath = os.path.join(RIG_BUILDER_PATH, "modules")
    ws.settings.historyPath = os.path.join(ws.folderPath(), "history")
    ws.save()

currentWorkspace = createDefaultWorkspace() or Workspace.load("default")
currentWorkspace.activate()
