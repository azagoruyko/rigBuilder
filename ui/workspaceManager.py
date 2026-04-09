import html
import os
import xml.etree.ElementTree as ET
import shutil
from typing import List, Protocol, Optional

from ..qt import *
from ..settings import (
    settings, 
    appState, 
    RIG_BUILDER_USER_PATH, 
    RIG_BUILDER_PATH,
    RIG_BUILDER_WORKSPACES_PATH,
    Settings,
    AppState
)
from ..core import Module, UidManager
from ..gitrepo import GitRepo
from ..utils import replaceSpecialChars

class WorkspaceMainWindow(Protocol):
    """Protocol for the main window passed to UI sync methods. Avoids depending on ui (circular import)."""
    treeWidget: object
    logger: object
    hostCombo: object
    connectionManager: object
    moduleBrowser: object


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
    def __init__(self, folderPath: str = ""):            
        self.folderPath = os.path.normpath(folderPath) if folderPath else ""
        
        self.modules: List[Module] = []
        self.expanded: List[bool] = []
        self.host: str = ""
        self.modulesPath: str = ""

    @property
    def name(self) -> str:
        """Derive workspace name from its folder path."""
        if not self.folderPath:
            return "Unsaved Workspace"
        return os.path.basename(self.folderPath)

    def path(self) -> str:
        """Return the absolute path to the workspace.rbws file."""
        if not self.folderPath:
            return ""
        return os.path.join(self.folderPath, "workspace.rbws")

    def settingsPath(self) -> str:
        """Return the absolute path to the workspace settings.json file."""
        if not self.folderPath:
            return ""
        return os.path.join(self.folderPath, "settings.json")

    def historyPath(self) -> str:
        """Return the absolute path to the local history directory."""
        if not self.folderPath:
            return ""
        return os.path.join(self.folderPath, "history")

    def modulesLocalPath(self) -> str:
        """Return the absolute path to the local modules directory."""
        if not self.folderPath:
            return ""
        return os.path.join(self.folderPath, "modules")

    def save(self) -> None:
        """Save workspace state to its .rbws file inside its folder."""
        if not self.folderPath:
            return

        # Ensure directory exists but NOT the subfolders (those are created on activate/create)
        os.makedirs(self.folderPath, exist_ok=True)

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

        if self.host:
            lines.append('<host name="{}"/>'.format(html.escape(self.host, quote=True)))

        if self.modulesPath:
            lines.append('<modulesPath value="{}"/>'.format(html.escape(self.modulesPath, quote=True)))

        lines.append("</workspace>")

        os.makedirs(self.folderPath, exist_ok=True)
        with open(self.path(), "w", encoding="utf-8") as f:
            f.write("\n".join(lines))
        
        # Save settings to its own JSON file
        settings.save(self.settingsPath())

    @classmethod
    def load(cls, folderPath: str) -> Optional['Workspace']:
        """Load workspace data from a folder containing workspace.rbws."""
        folderPath = os.path.normpath(folderPath)
        rbwsPath = os.path.join(folderPath, "workspace.rbws")
        
        if not os.path.exists(rbwsPath):
            return None

        try:
            tree = ET.parse(rbwsPath)
            root = tree.getroot()
        except ET.ParseError as e:
            print(f"Cannot parse workspace: {e}")
            return None

        workspace = cls(folderPath=folderPath)

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

        # Host
        hostEl = root.find("host")
        if hostEl is not None:
            workspace.host = hostEl.attrib.get("name", "")

        # Modules Path
        modulesPathEl = root.find("modulesPath")
        if modulesPathEl is not None:
            workspace.modulesPath = modulesPathEl.attrib.get("value", "")

        return workspace

    def activate(self) -> bool:
        """Core activation: populate runtime Settings from this workspace."""
        if not self.folderPath:
            return False

        # 1. Update Runtime Settings (Merge order: Code defaults -> Workspace JSON)
        # Start fresh from code defaults by creating an empty Settings object and merging
        defaults = Settings()
        settings.update(defaults.toDict())
        
        # Load workspace-specific overrides
        settings.load(self.settingsPath())
        
        appState.currentWorkspace = os.path.basename(os.path.normpath(self.folderPath))
        appState.save()
        
        # 2. Ensure directories and repos exist
        historyPath = settings.getHistoryPath()
        os.makedirs(historyPath, exist_ok=True)
        # Ensure modules directory exists if it's pointing to the local workspace folder
        activeModulesPath = settings.getModulesPath()
        if os.path.abspath(activeModulesPath) == os.path.abspath(self.modulesLocalPath()):
             os.makedirs(self.modulesLocalPath(), exist_ok=True)

        repo = GitRepo(historyPath)
        repo.init()
        
        # 3. Refresh UID Manager
        UidManager.update()
        
        return True

    def delete(self) -> bool:
        """Delete the entire workspace folder."""
        if not self.folderPath or not os.path.exists(self.folderPath):
            return False

        try:
            shutil.rmtree(self.folderPath)
            return True
        except Exception as e:
            print(f"Failed to delete workspace folder: {e}")
            return False
    @classmethod
    def list(cls) -> List['Workspace']:
        """List all available workspaces in the standard directory."""
        root = RIG_BUILDER_WORKSPACES_PATH
        if not os.path.exists(root):
            return []

        workspaces = []
        for d in os.listdir(root):
            dirPath = os.path.join(root, d)
            if os.path.isdir(dirPath):
                ws = cls.load(dirPath)
                if ws:
                    workspaces.append(ws)
        
        return sorted(workspaces, key=lambda x: x.name.lower())

    @classmethod
    def create(cls, name: str = "default", parentDir: str = "") -> 'Workspace':
        """Create a new workspace directory structure."""
        if not parentDir:
            parentDir = os.path.join(RIG_BUILDER_USER_PATH, "workspaces")
            
        folderPath = os.path.join(parentDir, replaceSpecialChars(name))
        os.makedirs(folderPath, exist_ok=True)
        
        ws = cls(folderPath)
        
        # Ensure directories and repos exist
        os.makedirs(ws.historyPath(), exist_ok=True)
        
        # Initialize local settings.json
        # Inherit from 'default' workspace if this is not the default workspace itself
        defaultWsSettings = os.path.join(RIG_BUILDER_USER_PATH, "workspaces", "default", "settings.json")
        if name != "default" and os.path.exists(defaultWsSettings):
            template = Settings()
            template.load(defaultWsSettings)
            template.save(ws.settingsPath())
        else:
            # First time for default, or no default yet: use current live settings (defaults)
            settings.save(ws.settingsPath())
        
        ws.save()
        return ws


class WorkspaceManagerDialog(QDialog):
    """Dialog for listing, creating, and removing workspaces."""
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Workspace Manager")
        self.setMinimumSize(700, 400)

        # 1. Left Panel (Workspace List)
        self.listWidget = QListWidget()
        self.listWidget.itemDoubleClicked.connect(self.accept)

        self.newBtn = QPushButton("➕")
        self.newBtn.setAutoDefault(False)
        self.newBtn.clicked.connect(self._onNew)

        self.removeBtn = QPushButton("🗑️")
        self.removeBtn.setAutoDefault(False)
        self.removeBtn.clicked.connect(self._onRemove)

        self.openBtn = QPushButton("📁")
        self.openBtn.setAutoDefault(False)
        self.openBtn.clicked.connect(self._onOpenFolder)

        btnLayout = QHBoxLayout()
        btnLayout.addWidget(self.newBtn)
        btnLayout.addWidget(self.removeBtn)
        btnLayout.addWidget(self.openBtn)

        listPanel = QWidget()
        listLayout = QVBoxLayout(listPanel)
        listLayout.setContentsMargins(0, 0, 0, 0)
        listLayout.addWidget(QLabel("Available Workspaces:"))
        listLayout.addWidget(self.listWidget)
        listLayout.addLayout(btnLayout)

        # 2. Right Panel (Settings)
        self.settingsGroup = QGroupBox("Workspace Settings")
        self.settingsGroup.setEnabled(False)
        self.settingsLayout = QFormLayout(self.settingsGroup)

        self.modulesPathEdit = QLineEdit()
        self.modulesPathEdit.setPlaceholderText("Path to modules folder (optional)...")
        self.modulesPathEdit.setToolTip("Directory where workspace-specific modules are stored.\nIf empty, global modules are used.")
        self.modulesPathEdit.editingFinished.connect(lambda: self._onSettingChanged("modulesPath", self.modulesPathEdit.text()))
        modulesPathLayout = QHBoxLayout()
        modulesPathLayout.addWidget(self.modulesPathEdit)
        self.modulesPathBrowseBtn = QPushButton("...")
        self.modulesPathBrowseBtn.setAutoDefault(False)
        self.modulesPathBrowseBtn.setToolTip("Browse for modules directory.")
        self.modulesPathBrowseBtn.clicked.connect(self._onBrowseModulesPath)
        modulesPathLayout.addWidget(self.modulesPathBrowseBtn)
        self.settingsLayout.addRow("Modules Path:", modulesPathLayout)

        self.vscodeEdit = QLineEdit()
        self.vscodeEdit.setPlaceholderText("e.g., code/cursor/antigravity")
        self.vscodeEdit.setToolTip("Application or command used to open the workspace in VSCode.")
        self.vscodeEdit.editingFinished.connect(lambda: self._onSettingChanged("vscode", self.vscodeEdit.text()))
        self.settingsLayout.addRow("VSCode Command/Path:", self.vscodeEdit)

        self.trackHistoryCheck = QCheckBox("Track History")
        self.trackHistoryCheck.setToolTip("Enable/Disable local Git history tracking for this workspace.")
        self.trackHistoryCheck.toggled.connect(lambda checked: self._onSettingChanged("trackHistory", checked))
        self.settingsLayout.addRow("", self.trackHistoryCheck)

        self.aiLanguageEdit = QLineEdit()
        self.aiLanguageEdit.setPlaceholderText("e.g., English, Russian...")
        self.aiLanguageEdit.setToolTip("Language used for AI code generation and documentation.")
        self.aiLanguageEdit.editingFinished.connect(lambda: self._onSettingChanged("aiLanguage", self.aiLanguageEdit.text()))
        self.settingsLayout.addRow("AI Language:", self.aiLanguageEdit)

        self.ollamaModelEdit = QLineEdit()
        self.ollamaModelEdit.setPlaceholderText("e.g., gpt-oss:20b-cloud")
        self.ollamaModelEdit.setToolTip("The model identifier used for Ollama AI responses.")
        self.ollamaModelEdit.editingFinished.connect(lambda: self._onSettingChanged("ollamaModel", self.ollamaModelEdit.text()))
        self.settingsLayout.addRow("Ollama Model:", self.ollamaModelEdit)

        # 3. Main Layout
        self.splitter = QSplitter(Qt.Horizontal)
        self.splitter.addWidget(listPanel)
        self.splitter.addWidget(self.settingsGroup)
        self.splitter.setStretchFactor(0, 1)
        self.splitter.setStretchFactor(1, 2)
        
        layout = QVBoxLayout(self)
        layout.addWidget(self.splitter)
        
        self.listWidget.itemSelectionChanged.connect(self._onSelectionChanged)
        self.refresh()

    def _onSelectionChanged(self):
        ws = self.selectedWorkspace()
        if ws and ws.name.lower() == "default":
            self.removeBtn.setEnabled(False)
            self.removeBtn.setToolTip("Cannot remove the default workspace.")
        else:
            self.removeBtn.setEnabled(True)
            self.removeBtn.setToolTip("Completely remove selected workspace folder.")
        
        self._refreshSettings(ws)

    def _refreshSettings(self, ws: Optional[Workspace]):
        if not ws:
            self.settingsGroup.setEnabled(False)
            self.settingsGroup.setTitle("Workspace Settings")
            return

        self.settingsGroup.setEnabled(True)
        self.settingsGroup.setTitle(f"Settings: {ws.name}")
        
        # Load workspace specific settings
        ws_settings = Settings()
        ws_settings.load(ws.settingsPath())

        self._blockSettingsSignals = True
        self.modulesPathEdit.setText(ws_settings.modulesPath)
        self.vscodeEdit.setText(ws_settings.vscode)
        self.trackHistoryCheck.setChecked(ws_settings.trackHistory)
        self.aiLanguageEdit.setText(ws_settings.aiLanguage)
        self.ollamaModelEdit.setText(ws_settings.ollamaModel)
        self._blockSettingsSignals = False

    def _onSettingChanged(self, key, value):
        if getattr(self, "_blockSettingsSignals", False):
            return

        ws = self.selectedWorkspace()
        if not ws:
            return

        # Load, Update, Save
        ws_settings = Settings()
        ws_settings.load(ws.settingsPath())
        if hasattr(ws_settings, key):
            setattr(ws_settings, key, value)
        ws_settings.save(ws.settingsPath())

        # If this is the active workspace, update the live settings object too
        activePath = settings.getCurrentWorkspacePath()
        if activePath and os.path.abspath(ws.folderPath) == os.path.abspath(activePath):
            if hasattr(settings, key):
                setattr(settings, key, value)
            print(f"Updated active workspace setting '{key}' to '{value}'")
        else:
            print(f"Updated workspace '{ws.name}' setting '{key}' to '{value}'")

    def _onBrowseModulesPath(self):
        ws = self.selectedWorkspace()
        if not ws:
            return
            
        startDir = self.modulesPathEdit.text() or ws.folderPath or RIG_BUILDER_PATH
        path = QFileDialog.getExistingDirectory(self, "Select Modules Directory", startDir)
        if path:
            self.modulesPathEdit.setText(path)
            self._onSettingChanged("modulesPath", path)

    def refresh(self):
        self.listWidget.clear()
        for ws in Workspace.list():
            item = QListWidgetItem(f"💼 {ws.name} workspace")
            item.setData(Qt.UserRole, ws.folderPath)
            self.listWidget.addItem(item)

    def selectedWorkspace(self) -> Optional[Workspace]:
        item = self.listWidget.currentItem()
        if not item:
            return None
        return Workspace.load(item.data(Qt.UserRole))

    def _onNew(self):
        name, ok = QInputDialog.getText(self, "New Workspace", "Workspace Name:")
        if not ok or not name:
            return

        name = name.strip()
        name = replaceSpecialChars(name)
        path = os.path.join(RIG_BUILDER_WORKSPACES_PATH, name)

        if not name or os.path.exists(path):
            QMessageBox.warning(self, "Workspace Manager", f"Workspace '{name}' already exists.")
            return

        Workspace.create(name)
        self.refresh()

    def _onRemove(self):
        ws = self.selectedWorkspace()
        if not ws:
            return

        if ws.name.lower() == "default":
            QMessageBox.warning(self, "Workspace Manager", "Cannot remove the default workspace.")
            return

        res = QMessageBox.question(self, "Workspace Manager", 
                                   f"Are you sure you want to COMPLETELY remove workspace '{ws.name}'?\n\nThis will delete the folder and all its history.",
                                   QMessageBox.Yes | QMessageBox.No)
        if res != QMessageBox.Yes:
            return

        if ws.delete():
            self.refresh()

    def _onOpenFolder(self):
        ws = self.selectedWorkspace()
        if ws and os.path.exists(ws.folderPath):
            os.startfile(ws.folderPath)


class WorkspaceWidget(QWidget):
    """UI Widget for workspace selection and management."""
    workspaceChanged = Signal(object) # Workspace

    def __init__(self, mainWindow: WorkspaceMainWindow, parent=None):
        super().__init__(parent)
        self.mainWindow = mainWindow
        self._currentWorkspace = None
        self._blockSignals = False

        self.combo = QComboBox()
        self.combo.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.combo.currentIndexChanged.connect(self._onComboChanged)

        self.manageBtn = QPushButton("⚙️")
        self.manageBtn.clicked.connect(self._onManage)

        layout = QHBoxLayout()
        layout.setContentsMargins(0, 0, 0, 2)
        layout.setSpacing(4)
        layout.addWidget(self.combo)
        layout.addWidget(self.manageBtn)
        self.setLayout(layout)

    def toWorkspace(self) -> Workspace:
        """Capture current UI state into a Workspace object."""
        # Use existing if we have one, otherwise create new
        ws = self._currentWorkspace or Workspace()
        
        # Scrape modules
        tree = self.mainWindow.treeWidget
        rootModules = tree.moduleModel.rootModule().children()
        allModules = flattenModules(rootModules)
        
        ws.modules = rootModules
        ws.expanded = [bool(tree.isExpanded(tree.moduleModel.indexForModule(m))) for m in allModules]
        ws.host = self.mainWindow.hostCombo.currentData() or ""
        
        return ws

    def fromWorkspace(self, workspace: Workspace):
        """Populate UI from the Workspace object's data."""
        self._currentWorkspace = workspace
        
        # Sync combo box without triggering signals
        self._blockSignals = True
        idx = self.combo.findData(workspace.folderPath)
        if idx >= 0:
            self.combo.setCurrentIndex(idx)
        else:
            # If not in list (e.g. external load), add it temporarily?
            # Or just refresh list
            self.refreshWorkspaces()
            idx = self.combo.findData(workspace.folderPath)
            if idx >= 0:
                self.combo.setCurrentIndex(idx)
        self._blockSignals = False

        # Clear current tree
        self.mainWindow.treeWidget.clear()

        # Add modules
        for module in workspace.modules:
            self.mainWindow.treeWidget.moduleModel.addModuleAt(module)

        # Restore expansion
        if workspace.expanded:
            rootModules = self.mainWindow.treeWidget.moduleModel.rootModule().children()
            allModules = flattenModules(rootModules)
            for m, isExpanded in zip(allModules, workspace.expanded):
                if isExpanded:
                    idx = self.mainWindow.treeWidget.moduleModel.indexForModule(m)
                    if idx.isValid():
                        self.mainWindow.treeWidget.setExpanded(idx, True)

        # Host combo
        if workspace.host:
            # Safety: disconnect if host mismatches
            try:
                from ..client.connectionManager import connectionManager
                activeHost = connectionManager.activeServerName()
                if activeHost and workspace.host != activeHost:
                    if connectionManager.activeConnection():
                        connectionManager.disconnect()
                        self.mainWindow._resetHostConnectionRow()
            except ImportError:
                pass

            idx = self.mainWindow.hostCombo.findData(workspace.host)
            if idx >= 0:
                self.mainWindow.hostCombo.setCurrentIndex(idx)

    def currentWorkspace(self) -> Optional[Workspace]:
        return self._currentWorkspace

    def setCurrentWorkspace(self, workspace: Workspace):
        self._currentWorkspace = workspace
        self.fromWorkspace(workspace)

    def refreshWorkspaces(self):
        """Update the combo box from disk."""
        self._blockSignals = True
        self.combo.clear()
        workspaces = Workspace.list()
        for ws in workspaces:
            self.combo.addItem(f"💼 {ws.name} workspace", ws.folderPath)
        
        if self._currentWorkspace:
            idx = self.combo.findData(self._currentWorkspace.folderPath)
            if idx >= 0:
                self.combo.setCurrentIndex(idx)
        self._blockSignals = False

    def initialize(self) -> Workspace:
        """Restore workspace state on startup."""
        self.refreshWorkspaces()
        appState.load()
        lastPath = settings.getCurrentWorkspacePath()
        
        workspace = None
        if lastPath:
            workspace = Workspace.load(lastPath)
            
        if not workspace:
            # Fallback to a default workspace in the user directory
            workspace = Workspace.create()

        workspace.activate()
        
        # Update UI components that depend on settings
        self.mainWindow.moduleBrowser.modulesAutoReloadWatcher.setRoots([settings.getModulesPath()])
        self.mainWindow.moduleBrowser.refreshModules()
        
        self.fromWorkspace(workspace)
        return workspace

    def _onComboChanged(self, index: int):
        if self._blockSignals:
            return

        folderPath = self.combo.itemData(index)
        if not folderPath:
            return

        # Auto-save current
        if self._currentWorkspace:
            self.toWorkspace().save()

        workspace = Workspace.load(folderPath)
        if workspace:
            workspace.activate()
            # UI Refresh
            self.mainWindow.moduleBrowser.modulesAutoReloadWatcher.setRoots([settings.getModulesPath()])
            self.mainWindow.moduleBrowser.refreshModules()
            self.fromWorkspace(workspace)
            self.workspaceChanged.emit(workspace)

    def _onManage(self):
        dialog = WorkspaceManagerDialog(self)
        if dialog.exec_():
            sel = dialog.selectedWorkspace()
            if sel:
                self.refreshWorkspaces()
                # Find and select
                idx = self.combo.findData(sel.folderPath)
                if idx >= 0:
                    self.combo.setCurrentIndex(idx) # This triggers _onComboChanged
        else:
            # Just refresh list in case something was removed
            self.refreshWorkspaces()

    def _onSaveWorkspace(self):
        """Overwrite current workspace."""
        if self._currentWorkspace and self._currentWorkspace.folderPath:
            ws = self.toWorkspace()
            ws.save()
            print(f"Workspace '{ws.name}' saved")
