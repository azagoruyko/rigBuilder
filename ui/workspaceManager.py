from __future__ import annotations
import os
from datetime import datetime
from functools import partial
from typing import List, Protocol, Optional

from ..qt import *
from ..settings import (
    settings, 
    RIG_BUILDER_USER_PATH, 
    RIG_BUILDER_PATH,
    RIG_BUILDER_WORKSPACES_PATH
)
from ..workspace import Workspace, flattenModules
from ..utils import replaceSpecialChars
from ..client.connectionManager import connectionManager

class WorkspaceMainWindow(Protocol):
    """Protocol for the main window passed to UI sync methods. Avoids depending on ui (circular import)."""
    treeWidget: object
    logger: object
    hostCombo: object
    moduleBrowser: object
    
    def switchWorkspace(self, folderPath: str): ...
    def _refreshModuleBrowserSource(self): ...

class WorkspaceManagerDialog(QDialog):
    """Dialog for listing, creating, and removing workspaces."""
    def __init__(self, currentWorkspaceName: str, parent=None):
        super().__init__(parent)
        self.currentWorkspaceName = currentWorkspaceName
        self.setWindowTitle("Workspace Manager")
        self.setMinimumSize(700, 400)
        
        self._blockSettingsSignals = False

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
        self.modulesPathEdit.setPlaceholderText("Path to modules folder...")
        self.modulesPathEdit.editingFinished.connect(partial(self._onLineEditChanged, "modulesPath", self.modulesPathEdit))
        
        modulesPathLayout = QHBoxLayout()
        modulesPathLayout.addWidget(self.modulesPathEdit)

        self.modulesPathBrowseBtn = QPushButton("...")
        self.modulesPathBrowseBtn.setAutoDefault(False)
        self.modulesPathBrowseBtn.clicked.connect(self._onBrowseModulesPath)

        modulesPathLayout.addWidget(self.modulesPathBrowseBtn)
        self.settingsLayout.addRow("Modules Path:", modulesPathLayout)

        self.vscodeEdit = QLineEdit()
        self.vscodeEdit.editingFinished.connect(partial(self._onLineEditChanged, "vscode", self.vscodeEdit))
        self.settingsLayout.addRow("VSCode Command:", self.vscodeEdit)

        self.trackHistoryCheck = QCheckBox("Track History")
        self.trackHistoryCheck.toggled.connect(partial(self._onSettingChanged, "trackHistory"))
        self.settingsLayout.addRow("", self.trackHistoryCheck)

        self.aiLanguageEdit = QLineEdit()
        self.aiLanguageEdit.editingFinished.connect(partial(self._onLineEditChanged, "aiLanguage", self.aiLanguageEdit))
        self.settingsLayout.addRow("AI Language:", self.aiLanguageEdit)

        self.ollamaModelEdit = QLineEdit()
        self.ollamaModelEdit.editingFinished.connect(partial(self._onLineEditChanged, "ollamaModel", self.ollamaModelEdit))
        self.settingsLayout.addRow("Ollama Model:", self.ollamaModelEdit)

        self.autoSaveIntervalSpin = QSpinBox()
        self.autoSaveIntervalSpin.setRange(1, 60)
        self.autoSaveIntervalSpin.setSuffix(" min")
        self.autoSaveIntervalSpin.valueChanged.connect(partial(self._onSettingChanged, "autoSaveInterval"))
        self.settingsLayout.addRow("Auto-save Interval:", self.autoSaveIntervalSpin)

        self.hostCombo = QComboBox()
        self.hostCombo.currentIndexChanged.connect(partial(self._onComboChanged, "host", self.hostCombo))
        self.settingsLayout.addRow("Host:", self.hostCombo)

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
        self.removeBtn.setEnabled(ws is not None and ws.name.lower() != "default")
        self._refreshSettings(ws)

    def _refreshSettings(self, ws: Workspace):
        if not ws:
            self.settingsGroup.setEnabled(False)
            self.settingsGroup.setTitle("Workspace Settings")
            return

        self.settingsGroup.setEnabled(True)
        self.settingsGroup.setTitle(f"Settings: {ws.name}")
        
        self._blockSettingsSignals = True
        self.modulesPathEdit.setText(ws.settings.modulesPath)
        self.vscodeEdit.setText(ws.settings.vscode)
        self.trackHistoryCheck.setChecked(ws.settings.trackHistory)
        self.aiLanguageEdit.setText(ws.settings.aiLanguage)
        self.ollamaModelEdit.setText(ws.settings.ollamaModel)
        self.autoSaveIntervalSpin.setValue(ws.settings.autoSaveInterval)

        # Populate and set Default Host
        self.hostCombo.clear()
        entries = sorted(connectionManager.servers().items(), key=lambda x: x[0].lower())
        for name, entry in entries:
            label = "🖥️ {} ({})".format(name, entry["host"])
            self.hostCombo.addItem(label, userData=name)
        
        idx = self.hostCombo.findData(ws.settings.host)
        if idx >= 0:
            self.hostCombo.setCurrentIndex(idx)

        self._blockSettingsSignals = False

    def _onSettingChanged(self, key, value):
        if self._blockSettingsSignals:
            return

        ws = self.selectedWorkspace()
        if not ws:
            return

        if hasattr(ws.settings, key):
            setattr(ws.settings, key, value)
            ws.save() # Workspace.save saves both workspace file and settings.json
            
            # If this is the active workspace, sync global settings immediately
            if self.currentWorkspaceName == ws.name:
                settings.fromDict(ws.settings.toDict())
                self.parent().mainWindow._refreshHostCombo()
                self.parent()._refreshModuleBrowserSource()
                self.parent()._updateAutoSaveInterval()

    def _onLineEditChanged(self, key, edit):
        self._onSettingChanged(key, edit.text())

    def _onComboChanged(self, key, combo, _idx):
        self._onSettingChanged(key, combo.currentData())

    def _onBrowseModulesPath(self):
        ws = self.selectedWorkspace()
        if not ws:
            return
            
        startDir = self.modulesPathEdit.text() or ws.folderPath() or RIG_BUILDER_PATH
        path = QFileDialog.getExistingDirectory(self, "Select Modules Directory", startDir)
        if path:
            self.modulesPathEdit.setText(path)
            self._onSettingChanged("modulesPath", path)

    def refresh(self):
        self.listWidget.clear()

        for ws in Workspace.list():
            item = QListWidgetItem(f"💼 {ws.name}")
            item.setData(Qt.UserRole, ws.name)
            self.listWidget.addItem(item)
            
            if ws.name == self.currentWorkspaceName:
                self.listWidget.setCurrentItem(item)

    def selectedWorkspace(self) -> Optional[Workspace]:
        item = self.listWidget.currentItem()
        if not item:
            return None
        return Workspace.load(item.data(Qt.UserRole))

    def _onNew(self):
        name, ok = QInputDialog.getText(self, "New Workspace", "Workspace Name:")
        if not ok or not name:
            return

        name = replaceSpecialChars(name.strip())
        if not name:
            return

        if Workspace.exists(name):
            QMessageBox.warning(self, "Workspace Manager", f"Workspace '{name}' already exists.")
            return

        Workspace.create(name)
        self.refresh()

    def _onRemove(self):
        ws = self.selectedWorkspace()
        if not ws or ws.name.lower() == "default":
            return

        res = QMessageBox.question(self, "Workspace Manager", 
                                   f"Are you sure you want to remove workspace '{ws.name}'?",
                                   QMessageBox.Yes | QMessageBox.No)
        if res != QMessageBox.Yes:
            return

        if ws.name == self.currentWorkspaceName:
            self.parent().switchWorkspace("default")

        if ws.delete():
            self.refresh()

    def _onOpenFolder(self):
        ws = self.selectedWorkspace()
        if ws and os.path.exists(ws.folderPath()):
            os.startfile(ws.folderPath())

class WorkspaceWidget(QWidget):
    """UI Widget for workspace selection and management."""
    workspaceChanged = Signal(object) # Workspace

    def __init__(self, mainWindow: WorkspaceMainWindow, parent=None):
        super().__init__(parent)
        self.mainWindow = mainWindow
        self._blockSignals = False
        self._currentWorkspaceName = ""

        self.combo = QComboBox()
        self.combo.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.combo.currentIndexChanged.connect(self._onComboChanged)

        self.manageBtn = QPushButton("⚙️")
        self.manageBtn.setToolTip("Manage Workspaces")
        self.manageBtn.clicked.connect(self._onManage)

        layout = QHBoxLayout()
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)
        layout.addWidget(self.combo)
        layout.addWidget(self.manageBtn)
        self.setLayout(layout)

        self.autoSaveTimer = QTimer(self)
        self.autoSaveTimer.timeout.connect(self._onAutoSaveTimer)
        self._updateAutoSaveInterval()

        self.refreshWorkspaces()        

    def toWorkspace(self) -> Workspace:
        """Capture current UI state into a Workspace object."""
        ws = Workspace.load(self._currentWorkspaceName) or Workspace(self._currentWorkspaceName)
        
        # Sync current global settings into workspace settings before saving
        ws.settings.fromDict(settings.toDict())
        
        tree = self.mainWindow.treeWidget
        rootModules = tree.moduleModel.rootModule().children()
        allModules = flattenModules(rootModules)
        
        ws.modules = rootModules
        ws.expanded = [bool(tree.isExpanded(tree.moduleModel.indexForModule(m))) for m in allModules]
        
        return ws

    def fromWorkspace(self, workspace: Workspace):
        """Populate UI from the Workspace object."""
        self._blockSignals = True
        idx = self.combo.findData(workspace.name)
        if idx >= 0:
            self.combo.setCurrentIndex(idx)
        self._blockSignals = False

        self.mainWindow.treeWidget.clear()

        for module in workspace.modules:
            self.mainWindow.treeWidget.moduleModel.addModuleAt(module)

        if workspace.expanded:
            rootModules = self.mainWindow.treeWidget.moduleModel.rootModule().children()
            allModules = flattenModules(rootModules)
            for m, isExpanded in zip(allModules, workspace.expanded):
                if isExpanded:
                    idx = self.mainWindow.treeWidget.moduleModel.indexForModule(m)
                    if idx.isValid():
                        self.mainWindow.treeWidget.setExpanded(idx, True)

    def refreshWorkspaces(self):
        """Update the combo box from disk."""
        self._blockSignals = True
        self.combo.clear()

        for ws in Workspace.list():
            self.combo.addItem(f"💼 {ws.name}", ws.name)
        
        idx = self.combo.findData(self._currentWorkspaceName)
        if idx >= 0:
            self.combo.setCurrentIndex(idx)
        self._blockSignals = False

    def _refreshModuleBrowserSource(self):
        self.mainWindow.moduleBrowser.modulesAutoReloadWatcher.setRoots([settings.modulesPath])
        self.mainWindow.moduleBrowser.refreshModules()

    def switchWorkspace(self, name: str):
        if not name:
            return

        # Save current IF one was active and it's a DIFFERENT workspace
        if self._currentWorkspaceName and self._currentWorkspaceName != name:
            self.toWorkspace().save()

        # Check for recovery
        hasMain, hasAutosave = Workspace.getLoadInfo(name)
        recovery = False
        if hasAutosave:
            res = QMessageBox.question(
                self, 
                "Rig Builder", 
                f"A recovery file was found for '{name}'.\n\nDo you want to restore it?\n(Selecting 'No' will delete the recovery file)",
                QMessageBox.Yes | QMessageBox.No | QMessageBox.Cancel
            )
            
            if res == QMessageBox.Cancel:
                # Revert combo to previous
                self.refreshWorkspaces()
                return

            if res == QMessageBox.Yes:
                recovery = True
            else:
                # Delete autosave by loading normally and saving
                ws = Workspace.load(name)
                if ws:
                    ws.save() # This clears the sidecar

        # Load and activate
        ws = Workspace.load(name, recovery=recovery)
        if ws:
            self._currentWorkspaceName = name
            ws.activate()
            self._refreshModuleBrowserSource()
            self.fromWorkspace(ws)
            self.workspaceChanged.emit(ws)

    def _onComboChanged(self, index: int):
        if self._blockSignals:
            return
        name = self.combo.itemData(index)
        self.switchWorkspace(name)

    def _onManage(self):
        dialog = WorkspaceManagerDialog(self._currentWorkspaceName, self)
        if dialog.exec_():
            sel = dialog.selectedWorkspace()
            if sel:
                self.switchWorkspace(sel.name)
        
        self.refreshWorkspaces()

    def _onAutoSaveTimer(self):
        """Triggered by the timer. Saves the current workspace state to a sidecar file."""
        # Don't autosave if no workspace or if it's the default one (optional?)
        if not self._currentWorkspaceName:
            return
        
        self.toWorkspace().autosave()
        
        timestamp = datetime.now().strftime("%H:%M")
        print(f"Workspace '{self._currentWorkspaceName}' autosaved at {timestamp}")

    def _updateAutoSaveInterval(self):
        """Update timer interval from global settings."""
        interval_ms = settings.autoSaveInterval * 60 * 1000
        self.autoSaveTimer.start(interval_ms)
