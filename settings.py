import os
import json
from .utils import loadJson, saveJson

RIG_BUILDER_PATH = os.path.normpath(os.path.dirname(__file__))
RIG_BUILDER_USER_PATH = os.path.normpath(os.path.join(os.path.expanduser("~"), "rigBuilder"))
RIG_BUILDER_WORKSPACES_PATH = os.path.normpath(os.path.join(RIG_BUILDER_USER_PATH, "workspaces"))
RIG_BUILDER_MODULES_PATH = os.path.normpath(os.path.join(RIG_BUILDER_PATH, "modules"))

STATE_PATH = os.path.join(RIG_BUILDER_USER_PATH, "state.json")

class BaseConfig:
    """Base class for configuration objects with shared load/save/update logic."""
    def update(self, data: dict):
        """Update instance attributes from a dictionary."""
        for key, value in data.items():
            if hasattr(self, key):
                setattr(self, key, value)

    def toDict(self) -> dict:
        """Return a dictionary representation of the config."""
        return {k: v for k, v in self.__dict__.items() if not k.startswith("_")}

    def load(self, path: str):
        """Load configuration from a JSON file."""
        self.update(loadJson(path))

    def save(self, path: str):
        """Save configuration to a JSON file."""
        saveJson(path, self.toDict())

class Settings(BaseConfig):
    """Container for persistent user preferences with explicit attributes and path helpers."""
    def __init__(self):
        self.vscode = "code"
        self.modulesPath = ""
        self.historyPath = ""
        self.trackHistory = True
        self.ollamaModel = "gpt-oss:20b-cloud"
        self.aiLanguage = "English"

    def getModulesPath(self) -> str:
        """Return the modules root directory, normalized.
        Defaults to local workspace modules for non-default workspaces,
        and global app modules for the 'default' workspace.
        """
        if self.modulesPath:
            return os.path.normpath(self.modulesPath)
        
        # If no workspace or 'default' workspace: use global modules
        if not appState.currentWorkspace or appState.currentWorkspace.lower() == "default":
            return RIG_BUILDER_MODULES_PATH
        
        # Otherwise: use local workspace modules
        wsPath = appState.getCurrentWorkspacePath()
        if wsPath:
            return os.path.normpath(os.path.join(wsPath, "modules"))
            
        return RIG_BUILDER_MODULES_PATH


    def getHistoryPath(self) -> str:
        """Return the history directory for module version history (git-tracked)."""
        if self.historyPath:
            return os.path.normpath(self.historyPath)
            
        # Fallback to current workspace history if active
        wsPath = appState.getCurrentWorkspacePath()
        if wsPath:
            return os.path.normpath(os.path.join(wsPath, "history"))

        # Default fallback inside workspaces tree
        return os.path.normpath(os.path.join(RIG_BUILDER_WORKSPACES_PATH, "default", "history"))

class AppState(BaseConfig):
    """Container for volatile machine-specific state."""
    def __init__(self):
        self.currentWorkspace = ""

    def getCurrentWorkspacePath(self) -> str:
        """Resolve the current workspace name to a full absolute path."""
        if not self.currentWorkspace:
            return ""
        return os.path.normpath(os.path.join(RIG_BUILDER_WORKSPACES_PATH, self.currentWorkspace))

    def load(self):
        """Load state from default or specified path."""
        super().load(STATE_PATH)

    def save(self):
        """Save state to default or specified path."""
        super().save(STATE_PATH)

# Global instances for application-wide access
settings = Settings()

appState = AppState()
appState.load()
