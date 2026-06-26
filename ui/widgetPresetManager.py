import os
import json
import logging
from .qt import *
from ..core.settings import RIG_BUILDER_USER_PATH
from .utils import centerWindow
from ..core.utils import loadJson, saveJson

PRESETS_FILE = os.path.join(RIG_BUILDER_USER_PATH, "presets.json")
logger = logging.getLogger('rigBuilder')

class WidgetPresetManager:
    """Manages saving, loading and removing widget presets."""

    @staticmethod
    def presets() -> dict:
        """Return all saved presets."""
        if os.path.exists(PRESETS_FILE):
            try:
                return loadJson(PRESETS_FILE)
            except Exception as e:
                logger.error(f"Failed to load presets from {PRESETS_FILE}: {e}")
        return {}

    @staticmethod
    def savePreset(name: str, template: str, data: dict):
        """Save a new preset or update an existing one."""
        presets = WidgetPresetManager.presets()
        presets[name] = {"template": template, "data": data}
        try:
            saveJson(PRESETS_FILE, presets)
        except Exception as e:
            logger.error(f"Failed to save preset '{name}': {e}")

    @staticmethod
    def removePreset(name: str):
        """Remove a preset by name."""
        presets = WidgetPresetManager.presets()
        if name in presets:
            del presets[name]
            try:
                saveJson(PRESETS_FILE, presets)
            except Exception as e:
                logger.error(f"Failed to remove preset '{name}': {e}")

    @staticmethod
    def renamePreset(oldName: str, newName: str):
        """Rename an existing preset."""
        presets = WidgetPresetManager.presets()
        if oldName in presets:
            presets[newName] = presets.pop(oldName)
            try:
                saveJson(PRESETS_FILE, presets)
            except Exception as e:
                logger.error(f"Failed to rename preset '{oldName}' to '{newName}': {e}")


class PresetEditorDialog(QDialog):
    """Dialog for managing widget presets (rename, remove, edit JSON)."""

    def __init__(self, parent=None):
        super().__init__(parent)

        from .widgets import EditJsonDialog # avoid circular import if EditJsonDialog is in .widgets.ui

        self.setWindowTitle("Manage Presets")
        self.resize(600, 500)
        
        layout = QVBoxLayout(self)
        
        self.listWidget = QListWidget()
        self.listWidget.itemSelectionChanged.connect(self._onSelectionChanged)
        self.listWidget.itemDoubleClicked.connect(self._rename)
        
        btnLayout = QHBoxLayout()
        self.removeBtn = QPushButton("Remove")
        self.removeBtn.clicked.connect(self._remove)
        self.editDataBtn = QPushButton("Edit Data...")
        self.editDataBtn.clicked.connect(self._editData)
        
        btnLayout.addWidget(self.removeBtn)
        btnLayout.addWidget(self.editDataBtn)
        btnLayout.addStretch()
        
        closeBtn = QPushButton("Close")
        closeBtn.clicked.connect(self.accept)
        btnLayout.addWidget(closeBtn)
        
        layout.addWidget(self.listWidget)
        layout.addLayout(btnLayout)
        
        self._refreshList()
        self._onSelectionChanged()
        
        centerWindow(self)

    def _refreshList(self):
        self.listWidget.clear()
        presets = WidgetPresetManager.presets()
        for name in sorted(presets.keys()):
            item = QListWidgetItem(f"{name} ({presets[name]['template']})")
            item.setData(Qt.UserRole, name)
            self.listWidget.addItem(item)

    def _onSelectionChanged(self):
        hasSelection = bool(self.listWidget.selectedItems())
        self.removeBtn.setEnabled(hasSelection)
        self.editDataBtn.setEnabled(hasSelection)

    def _rename(self):
        item = self.listWidget.currentItem()
        if not item:
            return
            
        oldName = item.data(Qt.UserRole)
        newName, ok = QInputDialog.getText(self, "Rename Preset", "New name:", QLineEdit.Normal, oldName)
        if ok and newName and newName != oldName:
            WidgetPresetManager.renamePreset(oldName, newName)
            self._refreshList()

    def _remove(self):
        item = self.listWidget.currentItem()
        if not item:
            return
            
        name = item.data(Qt.UserRole)
        if QMessageBox.question(self, "Remove Preset", f"Remove preset '{name}'?", QMessageBox.Yes | QMessageBox.No) == QMessageBox.Yes:
            WidgetPresetManager.removePreset(name)
            self._refreshList()

    def _editData(self):
        from .widgets import EditJsonDialog # avoid circular import
        item = self.listWidget.currentItem()
        if not item:
            return
            
        name = item.data(Qt.UserRole)
        presets = WidgetPresetManager.presets()
        preset = presets[name]
        
        def save(newDataList):
            newData = newDataList[0] # EditJsonDialog returns a list
            WidgetPresetManager.savePreset(name, preset["template"], newData)
            
        dlg = EditJsonDialog(preset["data"], title=f"Edit Preset Data: {name}", parent=self)
        dlg.saved.connect(save)
        dlg.exec()
