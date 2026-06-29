import os
import json
import logging
from .utils import loadJson, saveJson

RIG_BUILDER_PATH = os.path.normpath(os.path.dirname(os.path.dirname(__file__)))
RIG_BUILDER_USER_PATH = os.path.normpath(os.path.join(os.path.expanduser("~"), "rigBuilder"))

SETTINGS_PATH = os.path.join(RIG_BUILDER_USER_PATH, "settings.json")
HOSTS_FILE = os.path.join(RIG_BUILDER_USER_PATH, "hosts.json")
RIG_BUILDER_WORKSPACES_PATH = os.path.join(RIG_BUILDER_USER_PATH, "workspaces")

DEFAULT_DISCOVERY_PORT = 51605
MODULE_EXT = ".rb" # default extension for new/saved modules
MODULE_EXTS = (MODULE_EXT, ".xml")  # accepted extensions (xml for backward compat)

HEARTBEAT_INTERVAL_SEC = 2.0
REGISTRATION_INTERVAL_SEC = 5.0

MODULE_EXECUTION_TIMEOUT = 86400 # 24 hours
CODE_EXECUTION_TIMEOUT = 60 # 60 seconds

logger = logging.getLogger('rigBuilder')

class Settings:
    """Unified application settings with support for workspace overrides."""

    def __init__(self):
        self.vscode = "code"
        self.trackHistory = True
        self.ollamaModel = "gpt-oss:20b-cloud"
        self.ollamaEmbeddingModel = "nomic-embed-text"
        self.aiLanguage = "English"
        self.workspacePath = os.path.join(RIG_BUILDER_WORKSPACES_PATH, "default")
        self.modulesPath = os.path.join(RIG_BUILDER_PATH, "modules")
        self.historyPath = os.path.join(self.workspacePath, "history")
        self.scriptsPath = os.path.join(self.workspacePath, "scripts")
        self.autoSaveInterval = 15 # minutes

    def toDict(self) -> dict:
        """Return a dictionary of current attributes (for saving global base)."""
        return {k: v for k, v in self.__dict__.items() if not k.startswith("_")}

    def fromDict(self, data: dict):
        """Update attributes from a dictionary."""
        for k, v in data.items():
            if hasattr(self, k):
                setattr(self, k, v)

    def load(self, path: str):
        """Load global settings from the base file."""
        try:
            data = loadJson(path)
            self.fromDict(data)
        except Exception as e:
            logger.error(f"Failed to load settings from {path}: {e}")

    def save(self, path: str):
        """Save global settings to the base file."""
        os.makedirs(os.path.dirname(path), exist_ok=True)
        try:
            saveJson(path, self.toDict())
        except Exception as e:
            logger.error(f"Failed to save settings to {path}: {e}")


# Global singleton
settings = Settings()
