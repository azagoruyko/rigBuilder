from __future__ import annotations
import html
import os
import xml.etree.ElementTree as ET
from typing import List, Protocol, Optional, Union, TYPE_CHECKING

if TYPE_CHECKING:
    from xml.etree.ElementTree import Element

from .settings import (
    Settings, 
    RIG_BUILDER_USER_PATH, 
    RIG_BUILDER_PATH,
    RIG_BUILDER_WORKSPACES_PATH
)

from .core import Module, UidManager
from .utils import forceRemove

def flattenModules(roots: List[Module]) -> List[Module]:
    """Return all modules in depth-first order (roots and every descendant)."""
    flat = []
    stack = list(reversed(roots))
    while stack:
        m = stack.pop()
        flat.append(m)
        stack.extend(reversed(m.children()))
    return flat

class WorkspaceFile:
    def __init__(self):
        self.modules: List[Module] = []
        self.expanded: List[bool] = []
    
    def toXml(self) -> str:
        """Serialize workspace file to XML."""

        lines = ['<workspace>']

        lines.append("<modules>")
        for module in self.modules:
            lines.append(module.toXml())
        lines.append("</modules>")

        if self.expanded:
            value = ",".join(str(int(x)) for x in self.expanded)
            lines.append('<expanded value="{}"/>'.format(value))

        lines.append("</workspace>")
        return "\n".join(lines)

    @classmethod
    def fromXml(cls, xml: Union[str, Element]) -> WorkspaceFile:
        """Deserialize workspace file from XML."""

        root = ET.fromstring(xml) if isinstance(xml, str) else xml
        wsFile = cls()

        modulesEl = root.find("modules")
        if modulesEl is not None:
            for child in modulesEl:
                if child.tag == "module":
                    try:
                        wsFile.modules.append(Module.fromXml(child))
                    except Exception as e:
                        print(f"Failed to load module: {e}")

        # Expanded states
        expandedEl = root.find("expanded")
        if expandedEl is not None:
            raw = expandedEl.attrib.get("value", "")
            if raw:
                wsFile.expanded = [x == "1" for x in raw.split(",")]

        return wsFile

    def save(self, filePath: str) -> None:
        """Save workspace file to file."""
        with open(filePath, "w", encoding="utf-8") as f:
            f.write(self.toXml())

    @classmethod
    def load(cls, filePath: str) -> WorkspaceFile:
        """Load workspace file from file."""
        with open(filePath, "r", encoding="utf-8") as f:
            return cls.fromXml(f.read())

class Workspace:
    """Represents a local project workspace with its own modules and settings."""
    def __init__(self, name: str):
        self.name = name
        self.folderPath = os.path.join(RIG_BUILDER_WORKSPACES_PATH, name)
        self.file = WorkspaceFile()
        
        self.settings = Settings()
        self.settings.modulesPath = os.path.join(self.folderPath, "modules")
        self.settings.historyPath = os.path.join(self.folderPath, "history")

    def save(self) -> None:
        """Save workspace state."""
        os.makedirs(self.folderPath, exist_ok=True)
        self.file.save(os.path.join(self.folderPath, "workspace.rbws"))
        self.settings.save(os.path.join(self.folderPath, "settings.json"))

    @classmethod
    def load(cls, name: str) -> Workspace:
        """Load workspace data."""
        folderPath = os.path.join(RIG_BUILDER_WORKSPACES_PATH, name)

        workspace = cls(name)
        workspace.file = WorkspaceFile.load(os.path.join(folderPath, "workspace.rbws"))
        workspace.settings.load(os.path.join(folderPath, "settings.json"))

        # Fallback to default paths for invalid paths
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
            forceRemove(self.folderPath)
            return True
        except Exception as e:
            print(f"Failed to delete workspace folder: {e}")
            return False

    @classmethod
    def list(cls) -> List[str]:
        """List all available workspace names in the standard directory."""
        workspaces = []
        for d in os.listdir(RIG_BUILDER_WORKSPACES_PATH):
            dirPath = os.path.join(RIG_BUILDER_WORKSPACES_PATH, d)
            if os.path.isdir(dirPath):
                workspaces.append(d)
        
        return sorted(workspaces)

    @classmethod
    def exists(cls, name: str) -> bool:
        """Check if a workspace with the given name exists."""
        folderPath = os.path.join(RIG_BUILDER_WORKSPACES_PATH, name)
        return os.path.exists(folderPath)

def getOrCreateDefaultWorkspace() -> Workspace:
    """Get default workspace or create it if it doesn't exist."""
    if Workspace.exists("default"):
        return Workspace.load("default")

    ws = Workspace("default")
    ws.settings.modulesPath = os.path.join(RIG_BUILDER_PATH, "modules")
    ws.save()
    
    return ws

currentWorkspace = getOrCreateDefaultWorkspace()
currentWorkspace.activate()
