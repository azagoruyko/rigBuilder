from __future__ import annotations
import os
from functools import partial
from typing import List, Optional, Union

from ..qt import *
from ..settings import (
    Settings,
    RIG_BUILDER_WORKSPACES_PATH
)
from .. import workspace
from ..workspace import Workspace
from ..utils import replaceSpecialChars
from ..client.connectionManager import connectionManager

_workspaceCache: dict[str, Workspace] = {}

def getWorkspace(name: str) -> Workspace:
    """Retrieve workspace from cache or load it."""
    if name in _workspaceCache:
        return _workspaceCache[name]
    
    ws = Workspace.load(name)
    _workspaceCache[name] = ws
    return ws

class WorkspaceManagerDialog(QDialog):
    """Dialog for listing, creating, and removing workspaces."""
    workspaceSwitchRequested = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Workspace Manager")
        self.setMinimumSize(700, 400)
        
        self._blockSettingsSignals = False

        # 1. Left Panel (Workspace List)
        self.listWidget = QListWidget()
        self.listWidget.itemDoubleClicked.connect(self.accept)

        self.newBtn = QPushButton("➕")
        self.newBtn.setAutoDefault(False)
        self.newBtn.clicked.connect(self._onNew)

        self.removeBtn = QPushButton("❌")
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

        self.ollamaEmbeddingModelEdit = QLineEdit()
        self.ollamaEmbeddingModelEdit.editingFinished.connect(partial(self._onLineEditChanged, "ollamaEmbeddingModel", self.ollamaEmbeddingModelEdit))
        self.settingsLayout.addRow("Ollama Embedding Model:", self.ollamaEmbeddingModelEdit)

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
        self.removeBtn.setEnabled(ws and ws.name.lower() != "default")
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
        self.ollamaEmbeddingModelEdit.setText(ws.settings.ollamaEmbeddingModel)
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
            ws.save()

    def _onLineEditChanged(self, key, edit):
        self._onSettingChanged(key, edit.text())

    def _onComboChanged(self, key, combo, _idx):
        self._onSettingChanged(key, combo.currentData())

    def _onBrowseModulesPath(self):
        ws = self.selectedWorkspace()
        if not ws:
            return
            
        startDir = self.modulesPathEdit.text() or ws.folderPath
        path = QFileDialog.getExistingDirectory(self, "Select Modules Directory", startDir)
        if path:
            self.modulesPathEdit.setText(path)
            self._onSettingChanged("modulesPath", path)

    def refresh(self):
        self.listWidget.clear()

        for wsName in Workspace.list():
            ws = getWorkspace(wsName)
            item = QListWidgetItem(f"💼 {wsName}")
            item.setData(Qt.UserRole, ws)
            self.listWidget.addItem(item)
            
            if wsName == workspace.currentWorkspace.name:
                self.listWidget.setCurrentItem(item)

    def selectedWorkspace(self) -> Optional[Workspace]:
        item = self.listWidget.currentItem()
        if item:
            return item.data(Qt.UserRole)

    def _onNew(self):
        name, ok = QInputDialog.getText(self, "New Workspace", "Workspace Name:")
        if not ok or not name:
            return

        name = replaceSpecialChars(name.strip())
        if not name:
            QMessageBox.warning(self, "Workspace Manager", "Workspace name cannot be empty.")
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

        # Switch to default if we're deleting the active workspace
        if ws.name == workspace.currentWorkspace.name:
            self.workspaceSwitchRequested.emit("default")

        if ws.delete():
            _workspaceCache.pop(ws.name, None)
            self.refresh()

    def _onOpenFolder(self):
        ws = self.selectedWorkspace()
        if ws:
            os.startfile(ws.folderPath)

class WorkspaceWidget(QWidget):
    """UI Widget for workspace selection and management."""
    workspaceChanged = Signal(object) # Workspace
    aboutToChangeWorkspace = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._blockSignals = False

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
        self.refreshWorkspaces()        


    def refreshWorkspaces(self):
        """Update the combo box from disk."""
        self._blockSignals = True
        self.combo.clear()

        # If current workspace doesn't exist anymore, fallback to default
        if not Workspace.exists(workspace.currentWorkspace.name):
            self.switchWorkspace("default")

        for wsName in Workspace.list():
            self.combo.addItem(f"💼 {wsName}", wsName)
        
        idx = self.combo.findData(workspace.currentWorkspace.name)
        if idx >= 0:
            self.combo.setCurrentIndex(idx)
        self._blockSignals = False

    def switchWorkspace(self, ws:str):
        ws = getWorkspace(ws)
        workspace.currentWorkspace = ws
        ws.activate()

        self.workspaceChanged.emit(ws)

    def _onComboChanged(self, index: int):
        if self._blockSignals:
            return

        wsName = self.combo.itemData(index)
        if not wsName:
            return

        # Save current IF one was active and it's a DIFFERENT workspace
        if workspace.currentWorkspace.name != wsName:
            self.aboutToChangeWorkspace.emit()

        self.switchWorkspace(wsName)

    def _onManage(self):
        dialog = WorkspaceManagerDialog(parent=self)
        dialog.workspaceSwitchRequested.connect(self.switchWorkspace)
        dialog.exec()
        self.refreshWorkspaces()

