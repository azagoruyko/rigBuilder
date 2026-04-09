import html
import os
import xml.etree.ElementTree as ET
import shutil
from typing import List, Protocol, Optional

from ..qt import *
from ..core import Module, RIG_BUILDER_USER_PATH, Settings, getModulesPath, UidManager, getWorkspacesPath, getHistoryPath
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


def migrateLegacyData():
    """Migrate legacy history and workspace.xml from RIG_BUILDER_USER_PATH root to the NEW workspaces/default structure."""
    defaultWorkspaceDir = os.path.join(getWorkspacesPath(), "default")

    if os.path.exists(defaultWorkspaceDir):
        return
    
    # Map legacy paths to new workspace paths
    mapping = {
        os.path.join(RIG_BUILDER_USER_PATH, "history"): os.path.join(defaultWorkspaceDir, "history"),
        os.path.join(RIG_BUILDER_USER_PATH, "workspace.xml"): os.path.join(defaultWorkspaceDir, "workspace.rbws")
    }
    
    os.makedirs(defaultWorkspaceDir, exist_ok=True)
    print(f"Migration: detected legacy data at {RIG_BUILDER_USER_PATH}. Migrating to default workspace...")

    for src, dst in mapping.items():
        if not os.path.exists(src) or os.path.exists(dst):
            print(f"Migration: skipping {os.path.basename(src)}: {os.path.basename(dst)} already exists.")
            continue

        try:
            shutil.move(src, dst)
        except Exception as e:
            print(f"Migration: failed to move {os.path.basename(src)}: {e}")    
    
    print("Migration: complete.")


class Workspace:
    def __init__(self, folderPath: str = "", modulesPath: str = ""):            
        self.folderPath = os.path.normpath(folderPath) if folderPath else ""
        self.modulesPath = modulesPath
        self.modules: List[Module] = []
        self.expanded: List[bool] = []
        self.host: str = ""

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
            f'<modulesPath value="{html.escape(self.modulesPath or "", quote=True)}"/>',
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

        lines.append("</workspace>")

        os.makedirs(self.folderPath, exist_ok=True)
        with open(self.path(), "w", encoding="utf-8") as f:
            f.write("\n".join(lines))

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

        # Settings
        el = root.find("modulesPath")
        if el is not None:
            workspace.modulesPath = el.attrib.get("value", "")

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

        return workspace

    def activate(self) -> bool:
        """Core activation: update history path and global settings."""
        if not self.folderPath:
            return False

        # 1. Update Settings paths
        Settings["currentWorkspace"] = self.folderPath
        Settings["historyPath"] = self.historyPath()
        
        # If modulesPath is empty, it means we use the global default (e.g. for "default" workspace)
        # However, if it's NOT the default and modulesPath was never set, we might want to default to local.
        # But usually, it's set during create().
        Settings["modulesPath"] = self.modulesPath
        
        # 2. Ensure directories and repos exist
        os.makedirs(self.historyPath(), exist_ok=True)
        if self.modulesPath and os.path.abspath(self.modulesPath) == os.path.abspath(self.modulesLocalPath()):
             os.makedirs(self.modulesLocalPath(), exist_ok=True)

        repo = GitRepo(self.historyPath())
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
        root = getWorkspacesPath()
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

    @staticmethod
    def create(folderPath: str = "") -> 'Workspace':
        """Initialize a new workspace folder structure. If folderPath is empty, the default is created."""
        if not folderPath:
            folderPath = os.path.join(RIG_BUILDER_USER_PATH, "workspaces", "default")
            isDefault = True
        else:
            isDefault = os.path.abspath(folderPath) == os.path.abspath(os.path.join(RIG_BUILDER_USER_PATH, "workspaces", "default"))

        folderPath = os.path.normpath(folderPath)
        os.makedirs(folderPath, exist_ok=True)
        
        ws = Workspace(folderPath=folderPath)
        
        if isDefault:
            # Default workspace points to global modules
            ws.modulesPath = "" 
        else:
            # New workspaces point to their local modules folder
            ws.modulesPath = ws.modulesLocalPath()
            os.makedirs(ws.modulesPath, exist_ok=True)
            
        os.makedirs(ws.historyPath(), exist_ok=True)
        ws.save()
        return ws


class WorkspaceManagerDialog(QDialog):
    """Dialog for listing, creating, and removing workspaces."""
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Workspace Manager")
        self.setMinimumSize(400, 300)

        self.listWidget = QListWidget()
        self.listWidget.itemDoubleClicked.connect(self.accept)

        self.newBtn = QPushButton("✨ New Workspace")
        self.newBtn.clicked.connect(self._onNew)

        self.removeBtn = QPushButton("🗑️ Remove Selected")
        self.removeBtn.clicked.connect(self._onRemove)

        self.openBtn = QPushButton("📁 Open Folder")
        self.openBtn.clicked.connect(self._onOpenFolder)

        btnLayout = QHBoxLayout()
        btnLayout.addWidget(self.newBtn)
        btnLayout.addWidget(self.removeBtn)
        btnLayout.addWidget(self.openBtn)

        layout = QVBoxLayout()
        layout.addWidget(QLabel("Available Workspaces:"))
        layout.addWidget(self.listWidget)
        layout.addLayout(btnLayout)
        
        self.setLayout(layout)
        
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

        name = replaceSpecialChars(name)
        path = os.path.join(getWorkspacesPath(), name)
        
        if os.path.exists(path):
            QMessageBox.warning(self, "Workspace Manager", f"Workspace '{name}' already exists.")
            return

        Workspace.create(path)
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
        ws.modulesPath = Settings.get("modulesPath", "")
        
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
        """Retrieve and activate the last used workspace on startup."""
        self.refreshWorkspaces()

        lastPath = Settings.get("currentWorkspace", "")
        
        workspace = None
        if lastPath:
            workspace = Workspace.load(lastPath)
            
        if not workspace:
            # Fallback to a default workspace in the user directory
            workspace = Workspace.create()

        workspace.activate()
        
        # Update UI components that depend on settings
        self.mainWindow.moduleBrowser.modulesAutoReloadWatcher.setRoots([getModulesPath()])
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
            self.mainWindow.moduleBrowser.modulesAutoReloadWatcher.setRoots([getModulesPath()])
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

migrateLegacyData()