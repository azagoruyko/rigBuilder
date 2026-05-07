from __future__ import annotations
import json
import time
import re
import os
import subprocess
import inspect
import sys
import shutil
import logging
import textwrap
import xml.etree.ElementTree as ET
from functools import partial
from typing import Callable, Optional, List, Tuple, Union, Any, TYPE_CHECKING

from .. import __version__
from .. import workspace
from ..ai.engine import IS_OLLAMA_AVAILABLE
from ..client.connectionManager import connectionManager
from ..client.hostExecutor import hostExecutor
from ..core import *
from ..uidManager import UidManager
from ..logger import logger, logHandler
from ..qt import *
from ..server.hosts import AVAILABLE_HOSTS, HOST_STARTUP_TEMPLATE
from ..settings import settings, RIG_BUILDER_PATH, RIG_BUILDER_USER_PATH
from ..utils import *
from ..widgets.core import getAttributeFromValue, DEFAULT_WIDGETS_DATA
from ..widgets.ui import TemplateWidgets, EditTextDialog, EditJsonDialog
from ..workspace import Workspace
from .aichat import AIChatDialog
from .apiBrowser import ApiBrowser
from .diffBrowser import DiffBrowserDialog, calculateModulesDiff, DiffBrowserDialogWithConfirm
from .docBrowser import DocBrowser
from .editor import CodeEditorWithNumbersWidget
from .fileTracker import TrackFileChangesThread, trackFileChangesThreads, DirectoryWatcher
from .moduleBrowser import ModuleBrowser
from .moduleHistoryBrowser import ModuleHistoryBrowser
from .utils import *
from .widgetPresetManager import WidgetPresetManager, PresetEditorDialog
from .workspaceManager import WorkspaceWidget, getWorkspace


class AttributesWidget(QWidget):
    moduleChanged = Signal(object) # Module
    executionRequested = Signal(str)

    def __init__(self, module: Module, category: str, **kwargs):
        super().__init__(**kwargs)

        self.module = module
        self.category = category

        self._attributeAndWidgets = [] # [attribute, nameWidget, templateWidget]

        self.updateAttributes()

    def updateAttributes(self):
        if not self.module:
            return

        layout = QGridLayout()
        layout.setDefaultPositioning(2, Qt.Horizontal)
        layout.setColumnStretch(1, 1)
        self.setLayout(layout)

        self._attributeAndWidgets = []
        self.attributes = [a for a in self.module.attributes() if a.category() == self.category]

        for idx, a in enumerate(self.attributes):
            templateWidget = TemplateWidgets[a.template()]()
            nameWidget = QLabel(a.name())

            self._attributeAndWidgets.append((a, nameWidget, templateWidget))
            
            self.updateWidget(idx)
            self.updateWidgetStyle(idx)

            templateWidget.somethingChanged.connect(partial(self._onWidgetChange, idx))
            templateWidget.moduleCodeExecutionRequested.connect(self._onModuleCodeExecutionRequested)

            nameWidget.setAlignment(Qt.AlignRight)
            nameWidget.setCursor(Qt.PointingHandCursor)
            nameWidget.contextMenuEvent = partial(self.nameContextMenuEvent, attrWidgetIndex=idx)

            layout.addWidget(nameWidget)
            layout.addWidget(templateWidget)

        layout.addWidget(QLabel())
        layout.setRowStretch(layout.rowCount(), 1)

    def _onModuleCodeExecutionRequested(self, code: str):
        if not code:
            return

        self.executionRequested.emit(code)

    def connectionMenu(self, menu: QMenu, module: Module, attrWidgetIndex: int, path: str = "/"):
        attr, _, _ = self._attributeAndWidgets[attrWidgetIndex]

        subMenu = QMenu(module.name(), self)

        for a in module.attributes():
            if a.template() == attr.template() and a.name(): # skip empty names as well
                subMenu.addAction(a.name(), partial(self.connectAttr, path+module.name()+"/"+a.name(), attrWidgetIndex))

        for ch in module.children():
            self.connectionMenu(subMenu, ch, attrWidgetIndex, path+module.name()+"/")

        if subMenu.actions():
            menu.addMenu(subMenu)

    def nameContextMenuEvent(self, event: QContextMenuEvent, attrWidgetIndex: int):
        attr, _, _ = self._attributeAndWidgets[attrWidgetIndex]

        menu = QMenu(self)
        titleAction = menu.addAction(attr.name() or "(Unnamed)")
        titleAction.setEnabled(False)
        font = titleAction.font()
        font.setBold(True)
        titleAction.setFont(font)
        menu.addSeparator()

        if self.module and self.module.parent():
            makeConnectionMenu = menu.addMenu("Make connection")

            for a in self.module.parent().attributes():
                if a.template() == attr.template() and a.name(): # skip empty names as well
                    makeConnectionMenu.addAction(a.name(), partial(self.connectAttr, "/"+a.name(), attrWidgetIndex))

            for ch in self.module.parent().children():
                if ch is not self.module:
                    self.connectionMenu(makeConnectionMenu, ch, attrWidgetIndex)

        if attr.connect():
            menu.addAction("Break connection", partial(self.disconnectAttr, attrWidgetIndex))

        menu.addSeparator()

        menu.addAction("Edit data", partial(self.editData, attrWidgetIndex))
        menu.addSeparator()
        menu.addAction("Edit expression", partial(self.editExpression, attrWidgetIndex))

        if attr.expression():
            menu.addAction("Evaluate expression", partial(self.updateWidget, attrWidgetIndex))
            menu.addAction("Clear expression", partial(self.clearExpression, attrWidgetIndex))

        menu.addSeparator()
        menu.addAction("Expose", partial(self.exposeAttr, attrWidgetIndex))
        menu.addSeparator()
        menu.addAction("Reset", partial(self.resetAttr, attrWidgetIndex))

        menu.addSeparator()

        # Presets submenu
        presetsMenu = menu.addMenu("Presets")
        presetsMenu.addAction("Manage Presets...", PresetEditorDialog(parent=self).exec)
        presetsMenu.addAction("Save as Preset...", partial(self._saveAsPreset, attrWidgetIndex))
        
        # Presets filtered by template
        presets = WidgetPresetManager.presets()
        compatiblePresets = {name: data for name, data in presets.items() if data.get("template") == attr.template()}
        
        if compatiblePresets:
            presetsMenu.addSeparator()
            for name, data in sorted(compatiblePresets.items()):
                presetsMenu.addAction(name, partial(self._applyPreset, attrWidgetIndex, data["data"]))

        menu.popup(event.globalPos())

    def _saveAsPreset(self, attrWidgetIndex: int):
        attr, _, _ = self._attributeAndWidgets[attrWidgetIndex]
        name, ok = QInputDialog.getText(self, "Save Preset", "Preset name:", QLineEdit.Normal, attr.name())
        if ok and name:
            WidgetPresetManager.savePreset(name, attr.template(), attr.localData())

    def _applyPreset(self, attrWidgetIndex: int, data: dict):
        attr, _, widget = self._attributeAndWidgets[attrWidgetIndex]
        attr.setData(data)
        self.updateWidget(attrWidgetIndex)
        self.updateWidgetStyle(attrWidgetIndex)

    @staticmethod
    def _wrapper(f: Callable[..., object]):
        def inner(self, attrWidgetIndex: int, *args, **kwargs):
            attr, _, widget = self._attributeAndWidgets[attrWidgetIndex]
            try:
                return f(self, attrWidgetIndex, *args, **kwargs)
            
            except Exception as e:
                moduleName = self.module.name() if self.module else "unknown"
                logger.error(f"{moduleName}.{attr.name()}: {str(e)}")

                if type(e) == AttributeResolverError:
                    with blockedWidgetContext(widget) as w:
                        w.setJsonData(attr.localData())

        return inner
    
    @_wrapper
    def _onWidgetChange(self, attrWidgetIndex: int):
        attr, _, widget = self._attributeAndWidgets[attrWidgetIndex]

        widgetData = widget.getJsonData()
        attr.setData(widgetData) # implicitly push

        if not self.module:
            return

        previousData = {id(a):a.localData() for a in self.module.attributes()}
        modifiedAttrs = []
        for otherAttr in self.module.attributes():
            otherAttr.pull()
            if otherAttr.localData() != previousData[id(otherAttr)]:
                modifiedAttrs.append(otherAttr)
        
        if modifiedAttrs:
            self.moduleChanged.emit(self.module)

        for idx, (otherAttr, _, otherWidget) in enumerate(self._attributeAndWidgets): # update attributes' widgets
            if otherAttr in modifiedAttrs:
                with blockedWidgetContext(otherWidget) as w:
                    w.setJsonData(otherAttr.localData())
                self.updateWidgetStyle(idx)

        # style not updated by the loop above (attr's data didn't change after pull), refresh it here
        if attr not in modifiedAttrs: 
            self.updateWidgetStyle(attrWidgetIndex)       

    @_wrapper
    def updateWidget(self, attrWidgetIndex: int):
        attr, _, widget = self._attributeAndWidgets[attrWidgetIndex]
        with blockedWidgetContext(widget) as w:
            w.setJsonData(attr.data()) # pull data

    def updateWidgets(self):
        for i in range(len(self._attributeAndWidgets)):
            self.updateWidget(i)

    def updateWidgetStyle(self, attrWidgetIndex: int):
        attr, nameWidget, widget = self._attributeAndWidgets[attrWidgetIndex]

        style = ""
        tooltip = []
        if attr.connect():
            tooltip.append("Connect: "+attr.connect())
        if attr.expression():
            tooltip.append("Expression:\n" + attr.expression())

        if attr.connect() and not attr.expression(): # only connection (yellow)
            style = "TemplateWidget { border: 1px solid rgba(210, 175, 0, 0.7); border-radius: 4px; }"
        
        elif attr.expression() and not attr.connect(): # only expression (bluish purple)
            style = "TemplateWidget { border: 1px solid rgba(123, 104, 238, 0.8); border-radius: 4px; }"
        
        elif attr.expression() and attr.connect(): # both (magenta)
            style = "TemplateWidget { border: 1px solid rgba(180, 50, 180, 0.7); border-radius: 4px; }"

        nameWidget.setText(attr.name())

        widget.setStyleSheet(style)
        widget.setToolTip("\n".join(tooltip))

    def updateWidgetStyles(self):
        for i in range(len(self._attributeAndWidgets)):
            self.updateWidgetStyle(i)

    def exposeAttr(self, attrWidgetIndex: int):
        attr, _, _ = self._attributeAndWidgets[attrWidgetIndex]

        if not self.module or not self.module.parent():
            QMessageBox.warning(self, "Rig Builder", "Can't expose attribute to parent: no parent module")
            return

        if self.module.parent().findAttribute(attr.name()):
            QMessageBox.warning(self, "Rig Builder", "Can't expose attribute to parent: attribute already exists")
            return

        doUsePrefix = QMessageBox.question(self, "Rig Builder", "Use prefix for the exposed attribute name?", QMessageBox.Yes | QMessageBox.No, QMessageBox.Yes) == QMessageBox.Yes
        prefix = self.module.name() + "_" if doUsePrefix else ""
        expAttr = attr.copy()
        expAttr.setName(prefix + expAttr.name())
        self.module.parent().addAttribute(expAttr)
        self.connectAttr("/"+expAttr.name(), attrWidgetIndex)
        self.moduleChanged.emit(self.module.parent())

    @_wrapper
    def editData(self, attrWidgetIndex: int):
        def save(data):
            @AttributesWidget._wrapper
            def _save(_, attrWidgetIndex: int):
                attr.setData(data[0]) # use [0] because data is a list
                self.updateWidget(attrWidgetIndex)
                self.updateWidgetStyle(attrWidgetIndex)
            _save(self, attrWidgetIndex)

        attr, _, _ = self._attributeAndWidgets[attrWidgetIndex]
        w = EditJsonDialog(attr.localData(), title="Edit data", parent=self)
        w.saved.connect(save)
        w.show()

    def editExpression(self, attrWidgetIndex: int):
        def save(text: str):
            attr.setExpression(text)
            self.updateWidgets()
            self.updateWidgetStyle(attrWidgetIndex)

        attr, _, _ = self._attributeAndWidgets[attrWidgetIndex]

        if not self.module:
            return

        w = EditTextDialog(
            attr.expression(), 
            title="Edit expression for '{}'".format(attr.name()), 
            placeholder='# Example: value = ch("../someAttr") + 1 or data["items"] = [1,2,3]', 
            words=set(self.module.context().keys()), 
            python=True,
            parent=self)

        w.saved.connect(save)
        w.show()

    def clearExpression(self, attrWidgetIndex: int):
        attr, _, _ = self._attributeAndWidgets[attrWidgetIndex]
        attr.setExpression("")
        self.updateWidgetStyle(attrWidgetIndex)

    def resetAttr(self, attrWidgetIndex: int):
        attr, _, _ = self._attributeAndWidgets[attrWidgetIndex]

        attr.setConnect("")
        attr.setData(copyJson(DEFAULT_WIDGETS_DATA[attr.template()]))
        self.updateWidget(attrWidgetIndex)
        self.updateWidgetStyle(attrWidgetIndex)

    def disconnectAttr(self, attrWidgetIndex: int):
        attr, _, _ = self._attributeAndWidgets[attrWidgetIndex]
        attr.setConnect("")
        self.updateWidgetStyle(attrWidgetIndex)

    def connectAttr(self, connect: str, attrWidgetIndex: int):
        attr, _, _ = self._attributeAndWidgets[attrWidgetIndex]
        attr.setConnect(connect)
        self.updateWidget(attrWidgetIndex)
        self.updateWidgetStyle(attrWidgetIndex)

class AttributesTabWidget(QTabWidget):
    moduleChanged = Signal(object) # Module
    executionRequested = Signal(str)
    attributesChanged = Signal()

    def __init__(self, **kwargs):
        super().__init__(**kwargs)

        self.module = None
        self.tabsAttributes = {}
        self._attributesWidget = None

        self.searchAndReplaceDialog = SearchReplaceDialog(["In all tabs"], parent=self)
        self.searchAndReplaceDialog.onReplace.connect(self._onReplace)

        self.currentChanged.connect(self.selectTab)

    def contextMenuEvent(self, event: QContextMenuEvent):
        menu = QMenu(self)

        if self.module:
            addAttrMenu = menu.addMenu("Add attribute")
            for templateName in sorted(TemplateWidgets.keys()):
                addAttrMenu.addAction(templateName, partial(self._onQuickAddAttribute, templateName))

            menu.addSeparator()
            menu.addAction("Edit attributes", self.editAttributes)
            menu.addSeparator()
            menu.addAction("Replace in values", self.searchAndReplaceDialog.exec)

        menu.popup(event.globalPos())

    def _onQuickAddAttribute(self, template: str):
        name, ok = QInputDialog.getText(self, "Quick Add Attribute", "Enter attribute name:", QLineEdit.Normal, "newAttr")
        if not ok:
            return

        if name and self.module.findAttribute(name):
            QMessageBox.warning(self, "Rig Builder", "Attribute already exists")
            return

        category = self.tabText(self.currentIndex()) or "General"
        newAttr = Attribute(name=name, template=template, category=category)
        
        if template in DEFAULT_WIDGETS_DATA:
            newAttr.setData(copyJson(DEFAULT_WIDGETS_DATA[template]))

        self.module.addAttribute(newAttr)
        self.attributesChanged.emit()
        self.updateTabs()

    def editAttributes(self):
        dialog = EditAttributesDialog(self.module, self.currentIndex(), parent=self)
        dialog.exec()

        self.attributesChanged.emit()
        self.updateTabs()

    def _onReplace(self, old: str, new: str, opts: dict[str, bool]):
        def replaceStringInData(data: object, old: str, new: str) -> object:
            try:
                return json.loads(json.dumps(data).replace(old,new))
            except ValueError:
                return data

        if opts.get("In all tabs"):
            attributes = []
            for attrs in self.tabsAttributes.values(): # merge all attributes
                attributes.extend(attrs)
        else:
            attributes = self.tabsAttributes[self.tabText(self.currentIndex())]

        for attr in attributes:
            v = replaceStringInData(attr.get(), old, new)
            attr.set(v)

        self.updateTabs()

    def selectTab(self, idx: int):
        """Switch to tab at index and build attributes widget."""

        if self.count() == 0:
            return

        idx = clamp(idx, 0, self.count()-1)

        title = self.tabText(idx)
        if title not in self.tabsAttributes:
            self._attributesWidget = None
            return

        scrollArea = self.widget(idx)
        self._attributesWidget = AttributesWidget(self.module, title)
        
        # Forward signals
        self._attributesWidget.moduleChanged.connect(self.moduleChanged.emit)
        self._attributesWidget.executionRequested.connect(self.executionRequested.emit)
        
        scrollArea.setWidget(self._attributesWidget)
        self.setCurrentIndex(idx)

    def updateTabs(self, module: Optional[Module] = None):
        if module is not None:
            self.module = module

        oldIndex = self.currentIndex()
        oldCount = self.count()

        self._attributesWidget = None
        self.tabsAttributes.clear()

        module = self.module
        if not module:
            return

        self.blockSignals(True)

        tabTitlesInOrder = []
        for a in module.attributes():
            if a.category() not in self.tabsAttributes:
                self.tabsAttributes[a.category()] = []
                tabTitlesInOrder.append(a.category())

            self.tabsAttributes[a.category()].append(a)

        if not tabTitlesInOrder: # no attributes, show placeholder
            label = QLabel("No attributes, right-click to add them.")
            label.setAlignment(Qt.AlignCenter)
            label.setStyleSheet("color: gray;")
            scrollArea = QScrollArea()
            scrollArea.setWidgetResizable(True)
            scrollArea.setWidget(label)
            self.addTab(scrollArea, "")

        for t in tabTitlesInOrder:
            scrollArea = QScrollArea() # empty, in tabChanged actual widget is set
            scrollArea.setWidgetResizable(True)
            self.addTab(scrollArea, t) # add new tabs in front of the old ones

        # remove previous tabs
        for _ in range(oldCount):
            w = self.widget(0)
            if w:
                w.deleteLater()
            self.removeTab(0)

        if self.count() == 1:
            self.tabBar().hide()
        else:
            self.tabBar().show()

        self.selectTab(oldIndex)
        self.blockSignals(False)

    def updateWidgetStyles(self):
        if self._attributesWidget:
            self._attributesWidget.updateWidgetStyles()


class ModuleTracker(QObject):
    """
    Handles tracking of module files on disk.
    Loads and caches original module definitions by UID and monitors file changes.
    """
    moduleChanged = Signal(str) # uid

    def __init__(self, parent: Optional[QObject] = None):
        super().__init__(parent)
        self._cache: dict[str, Module] = {}
        self._watcher = QFileSystemWatcher(self)
        self._watcher.fileChanged.connect(self._onFileChanged)

    def getModule(self, uid: str) -> Optional[Module]:
        """Get the cached reference module by UID, loading it if necessary."""
        if not uid:
            return None
            
        if uid not in self._cache:
            self.loadModule(uid)
            
        return self._cache.get(uid)

    def loadModule(self, uid: str):
        """Load module from disk and add its file to the watcher."""
        path = UidManager.resolve(uid)
        if not path or not os.path.exists(path):
            self._cache[uid] = None
            return

        try:
            # Get the module from disk (synced)
            refModule = Module.loadModule(path)
            self._cache[uid] = refModule
            
            # Start watching the file for changes if not already watched
            if path not in self._watcher.files():
                self._watcher.addPath(path)
                
        except Exception as e:
            mainWindow.logger.error(f"ModuleTracker: Failed to load module for {uid}: {str(e)}")
            self._cache[uid] = None

    def _onFileChanged(self, path: str):
        """Handle file change event from QFileSystemWatcher."""
        uid = UidManager.getUidFromFile(path)
        if uid and uid in self._cache:
            self.loadModule(uid)
            self.moduleChanged.emit(uid)

        # resync dependent modules in cache
        for m in self._cache.values():
            if m.dependsOn(uid):
                m.sync()
                self.moduleChanged.emit(m._uid)

    def refresh(self):
        """Force-reload all cached reference modules."""
        for uid in list(self._cache.keys()):
            self.loadModule(uid)

    def clearCache(self):
        """Clear all loaded modules and stop watching files."""
        self._cache.clear()
        if self._watcher.files():
            self._watcher.removePaths(self._watcher.files())

class ModuleModel(QAbstractItemModel):
    """
    Qt Model for Module hierarchy.
    Enables MVC pattern where Module is the single source of truth.
    """
    def __init__(self, rootModule: Optional[Module] = None, parent=None):
        super().__init__(parent)
        self._rootModule = rootModule or Module()
        self._rootModule.setName("ROOT")
        self._draggedModules = [] # Temporary storage for internal drag and drop
        
        self.moduleTracker = ModuleTracker(self)
        self.moduleTracker.moduleChanged.connect(self._onModuleTrackerChanged)

    def rootModule(self) -> Module:
        return self._rootModule

    def getModule(self, index: QModelIndex) -> Optional[Module]:
        """Convert a QModelIndex to a Module object safely."""
        if index.isValid():
            return index.internalPointer()
        return None

    def index(self, row, column, parent=QModelIndex()):
        if not self.hasIndex(row, column, parent):
            return QModelIndex()

        if not parent.isValid():
            parentModule = self._rootModule
        else:
            parentModule = parent.internalPointer()

        if row < 0 or row >= len(parentModule.children()):
            return QModelIndex()

        childModule = parentModule.children()[row]
        return self.createIndex(row, column, childModule)

    def parent(self, index):
        if not index.isValid():
            return QModelIndex()

        childModule = index.internalPointer()
        parentModule = childModule.parent()

        if parentModule == self._rootModule or parentModule is None:
            return QModelIndex()

        grandParent = parentModule.parent()
        if grandParent is None: # Should not happen if parentModule != rootModule
            return QModelIndex()
            
        try:
            row = grandParent.children().index(parentModule)
        except ValueError:
            return QModelIndex()

        return self.createIndex(row, 0, parentModule)

    def rowCount(self, parent=QModelIndex()):
        if parent.column() > 0:
            return 0

        if not parent.isValid():
            parentModule = self._rootModule
        else:
            parentModule = parent.internalPointer()

        return len(parentModule.children())

    def columnCount(self, parent=QModelIndex()):
        return 3 # Name, Path, UID

    def data(self, index, role=Qt.DisplayRole):
        if not index.isValid():
            return None

        module = index.internalPointer()
        column = index.column()

        if role == Qt.DisplayRole:
            if column == 0:
                icon = ""
                if module.referenceFile():
                    icon = "📦 "
                elif self.isInsideReferenceModule(module):
                    icon = "🔒 "
                
                name = module.name()
                refModule = self.moduleTracker.getModule(module.uid())
                if refModule and module.isSyncRequired(refModule):
                    name += "*"

                return icon + name + " "

            elif column == 1:
                ref = module.referenceFile()
                if ref:
                    path = relativePath(ref, settings.modulesPath).replace("\\", "/")
                    return os.path.splitext(path)[0]
                else:
                    return ""

            elif column == 2:
                return module.uid()[:8]

        elif role == Qt.EditRole:
            if column == 0:
                return module.name()
            return "n/a"

        elif role == Qt.ForegroundRole:
            # Check if self or any parent is muted
            isMuted = module.muted()
            p = module.parent()
            while p:
                if p.muted():
                    isMuted = True
                    break
                p = p.parent()

            if column == 0:
                color = QColor(200, 200, 200)
                if isMuted:
                    color = QColor(100, 100, 100)
                elif self.isInsideReferenceModule(module):
                    color = QColor(230, 230, 100) # Yellow for reference modules
                return color

            elif column == 1:
                return QColor(100, 100, 100) if isMuted else QColor(125, 125, 125)

            elif column == 2:
                return QColor(100, 100, 150) if isMuted else QColor(125, 125, 170)

        elif role == Qt.BackgroundRole:
            if column == 0:
                if not re.match("\\w*", module.name()):
                    return QColor(170, 50, 50)
                
                p = module.parent()
                if p and len([ch for ch in p.children() if ch.name() == module.name()]) > 1:
                    return QColor(170, 50, 50)

    def setData(self, index, value, role=Qt.EditRole):
        if index.isValid() and role == Qt.EditRole:
            module = index.internalPointer()
            column = index.column()
            if column == 0:
                newName = replaceSpecialChars(str(value)).strip()
                p = module.parent() or self._rootModule
                
                existingNames = set([ch.name() for ch in p.children() if ch is not module])
                newName = findUniqueName(newName, existingNames)
                
                # Handle connection updates (migrated from ModuleItem)
                connections = self._saveConnections(module)
                module.setName(newName)
                self._updateConnections(connections)
                
                self.dataChanged.emit(index, index)
                return True
        return False

    def _saveConnections(self, currentModule: Module):
        connections = []
        for a in currentModule.attributes():
            connections.append({"attr":a, "module": currentModule, "connections":a.listConnections()})
        for ch in currentModule.children():
            connections += self._saveConnections(ch)
        return connections

    def _updateConnections(self, connections: list[dict]):
        for data in connections:
            srcAttr = data["attr"]
            module = data["module"]
            for a in data["connections"]:
                c = module.path().replace(a.module().path(inclusive=False), "") + "/" + srcAttr.name()
                a.setConnect(c)

    def headerData(self, section, orientation, role=Qt.DisplayRole):
        if orientation == Qt.Horizontal and role == Qt.DisplayRole:
            return ["Name", "Path", "UID"][section]
        return None

    def flags(self, index):
        if not index.isValid():
            return Qt.ItemIsDropEnabled
        
        f = Qt.ItemIsSelectable | Qt.ItemIsEnabled | Qt.ItemIsDragEnabled | Qt.ItemIsDropEnabled
        return f | Qt.ItemIsEditable

    # Helpers for structural changes
    def addModuleAt(self, module: Module, parentIndex: QModelIndex = QModelIndex(), row: int = -1):
        parentModule = parentIndex.internalPointer() if parentIndex.isValid() else self._rootModule
        
        # Ensure unique name within parent
        existingNames = {ch.name() for ch in parentModule.children()}
        module.setName(findUniqueName(module.name(), existingNames))

        if row < 0:
            row = len(parentModule.children())
        
        self.beginInsertRows(parentIndex, row, row)
        parentModule.insertChild(row, module)
        self.endInsertRows()
        return self.index(row, 0, parentIndex)

    def indexForModule(self, module: Module, parent=QModelIndex()) -> QModelIndex:
        """Find the QModelIndex for a given Module instance."""
        if not module:
             return QModelIndex()
             
        for row in range(self.rowCount(parent)):
            idx = self.index(row, 0, parent)
            if idx.internalPointer() == module:
                return idx
            
            # Recursive search
            childIdx = self.indexForModule(module, idx)
            if childIdx.isValid():
                return childIdx
        return QModelIndex()

    def removeModule(self, index: QModelIndex):
        module = self.getModule(index)
        if not module:
            return False
        
        parentModule = module.parent() or self._rootModule
        parentIndex = index.parent()
        
        try:
            row = parentModule.children().index(module)
        except ValueError:
            return False
            
        self.beginRemoveRows(parentIndex, row, row)
        parentModule.removeChild(module)
        self.endRemoveRows()
        return True

    def mimeTypes(self) -> List[str]:
        return ["text/uri-list", "application/x-rigbuilder-module-internal"]

    def mimeData(self, indexes: List[QModelIndex]) -> QMimeData:
        mimeData = QMimeData()
        
        self._draggedModules = []
        for idx in indexes:
            if idx.column() == 0:
                m = self.getModule(idx)
                if m:
                    self._draggedModules.append(m)
        
        if self._draggedModules:
            # We just need to signal that we have internal modules
            mimeData.setData("application/x-rigbuilder-module-internal", b"true")
        return mimeData

    def supportedDropActions(self) -> Qt.DropActions:
        return Qt.CopyAction | Qt.MoveAction

    def canDropMimeData(self, data: QMimeData, action: Qt.DropAction, row: int, column: int, parent: QModelIndex) -> bool:
        return data.hasFormat("application/x-rigbuilder-module-internal") or data.hasUrls()

    def dropMimeData(self, data: QMimeData, action: Qt.DropAction, row: int, column: int, parent: QModelIndex) -> bool:
        if action == Qt.IgnoreAction:
            return True

        if not data.hasFormat("application/x-rigbuilder-module-internal") and not data.hasUrls():
            return False

        parentModule = self.getModule(parent) or self._rootModule
        if row < 0:
            row = len(parentModule.children())

        # External drops (from browser)
        if data.hasUrls():
            for url in data.urls():
                filePath = url.toLocalFile()
                if not filePath or not os.path.exists(filePath):
                    continue

                if any(filePath.endswith(ext) for ext in MODULE_EXTS):
                    try:
                        m = Module.loadModule(filePath)
                        self.addModuleAt(m, parent, row)
                        row += 1
                    except Exception:
                        continue

                elif filePath.endswith(".py"):
                    with open(filePath, "r", encoding="utf-8") as f:
                        code = f.read()

                    name = os.path.splitext(os.path.basename(filePath))[0]
                    m = Module()
                    m.setName(name)
                    m.setRunCode(code)

                    self.addModuleAt(m, parent, row)
                    row += 1
            return True

        # If it's internal move (reordering)
        if data.hasFormat("application/x-rigbuilder-module-internal"):
            if not self._draggedModules:
                return False

            for m in self._draggedModules:
                oldParent = m.parent() or self._rootModule
                try:
                    oldRow = oldParent.children().index(m)
                except ValueError:
                    continue
                
                oldParentIdx = self.indexForModule(oldParent) if oldParent != self._rootModule else QModelIndex()
                
                # Prevent moving into itself
                temp = parentModule
                isRecursive = False
                while temp:
                    if temp == m:
                        isRecursive = True
                        break
                    temp = temp.parent()
                if isRecursive: continue

                targetRow = row
                if oldParent == parentModule and oldRow < row:
                    targetRow -= 1

                # Use beginMoveRows and check its return value
                # Documentation: destinationChild is the index where the rows will be placed
                # before any items are removed.
                if self.beginMoveRows(oldParentIdx, oldRow, oldRow, parent, row):
                    try:
                        oldParent.removeChild(m)
                        parentModule.insertChild(targetRow, m)
                    finally:
                        self.endMoveRows()
                    
                    # Update row for the next item in multi-selection 
                    row = targetRow + 1
            
            self._draggedModules = []
            return True
        
    def isInsideReferenceModule(self, module: Module) -> bool:
        """Recursive helper to find the reference counterpart (source definition) of a module."""
        if module.referenceFile():
            return True

        parent = module.parent()
        return self.isInsideReferenceModule(parent) if parent else False

    def _onModuleTrackerChanged(self, uid: str):
        """Handle signal from ModuleTracker when a tracked file changes."""
        self.layoutChanged.emit() # Refresh all

    def refreshReferences(self):
        """Force-reload all cached reference modules via the tracker."""
        self.moduleTracker.refresh()
        self.layoutChanged.emit()

    def replaceModule(self, index: QModelIndex, newModule: Module):
        """Replace a module instance at the given index with a new one."""
        oldModule = self.getModule(index)
        if not oldModule:
            return
        
        parentModule = oldModule.parent() or self._rootModule
        
        try:
            row = parentModule.children().index(oldModule)
        except ValueError:
            return
            
        self.beginResetModel()
        parentModule.removeChild(oldModule)
        parentModule.insertChild(row, newModule)
        self.endResetModel()

    def clear(self):
        """Clear all modules from the model."""
        self.beginResetModel()
        self.moduleTracker.clearCache()
        self._rootModule.removeChildren()
        self.endResetModel()

class ModuleTreeWidget(QTreeView):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)

        self.clipboard = []  # Module clipboard for copy/paste
        self.middlePressPos = QPoint()
        
        self.moduleModel = ModuleModel()
        self.setModel(self.moduleModel)

        self.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.header().setSectionResizeMode(QHeaderView.ResizeToContents)

        self.setDragEnabled(False) # Handle manually via middle button
        self.setAcceptDrops(True)
        self.setDropIndicatorShown(True)

        self.setIndentation(16)
        self.setEditTriggers(QAbstractItemView.DoubleClicked | QAbstractItemView.EditKeyPressed)

    def clear(self):
        """Clear the tree by resetting the model."""
        self.moduleModel.clear()

    def mousePressEvent(self, event: QMouseEvent):
        if event.button() == Qt.MiddleButton:
            self.middlePressPos = event.pos()
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event: QMouseEvent):
        if event.buttons() & Qt.MiddleButton:
            if (event.pos() - self.middlePressPos).manhattanLength() >= QApplication.startDragDistance():
                self._startDrag()
                self.middlePressPos = QPoint()
                event.accept()
                return
        super().mouseMoveEvent(event)

    def _startDrag(self):
        selectedIndices = self.selectionModel().selectedRows()
        if not selectedIndices: return

        mimeData = self.moduleModel.mimeData(selectedIndices)
        drag = QDrag(self)
        drag.setMimeData(mimeData)
        drag.exec(Qt.MoveAction)

    def dropEvent(self, event: QDropEvent):
        if event.source() == self:
            event.setDropAction(Qt.CopyAction) # Prevents Qt from double-removing items
        super().dropEvent(event)

    def drawRow(self, painter: QPainter, option: QStyleOptionViewItem, index: QModelIndex):
        if self.selectionModel().isSelected(index):
            fullRowRect = QRect(0, option.rect.y(), self.viewport().width(), option.rect.height())
            painter.fillRect(fullRowRect, self.palette().highlight())
            option.palette.setBrush(QPalette.Highlight, QBrush(Qt.transparent, Qt.NoBrush))
        else:
            option.palette.setBrush(QPalette.Highlight, self.palette().highlight())
        super().drawRow(painter, option, index)

    def wheelEvent(self, event: QWheelEvent):
        ctrl = event.modifiers() & Qt.ControlModifier

        if ctrl:
            delta = event.angleDelta().y()
            if delta == 0:
                return
                
            d = delta / abs(delta)
            font = self.font()
            sz = clamp(fontSize(font) + d, 6, 20)
            setFontSize(font, sz)
            self.setFont(font)
            
            # Scale indentation proportionally
            self.setIndentation(sz * 1.5)
            event.accept()
        else:
            super().wheelEvent(event)

    def contextMenuEvent(self, event: QContextMenuEvent):
        mainWindow.menu().popup(event.globalPos())

    def selectedModules(self) -> List[Module]:
        return [self.moduleModel.getModule(idx) for idx in self.selectionModel().selectedRows()]

    def currentModule(self) -> Optional[Module]:
        selectedIndices = self.selectionModel().selectedRows()
        if not selectedIndices:
            return None
        
        # If current index is among selected, return it.
        # Otherwise return the first selected one.
        curr = self.currentIndex()
        if curr.isValid() and self.selectionModel().isSelected(curr):
            return self.moduleModel.getModule(curr)
        
        return self.moduleModel.getModule(selectedIndices[0])

    def _getTreeState(self) -> dict:
        """Collect expansion paths, selection paths, and current index path in a single pass."""
        state = {
            "expanded": set(),
            "selected": [],
            "current": None
        }
        
        # Save current index path
        curr = self.currentIndex()
        if curr.isValid():
            path = []
            tmp = curr
            while tmp.isValid():
                m = self.moduleModel.getModule(tmp)
                if m: path.insert(0, m.name())
                tmp = tmp.parent()
            state["current"] = tuple(path)

        def walk(index: QModelIndex, path: Tuple[str, ...]):
            if self.isExpanded(index):
                state["expanded"].add(path)
            if self.selectionModel().isSelected(index):
                state["selected"].append(path)
            
            for row in range(self.moduleModel.rowCount(index)):
                childIdx = self.moduleModel.index(row, 0, index)
                m = self.moduleModel.getModule(childIdx)
                if m:
                    walk(childIdx, path + (m.name(),))

        for row in range(self.moduleModel.rowCount()):
            idx = self.moduleModel.index(row, 0)
            m = self.moduleModel.getModule(idx)
            if m:
                walk(idx, (m.name(),))
        
        return state

    def _setTreeState(self, state: dict):
        """Restore tree state (expansion, selection, current index) in a single pass."""
        self.selectionModel().clearSelection()
        selection = QItemSelection()
        expanded = state.get("expanded", set())
        selected = state.get("selected", [])
        currentPath = state.get("current")

        def walk(index: QModelIndex, path: Tuple[str, ...]):
            if path in expanded:
                self.setExpanded(index, True)
            if path in selected:
                selection.select(index, index)
            if currentPath == path:
                self.setCurrentIndex(index)

            for row in range(self.moduleModel.rowCount(index)):
                childIdx = self.moduleModel.index(row, 0, index)
                m = self.moduleModel.getModule(childIdx)
                if m:
                    walk(childIdx, path + (m.name(),))

        for row in range(self.moduleModel.rowCount()):
            idx = self.moduleModel.index(row, 0)
            m = self.moduleModel.getModule(idx)
            if m:
                walk(idx, (m.name(),))
        
        if not selection.isEmpty():
            self.selectionModel().select(selection, QItemSelectionModel.Select | QItemSelectionModel.Rows)
        
        # Force header to recalculate column widths
        self.header().doItemsLayout()

    def replaceModule(self, index: QModelIndex, newModule: Module):
        """Replace a module instance at the given index, preserving expansion and selection state."""
        if not index.isValid():
            return
        
        state = self._getTreeState()
        self.moduleModel.replaceModule(index, newModule)
        self._setTreeState(state)

    def insertModule(self):
        m = Module()
        m.setName("module")
        
        # Add to root if nothing selected or current index is invalid
        parentIdx = self.currentIndex()
        if not self.selectionModel().hasSelection() or not parentIdx.isValid():
             parentIdx = QModelIndex()
        
        newIdx = self.moduleModel.addModuleAt(m, parentIdx)
        if parentIdx.isValid():
            self.setExpanded(parentIdx, True)
        self.setCurrentIndex(newIdx)
        self.scrollTo(newIdx)

    def importModule(self):
        filePath, _ = QFileDialog.getOpenFileName(self.window(), "Import", settings.modulesPath, "Module files (*.rb *.xml);;All files (*)")
        if not filePath:
            return

        try:
            m = Module.loadModule(filePath)
            self.moduleModel.addModuleAt(m)
        except ET.ParseError:
            logger.error(f"'{filePath}': invalid module")
            self.window().showLog()

    def importScript(self):
        filePath, _ = QFileDialog.getOpenFileName(self.window(), "Import script", settings.modulesPath, "Python (*.py);;All files (*)")
        if not filePath:
            return

        with open(filePath, "r", encoding="utf-8") as f:
            code = f.read()

        name = os.path.splitext(os.path.basename(filePath))[0]
        m = Module()
        m.setName(name)
        m.setRunCode(code)
        
        newIdx = self.moduleModel.addModuleAt(m)
        self.setCurrentIndex(newIdx)

    def saveModules(self, forceDialog: bool = False, generateNewUids: bool = False):
        selectedIndices = self.selectionModel().selectedRows()
        if not selectedIndices:
            return

        saveData = [] # List of (module, outputPath, index)

        # 1. Collect target paths and show file dialogs if needed
        for idx in selectedIndices:
            module = self.moduleModel.getModule(idx)
            outputPath = None
            
            if not forceDialog:
                outputPath = module.referenceFile()

            if not outputPath:
                initialPath = os.path.join(settings.modulesPath, module.name())
                title = "Save as " + module.name() if forceDialog else "Save " + module.name()
                outputPath, _ = QFileDialog.getSaveFileName(self.window(), title, initialPath, "Module files (*.rb *.xml)")

            if outputPath:
                saveData.append((module, outputPath, idx))

        if not saveData:
            return

        # 2. Confirmation / Commit message
        historyWidget = self.window().moduleHistoryBrowser
        historyEnabled = historyWidget.isHistoryTrackingEnabled()
        commitMessage = ""

        # Build list for description
        desc = "Save modules?\n" + "\n".join(["{} -> {}".format(m.name(), relativePath(p, settings.modulesPath)) for m, p, _ in saveData])

        if historyEnabled:
            modulesToSave = [m for m, _, _ in saveData]
            accepted, commitMessage = historyWidget.showCommitMessageDialog(
                diffText=calculateModulesDiff(modulesToSave),
                description=desc
            )
            if not accepted:
                return
        else:
            if QMessageBox.question(self.window(), "Rig Builder", desc, QMessageBox.Yes | QMessageBox.No, QMessageBox.Yes) != QMessageBox.Yes:
                return

        # 3. Perform the actual save
        for module, outputPath, idx in saveData:
            dirname = os.path.dirname(outputPath)
            if not os.path.exists(dirname):
                os.makedirs(dirname)

            try:
                module.saveToFile(outputPath, newUid=generateNewUids)
            except Exception as e:
                QMessageBox.critical(self.window(), "Rig Builder", "Can't save module '{}': {}".format(module.name(), str(e)))
            else:
                if historyEnabled:
                    if not moduleHistoryBrowser.recordModuleSave(module, commitMessage):
                        QMessageBox.critical(self.window(), "Rig Builder", "Can't save history for '{}'".format(module.name()))
                
                self.moduleModel.dataChanged.emit(idx, idx) # refresh display
                self.window().attributesTabWidget.updateWidgetStyles()

        self.window().moduleHistoryBrowser.syncModuleHistory()

    def embedModule(self):
        modules = self.selectedModules()
        if not modules:
            return

        msg = "\n".join([m.name() for m in modules])

        if QMessageBox.question(self.window(), "Rig Builder", "Embed modules?\n"+msg, QMessageBox.Yes | QMessageBox.No, QMessageBox.Yes) != QMessageBox.Yes:
            return

        selectedIndices = self.selectionModel().selectedRows()
        for idx in selectedIndices:
            module = self.moduleModel.getModule(idx)
            module.embed()
            self.moduleModel.dataChanged.emit(idx, idx)

    def syncAllModules(self):
        """Full refresh of the entire tree from disk while preserving expansion state."""
        state = self._getTreeState()
        self.moduleModel.refreshReferences()
        
        self.moduleModel.beginResetModel()
        self.moduleModel.rootModule().sync()
        self.moduleModel.endResetModel()
        
        self._setTreeState(state)

        # Refresh attributes panel if needed
        module = self.currentModule()
        if module:
            mainWindow.attributesTabWidget.updateTabs(module)

    def syncModule(self, filePath: str):
        """Sync specific module(s) from disk."""
        
        def walk(module: Module):
            if module.referenceFile() == filePath:
                module.sync()
            
            for ch in module.children():
                walk(ch)

        state = self._getTreeState()
        self.moduleModel.beginResetModel()

        walk(self.moduleModel.rootModule())
        
        self.moduleModel.endResetModel()
        self._setTreeState(state)

        # Refresh attributes panel if needed
        module = self.currentModule()
        if module:
            mainWindow.attributesTabWidget.updateTabs(module)

    def syncSelectedModules(self):
        """Sync selected modules with the files on disk with confirmation."""
        selectedIndices = self.selectionModel().selectedRows()
        if not selectedIndices:
            return

        msg = "Sync selected modules with the files on disk?\n\nYou may lose unsaved changes for those modules.\n\nContinue?"
        if QMessageBox.question(self.window(), "Rig Builder", msg, QMessageBox.Yes | QMessageBox.No, QMessageBox.Yes) != QMessageBox.Yes:
            return

        state = self._getTreeState()
        self.moduleModel.beginResetModel()
        for idx in selectedIndices:
            module = self.moduleModel.getModule(idx)
            if module:
                module.sync()
        self.moduleModel.endResetModel()
        self._setTreeState(state)

        # Refresh attributes panel if needed
        module = self.currentModule()
        if module:
            mainWindow.attributesTabWidget.updateTabs(module)

    def muteModule(self):
        selectedIndices = self.selectionModel().selectedRows()
        if not selectedIndices:
            return

        for idx in selectedIndices:
            module = self.moduleModel.getModule(idx)
            if module.muted():
                module.unmute()
            else:
                module.mute()
        
        self.moduleModel.layoutChanged.emit() # Refresh all to redraw descendants

    def duplicateModule(self):
        # Sort indices by row descending to avoid index shifting issues during insertion
        rows = sorted(self.selectionModel().selectedRows(0), key=lambda x: x.row(), reverse=True)
        if not rows:
            return

        newIndices = []
        for idx in rows:
            module = self.moduleModel.getModule(idx)
            if not module:
                continue

            # Create copy with a unique name
            parentModule = module.parent() or self.moduleModel.rootModule()
            newModule = module.copy()

            # Insert the new module right after the original one
            parentIdx = idx.parent()
            newIdx = self.moduleModel.addModuleAt(newModule, parentIdx, idx.row() + 1)
            
            if newIdx.isValid():
                newIndices.append(newIdx)
                if parentIdx.isValid():
                    self.setExpanded(parentIdx, True)

        # Select all newly created modules
        if newIndices:
            self.selectionModel().clearSelection()
            for idx in newIndices:
                self.selectionModel().select(idx, QItemSelectionModel.Select | QItemSelectionModel.Rows)

    def copyModules(self):
        """Copy selected modules to clipboard."""
        modules = self.selectedModules()
        if not modules:
            return
            
        self.clipboard = [m.copy() for m in modules]
        
    def cutModules(self):
        """Cut selected modules to clipboard."""
        modules = self.selectedModules()
        if not modules:
            return

        self.clipboard = [m.copy() for m in modules]
        
        self.removeModule(askConfirmation=False)

    def pasteModules(self):
        """Paste modules from clipboard."""
        if not self.clipboard:
            QMessageBox.warning(self, "Rig Builder", "Clipboard is empty.")
            return

        parentIdx = self.currentIndex()
        if not self.selectionModel().hasSelection() or not parentIdx.isValid():
            parentIdx = QModelIndex()
            
        parentModule = self.moduleModel.getModule(parentIdx) or self.moduleModel.rootModule()

        if parentIdx.isValid():
            self.setExpanded(parentIdx, True)

        pastedIndices = []
        for module in self.clipboard:
            newModule = module.copy()
            
            newIdx = self.moduleModel.addModuleAt(newModule, parentIdx)
            pastedIndices.append(newIdx)
        
        # Select pasted items
        self.selectionModel().clearSelection()
        for idx in pastedIndices:
            self.selectionModel().select(idx, QItemSelectionModel.Select | QItemSelectionModel.Rows)
            
    def removeModule(self, *, askConfirmation: bool = True):
        selectedIndices = self.selectionModel().selectedRows()
        if not selectedIndices:
            return

        if askConfirmation:
            modules = self.selectedModules()
            msg = "\n".join([m.name() for m in modules])
            if QMessageBox.question(self.window(), "Rig Builder", "Remove modules?\n"+msg, QMessageBox.Yes | QMessageBox.No, QMessageBox.Yes) != QMessageBox.Yes:
                return

        # Sort indices in reverse order to avoid shifting issues when removing
        sortedIndices = sorted(selectedIndices, key=lambda x: x.row(), reverse=True)
        for idx in sortedIndices:
            self.moduleModel.removeModule(idx)


    def addModule(self, module: "Module") -> "Module":
        """Adds top level module."""
        self.moduleModel.addModuleAt(module)
        return module

    def selectModule(self, module: Module):
        """Find and select a module in the tree view."""
        if not module:
             return
        idx = self.moduleModel.indexForModule(module)
        if idx.isValid():
            self.setCurrentIndex(idx)
            self.scrollTo(idx)


class TemplateSelectorDialog(QDialog):
    selectedTemplate = Signal(str)

    def __init__(self, **kwargs):
        super().__init__(**kwargs)

        self.setWindowTitle("Template Selector")
        self.setGeometry(0, 0, 700, 500)

        layout = QVBoxLayout()
        self.setLayout(layout)

        scrollWidget = QWidget()
        scrollArea = QScrollArea()
        scrollArea.setWidget(scrollWidget)
        scrollArea.setWidgetResizable(True)

        self.gridLayout = QGridLayout()
        scrollWidget.setLayout(self.gridLayout)

        self.gridLayout.setDefaultPositioning(3, Qt.Horizontal)
        self.gridLayout.setColumnStretch(1, 1)

        layout.addWidget(scrollArea)

        self.refreshTemplates()
        centerWindow(self)

    def selectTemplate(self, t: str):
        self.selectedTemplate.emit(t)
        self.done(0)

    def refreshTemplates(self):
        """Rebuild template grid."""
        clearLayout(self.gridLayout)

        for t in sorted(TemplateWidgets.keys()):
            self.gridLayout.addWidget(QLabel(t))
            w  = TemplateWidgets[t]()
            w.setJsonData(w.getDefaultData())
            self.gridLayout.addWidget(w)

            selectBtn = QPushButton("✅ Select")
            selectBtn.clicked.connect(partial(self.selectTemplate, t))
            self.gridLayout.addWidget(selectBtn)

class DragHandleButton(QPushButton):
    dragged = Signal()

    def __init__(self, parent=None):
        super().__init__("↕️", parent)        
        self.setToolTip("Drag to reorder")
        self.dragging = False

    def mousePressEvent(self, event: QMouseEvent):
        if event.button() == Qt.LeftButton:
            self.dragging = True
            self.setCursor(Qt.SizeVerCursor)
            self.setStyleSheet("background-color: #6496ff; color: white;")
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event: QMouseEvent):
        if self.dragging:
            self.dragged.emit()
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event: QMouseEvent):
        if event.button() == Qt.LeftButton:
            self.dragging = False
            self.unsetCursor()
            self.setStyleSheet("")
        super().mouseReleaseEvent(event)

class EditTemplateWidget(QWidget):
    Clipboard = []
    nameChanged = Signal(str, str)

    def __init__(self, name: str, template: str, **kwargs):
        super().__init__(**kwargs)

        self.template = template
        self.attrConnect = ""
        self.attrExpression = ""

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0,0,0,0)

        self.nameWidget = QLabel(name)
        self.nameWidget.setAlignment(Qt.AlignRight)
        self.nameWidget.setFixedWidth(self.fontMetrics().averageCharWidth()*20)
        self.nameWidget.setCursor(Qt.PointingHandCursor)
        self.nameWidget.mouseDoubleClickEvent = self.nameMouseDoubleClickEvent
        self.nameWidget.contextMenuEvent = self.nameContextMenuEvent

        self.templateWidget = TemplateWidgets[template]()

        self.dragBtn = DragHandleButton()
        self.dragBtn.setFixedSize(35, 30)
        self.dragBtn.dragged.connect(self._onDragged)

        self.removeBtn = QPushButton("❌")
        self.removeBtn.setFixedSize(35, 30)
        self.removeBtn.setToolTip("Remove attribute")
        self.removeBtn.clicked.connect(self._onRemoveBtnClicked)

        layout.addWidget(self.nameWidget)
        layout.addWidget(self.templateWidget)
        layout.addWidget(self.dragBtn)
        layout.addWidget(self.removeBtn)

    def nameContextMenuEvent(self, event: QContextMenuEvent):
        menu = QMenu(self)
        titleAction = menu.addAction(self.nameWidget.text() or "(Unnamed)")
        titleAction.setEnabled(False)
        font = titleAction.font()
        font.setBold(True)
        titleAction.setFont(font)
        menu.addSeparator()

        menu.addAction("Copy", self.copyTemplate)

        if EditTemplateWidget.Clipboard and EditTemplateWidget.Clipboard[0]["template"] == self.template:
            menu.addAction("Paste", partial(self.templateWidget.setJsonData, EditTemplateWidget.Clipboard[0]["data"]))

        menu.addSeparator()
        presetsMenu = menu.addMenu("Presets")
        presetsMenu.addAction("Manage Presets...", PresetEditorDialog(parent=self).exec)
        presetsMenu.addAction("Save as Preset...", self._saveAsPreset) 

        presets = WidgetPresetManager.presets()
        if presets:
            matchingPresets = {name: data for name, data in presets.items() if data["template"] == self.template}
            if matchingPresets:
                presetsMenu.addSeparator()
                for name, data in sorted(matchingPresets.items()):
                    presetsMenu.addAction(name, partial(self._applyPreset, data))

        menu.popup(event.globalPos())

    def _applyPreset(self, presetData: dict):
        data = presetData["data"]
        self.templateWidget.setJsonData(data)

    def _saveAsPreset(self):
        name, ok = QInputDialog.getText(self, "Save Preset", "Preset name:", QLineEdit.Normal, self.nameWidget.text())
        if ok and name:
            WidgetPresetManager.savePreset(name, self.template, self.templateWidget.getJsonData())

    def copyTemplate(self):
        module = {"data": self.templateWidget.getJsonData(),
                  "template": self.template,
                  "name": self.nameWidget.text()}

        EditTemplateWidget.Clipboard = [module]

    def nameMouseDoubleClickEvent(self, event: QMouseEvent):
        oldName = self.nameWidget.text()
        newName, ok = QInputDialog.getText(self, "Rig Builder", "New name", QLineEdit.Normal, oldName)
        if ok:
            newName = replaceSpecialChars(newName)
            self.nameWidget.setText(newName)
            self.nameChanged.emit(oldName, newName)

    def _onRemoveBtnClicked(self):
        if QMessageBox.question(self, "Rig Builder", "Remove '{}' attribute?".format(self.nameWidget.text()), QMessageBox.Yes | QMessageBox.No, QMessageBox.Yes) == QMessageBox.Yes:
            self.copyTemplate()
            self.deleteLater()

    def _onDragged(self) -> bool:
        editAttrsWidget = self.parent()
        layout = editAttrsWidget.attributesLayout
        idx = layout.indexOf(self)
        mouseY = QCursor.pos().y()

        # Check neighbor below
        if idx < layout.count() - 1:
            neighbor = layout.itemAt(idx + 1).widget()
            if neighbor:
                neighborCenterY = neighbor.mapToGlobal(neighbor.rect().center()).y()
                if mouseY > neighborCenterY:
                    layout.insertWidget(idx + 1, self)
                    return True

        # Check neighbor above
        if idx > 0:
            neighbor = layout.itemAt(idx - 1).widget()
            if neighbor:
                neighborCenterY = neighbor.mapToGlobal(neighbor.rect().center()).y()
                if mouseY < neighborCenterY:
                    layout.insertWidget(idx - 1, self)
                    return True
        return False

class EditAttributesWidget(QWidget):
    nameChanged = Signal(str, str)
    RecentTemplates = []

    def __init__(self, module: Module, category: str, **kwargs):
        super().__init__(**kwargs)

        self.category = category
        self.module = module
        if not self.module:
             return

        layout = QVBoxLayout()
        self.setLayout(layout)

        self.attributesLayout = QVBoxLayout()
        self.placeholderWidget = QLabel("Right-click to add attributes")
        self.placeholderWidget.setAlignment(Qt.AlignCenter)
        self.placeholderWidget.setStyleSheet("color: gray;")

        for a in self.module.attributes():
            if a.category() == self.category:
                w = self.insertCustomWidget(a.template())
                w.nameWidget.setText(a.name())
                w.templateWidget.setJsonData(a.localData())
                w.attrConnect = a.connect()
                w.attrExpression = a.expression()

        layout.addWidget(self.placeholderWidget)
        layout.addLayout(self.attributesLayout)
        layout.addStretch()

    def contextMenuEvent(self, event: QContextMenuEvent):
        menu = QMenu(self)

        menu.addAction("Add", self.addTemplateAttribute)
        menu.addAction("Copy visible", self.copyVisibleAttributes)

        if EditTemplateWidget.Clipboard:
            menu.addAction("Paste", self.pasteAttribute)

        menu.addSeparator()

        presetsMenu = menu.addMenu("Presets")
        presetsMenu.addAction("Manage Presets...", PresetEditorDialog(parent=self).exec)
        
        presets = WidgetPresetManager.presets()
        if presets:
            presetsMenu.addSeparator()
            for name, data in sorted(presets.items()):
                presetsMenu.addAction(f"{name} ({data['template']})", partial(self._addFromPreset, name, data))        

        if EditAttributesWidget.RecentTemplates:
            menu.addSeparator()
            titleAction = menu.addAction("Recent")
            titleAction.setEnabled(False)
            font = titleAction.font()
            font.setBold(True)
            titleAction.setFont(font)
            for t in EditAttributesWidget.RecentTemplates:
                menu.addAction("  " + t, partial(self._onTemplateSelected, t))

        menu.popup(event.globalPos())

    def _addFromPreset(self, presetName: str, presetData: dict):
        template = presetData["template"]
        data = presetData["data"]
        w = self.insertCustomWidget(template)
        if w:
            w.templateWidget.setJsonData(data)
            # Find unique name for the new attribute
            existingNames = {self.attributesLayout.itemAt(k).widget().nameWidget.text() for k in range(self.attributesLayout.count()) if self.attributesLayout.itemAt(k).widget()}
            w.nameWidget.setText(findUniqueName(presetName, existingNames))

    def copyVisibleAttributes(self):
        EditTemplateWidget.Clipboard = []

        for k in range(self.attributesLayout.count()):
            w = self.attributesLayout.itemAt(k).widget()
            module = {"data": w.templateWidget.getJsonData(),
                      "name": w.nameWidget.text(),
                      "template": w.template}
            EditTemplateWidget.Clipboard.append(module)

    def pasteAttribute(self):
        for module in EditTemplateWidget.Clipboard:
            w = self.insertCustomWidget(module["template"])
            w.templateWidget.setJsonData(module["data"])
            w.nameWidget.setText(module["name"])

    def _onTemplateSelected(self, template: str):
        if template in EditAttributesWidget.RecentTemplates:
            EditAttributesWidget.RecentTemplates.remove(template)
        EditAttributesWidget.RecentTemplates.insert(0, template)
        EditAttributesWidget.RecentTemplates = EditAttributesWidget.RecentTemplates[:5]
        self.insertCustomWidget(template)

    def addTemplateAttribute(self):
        selector = TemplateSelectorDialog(parent=self)
        selector.selectedTemplate.connect(self._onTemplateSelected)
        selector.exec()

    def insertCustomWidget(self, template: str, row: Optional[int] = None) -> Optional[EditTemplateWidget]:
        if not TemplateWidgets.get(template):
            return

        row = self.attributesLayout.count() if row is None else row
        w = EditTemplateWidget("attr{}".format(row+1), template)
        w.templateWidget.setJsonData(w.templateWidget.getDefaultData())
        w.nameChanged.connect(self.nameChanged.emit)
        self.attributesLayout.insertWidget(row, w)
        return w

    def resizeNameFields(self):
        fontMetrics = self.fontMetrics()
        maxWidth = max([getFontWidth(fontMetrics, self.attributesLayout.itemAt(k).widget().nameWidget.text()) for k in range(self.attributesLayout.count())])
        for k in range(self.attributesLayout.count()):
            w = self.attributesLayout.itemAt(k).widget()
            w.nameWidget.setFixedWidth(maxWidth)

class EditAttributesTabWidget(QTabWidget):
    def __init__(self, module: Module, currentIndex: int = 0, **kwargs):
        super().__init__(**kwargs)

        self.module = module
        if not self.module:
            self.setEnabled(False)
            return

        self.tempRunCode = self.module.runCode()

        self.setMovable(True)
        self.setTabsClosable(True)
        self.tabBarDoubleClicked.connect(self._onTabBarDoubleClicked)
        self.tabCloseRequested.connect(self._onTabCloseRequested)

        tabTitlesInOrder = []
        for a in self.module.attributes():
            if a.category() not in tabTitlesInOrder:
                tabTitlesInOrder.append(a.category())

        for t in tabTitlesInOrder:
            self.addTabCategory(t)

        if self.count() == 0:
            self.addTabCategory("General")

        self.setCurrentIndex(currentIndex)

    def addTabCategory(self, category: str):
        w = EditAttributesWidget(self.module, category)
        w.nameChanged.connect(self._onNameChanged)

        scrollArea = QScrollArea()
        scrollArea.setWidget(w)
        scrollArea.setWidgetResizable(True)
        self.addTab(scrollArea, category)
        self.setCurrentIndex(self.count()-1)

    def _onNameChanged(self, oldName: str, newName: str):
        sameAttrs = []
        for i in range(self.count()): # find other attributes with the same name, if any, then don't rename in code and connections
            attrsLayout = self.widget(i).widget().attributesLayout # tab/scrollArea/EditAttributesWidget

            for k in range(attrsLayout.count()):
                w = attrsLayout.itemAt(k).widget()
                attrName = w.nameWidget.text()
                if attrName == oldName:
                    sameAttrs.append(w)

        if oldName.strip() and not sameAttrs:
            pairs = [("@\\b{}\\b".format(oldName), "@"+newName),
                     ("@\\bset_{}\\b".format(oldName), "@set_"+newName),
                     ("@\\b{}_data\\b".format(oldName), "@"+newName+"_data")]

            self.tempRunCode = replacePairs(pairs, self.tempRunCode)

            # rename in connections
            attr = self.module.findAttribute(oldName)
            if attr:
                for a in attr.listConnections():
                    c = self.module.path().replace(attr.module().path(inclusive=False), "") + "/" + newName # update connection path
                    a.setConnect(c)

    def _onTabBarDoubleClicked(self, idx: int):
        newName, ok = QInputDialog.getText(self, "Rig Builder", "New name", QLineEdit.Normal, self.tabText(idx))
        if ok:
            self.setTabText(idx, newName)

    def _onTabCloseRequested(self, i: int):
        if QMessageBox.question(self, "Rig Builder", "Remove '{}' tab?".format(self.tabText(i)), QMessageBox.Yes | QMessageBox.No, QMessageBox.Yes) == QMessageBox.Yes:
            self.setCurrentIndex(i-1)
            self.clearTab(i)

    def contextMenuEvent(self, event: QContextMenuEvent):
        menu = QMenu(self)
        menu.addAction("New tab", partial(self.addTabCategory, "Untitled"))
        menu.popup(event.globalPos())

    def clearTab(self, i: int):
        self.widget(i).deleteLater()
        self.removeTab(i)

    def clearTabs(self):
        for _ in range(self.count()):
            self.clearTab(0)

class EditAttributesDialog(QDialog):
    def __init__(self, module: Module, currentIndex: int = 0, **kwargs):
        super().__init__(**kwargs)

        self.module = module
        self.setWindowTitle("Edit Attributes - " + self.module.name())
        self.setGeometry(0, 0, 800, 600)

        layout = QVBoxLayout()
        self.setLayout(layout)

        self.tabWidget = EditAttributesTabWidget(self.module, currentIndex)

        okBtn = QPushButton("✅ OK")
        okBtn.clicked.connect(self.saveAttributes)
        cancelBtn = QPushButton("❌ Cancel")
        cancelBtn.clicked.connect(self.close)

        hlayout = QHBoxLayout()
        hlayout.addWidget(okBtn)
        hlayout.addWidget(cancelBtn)

        layout.addWidget(self.tabWidget)
        layout.addLayout(hlayout)

        centerWindow(self)

    def saveAttributes(self):
        module = self.module

        def attrMetaEqual(a: Attribute, b: Attribute) -> bool:
            return (a.name() == b.name()
                    and a.category() == b.category()
                    and a.template() == b.template()
                    and a.connect() == b.connect()
                    and a.expression() == b.expression()
                    and a.localData() == b.localData())

        origAttrs = list(module.attributes())
        origByName = {a.name(): a for a in origAttrs if a.name()}

        newAttrs = self.buildAttributesFromTabs()
        newRunCode = self.tabWidget.tempRunCode

        module.removeAttributes()

        for a in newAttrs:
            module.addAttribute(a)

        if module.runCode() != newRunCode:
            module.setRunCode(newRunCode)

        self.accept()

    def buildAttributesFromTabs(self) -> List[Attribute]:
        attrs = []
        for i in range(self.tabWidget.count()):
            attrsLayout = self.tabWidget.widget(i).widget().attributesLayout
            category = self.tabWidget.tabText(i)

            for k in range(attrsLayout.count()):
                w = attrsLayout.itemAt(k).widget()

                a = Attribute()
                a._name = w.nameWidget.text()
                a._category = category
                a._template = w.template
                a._connect = w.attrConnect
                a._expression = w.attrExpression
                a._data = copyJson(w.templateWidget.getJsonData())
                attrs.append(a)

        return attrs

class CodeEditorWidget(CodeEditorWithNumbersWidget):
    def __init__(self, module: Optional[Module] = None, **kwargs):
        super().__init__(**kwargs)

        self.module = module
        self._skipSaving = False

        self.editorWidget.textChanged.connect(self._onCodeChanged)

        self.updateState()

    def _onCodeChanged(self):
        if not self.module or self._skipSaving:
            return

        self.module.setRunCode(self.editorWidget.toPlainText())

    def updateState(self):
        if not self.module:
            self.editorWidget.clear()
            return

        self.editorWidget.ignoreStates = True
        self._skipSaving = True
        self.editorWidget.setText(self.module.runCode())
        self._skipSaving = False
        self.editorWidget.ignoreStates = False

        self.editorWidget.document().clearUndoRedoStacks()
        self.generateCompletionWords()

        self.editorWidget.preset = self.module.path()
        self.editorWidget.loadState()

    def generateCompletionWords(self):
        if not self.module:
            return

        words = set(self.module.context().keys())

        for a in self.module.attributes():
            words.add("@" + a.name())
            words.add("@" + a.name() + "_data")
            words.add("@set_" + a.name())

        self.editorWidget.words = words

class LogHighligher(QSyntaxHighlighter):
    def __init__(self, parent: QTextDocument):
        super().__init__(parent)

        self.highlightingRules = []

        warningFormat = QTextCharFormat()
        warningFormat.setForeground(QColor(250, 150, 90))
        self.highlightingRules.append(("(?i)\\b\\w*warning\\b", warningFormat))

        errorFormat = QTextCharFormat()
        errorFormat.setForeground(QColor(250, 90, 90))
        self.highlightingRules.append(("(?i)\\b\\w*error\\b", errorFormat))

    def highlightBlock(self, text: str):
        for pattern, format in self.highlightingRules:
            if not pattern:
                continue

            expression = QRegularExpression(pattern)
            iterator = expression.globalMatch(text)
            while iterator.hasNext():
                match = iterator.next()
                self.setFormat(match.capturedStart(), match.capturedLength(), format)

        self.setCurrentBlockState(0)

class LogWidget(QTextEdit):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)

        self.syntax = LogHighligher(self.document())
        self.setPlaceholderText("Output and errors or warnings...")
        self.setReadOnly(True)

    def contextMenuEvent(self, event: QContextMenuEvent):
        menu = self.createStandardContextMenu()
        menu.addSeparator()
        menu.addAction("Clear log", self.clear)
        menu.popup(event.globalPos())

    def write(self, txt: str):
        self.moveCursor(QTextCursor.End)
        self.insertPlainText(txt)
        self.ensureCursorVisible()

    def flush(self):
        return


class REPLWidget(QLineEdit):
    executionRequested = Signal(str)

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.setPlaceholderText("Python REPL (host side)...")
        self._history = []
        self._historyIndex = -1
        self._currentText = ""

    def keyPressEvent(self, event: QKeyEvent):
        if event.key() == Qt.Key_Return or event.key() == Qt.Key_Enter:
            code = self.text().strip()
            if code:
                if not self._history or self._history[-1] != code:
                    self._history.append(code)
                self._historyIndex = -1
                self.executionRequested.emit(code)
                self.clear()
            return

        if event.key() == Qt.Key_Up:
            if not self._history:
                return
            if self._historyIndex == -1:
                self._currentText = self.text()
                self._historyIndex = len(self._history) - 1
            elif self._historyIndex > 0:
                self._historyIndex -= 1
            
            self.setText(self._history[self._historyIndex])
            return

        if event.key() == Qt.Key_Down:
            if self._historyIndex == -1:
                return
            
            if self._historyIndex < len(self._history) - 1:
                self._historyIndex += 1
                self.setText(self._history[self._historyIndex])
            else:
                self._historyIndex = -1
                self.setText(self._currentText)
            return

        super().keyPressEvent(event)


class WideSplitterHandle(QSplitterHandle):
    def __init__(self, orientation: Qt.Orientation, parent: QWidget, **kwargs):
        super().__init__(orientation, parent, **kwargs)
        self.hovered = False

    def enterEvent(self, event: QEvent):
        self.hovered = True
        self.update()
        super().enterEvent(event)

    def leaveEvent(self, event: QEvent):
        self.hovered = False
        self.update()
        super().leaveEvent(event)

    def paintEvent(self, event: QPaintEvent):
        if not self.hovered:
            return

        painter = QPainter()
        if painter.begin(self):
            try:
                # Solid accent color on hover, no patterns
                painter.fillRect(event.rect(), QColor(110, 167, 255, 60))
            finally:
                painter.end()

class WideSplitter(QSplitter):
    def __init__(self, orientation: Qt.Orientation, width: int = 8, **kwargs):
        super().__init__(orientation, **kwargs)
        self.setHandleWidth(width)

    def createHandle(self) -> QSplitterHandle:
        return WideSplitterHandle(self.orientation(), self)

class MyProgressBar(QWidget):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)

        self.queue = []
        self.labelSize = 25

        layout = QHBoxLayout()
        self.setLayout(layout)
        layout.setContentsMargins(0, 0, 0, 0)

        self.labelWidget = QLabel()
        self.progressBarWidget = QProgressBar()
        layout.addWidget(self.labelWidget)
        layout.addWidget(self.progressBarWidget)

    def initialize(self):
        self.queue = []

    def updateWithState(self, state: dict[str, object]):
        trimText = lambda text, size: "..." + text[-size+3:]  if len(text) > size else " "*(size-len(text)) + text
        self.labelWidget.setText(trimText(state["text"], self.labelSize))
        self.progressBarWidget.setValue(state["value"])
        self.progressBarWidget.setMaximum(state["max"])

    def beginProgress(self, text: str, count: int, updatePercent: float = 0.01):
        q = {"text": text, "max": count, "value": 0, "updatePercent":updatePercent}
        self.queue.append(q)
        self.updateWithState(q)
        self.show()

    def stepProgress(self, value: int, text: Optional[str] = None):
        if not self.queue:
            return
        q = self.queue[-1]
        q["value"] = value

        updateValue = int(clamp(q["max"] * q["updatePercent"], 1, q["max"]))

        if not q["updatePercent"] or value % updateValue == 0:
            if text:
                q["text"] = text
            self.updateWithState(q)
            QApplication.processEvents()

    def endProgress(self):
        if not self.queue:
            return
        self.queue.pop()
        if not self.queue:
            self.hide()
        else:
            q = self.queue[-1] # get latest state
            self.updateWithState(q)

# --- Host Settings Dialog ---
class HostManagerDialog(QDialog):
    hostsChanged = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Host Manager")
        self.resize(500, 480)
        
        mainLayout = QVBoxLayout(self)
        mainLayout.setSpacing(15)
        mainLayout.setContentsMargins(20, 20, 20, 20)

        # 1. Discovery Server Settings
        discoveryGroup = QGroupBox("Discovery Server")
        discoveryLayout = QVBoxLayout(discoveryGroup)
        discoveryLayout.setSpacing(10)
        
        infoLabel = QLabel("Rig Builder listens on this port for host registrations.")
        infoLabel.setStyleSheet("color: #888; font-size: 10px;")
        discoveryLayout.addWidget(infoLabel)

        portRow = QHBoxLayout()
        portRow.addWidget(QLabel("Discovery Port:"))
        self.discoveryPortEdit = QLineEdit(str(connectionManager.discoveryPort))
        self.discoveryPortEdit.setValidator(QIntValidator(1, 65535))
        self.discoveryPortEdit.setFixedWidth(80)
        portRow.addWidget(self.discoveryPortEdit)
        portRow.addStretch()
        
        self.savePortBtn = QPushButton("Save && Restart")
        self.savePortBtn.setFixedWidth(120)
        self.savePortBtn.clicked.connect(self._saveDiscoveryPort)
        portRow.addWidget(self.savePortBtn)
        discoveryLayout.addLayout(portRow)
        
        mainLayout.addWidget(discoveryGroup)

        # 2. Startup Code Generator
        generatorGroup = QGroupBox("Host Startup Code Generator")
        generatorLayout = QVBoxLayout(generatorGroup)
        generatorLayout.setSpacing(10)
        
        genInfoLabel = QLabel("Select a host type to generate the initialization snippet.")
        genInfoLabel.setStyleSheet("color: #888; font-size: 10px;")
        generatorLayout.addWidget(genInfoLabel)

        hostRow = QHBoxLayout()
        hostRow.addWidget(QLabel("Target Host:"))

        self.hostCombo = QComboBox()
        for host in AVAILABLE_HOSTS:
            iconPath = os.path.join(RIG_BUILDER_PATH, "images", f"{host}.png")
            if os.path.exists(iconPath):
                self.hostCombo.addItem(QIcon(iconPath), host.capitalize())
            else:
                self.hostCombo.addItem(host.capitalize())

        self.hostCombo.currentIndexChanged.connect(self._refreshCode)
        hostRow.addWidget(self.hostCombo)
        hostRow.addStretch()
        generatorLayout.addLayout(hostRow)

        codeHeader = QHBoxLayout()
        codeHeader.addWidget(QLabel("Startup Script:"))
        codeHeader.addStretch()
        self.copyBtn = QPushButton("📋")
        self.copyBtn.setFixedWidth(40)
        self.copyBtn.clicked.connect(self._copyCode)
        codeHeader.addWidget(self.copyBtn)
        generatorLayout.addLayout(codeHeader)

        self.codeEdit = QPlainTextEdit()
        self.codeEdit.setReadOnly(True)
        # Use a monospace font for code
        font = QFont("Consolas", 10) if sys.platform == "win32" else QFont("Monospace", 10)
        self.codeEdit.setFont(font)
        self.codeEdit.setStyleSheet("background-color: #1e1e1e; color: #d4d4d4; border: 1px solid #333; border-radius: 4px;")
        generatorLayout.addWidget(self.codeEdit)
        
        mainLayout.addWidget(generatorGroup)

        # Bottom Buttons
        buttonBox = QDialogButtonBox(QDialogButtonBox.Close)
        buttonBox.rejected.connect(self.reject)
        mainLayout.addWidget(buttonBox)

        self._refreshCode()

    def _saveDiscoveryPort(self):
        port_str = self.discoveryPortEdit.text()
        if not port_str:
            return
            
        port = int(port_str)
        connectionManager.setDiscoveryPort(port)
        
        # Visual feedback
        self.savePortBtn.setText("✅ Saved")
        self.savePortBtn.setStyleSheet("color: #4CAF50; font-weight: bold;")
        QTimer.singleShot(2000, self._resetSaveBtn)
        
        self.hostsChanged.emit()
        self._refreshCode()

    def _resetSaveBtn(self):
        self.savePortBtn.setText("Save && Restart")
        self.savePortBtn.setStyleSheet("")

    def _copyCode(self):
        QApplication.clipboard().setText(self.codeEdit.toPlainText())
        self.copyBtn.setText("✅")
        self.copyBtn.setStyleSheet("color: #4CAF50; font-weight: bold;")
        QTimer.singleShot(2000, self._resetCopyBtn)

    def _resetCopyBtn(self):
        self.copyBtn.setText("📋")
        self.copyBtn.setStyleSheet("")

    def _refreshCode(self):
        host = self.hostCombo.currentText().lower()
        HostClass = host.capitalize() + "Server"
        discoveryPort = self.discoveryPortEdit.text() or str(DEFAULT_DISCOVERY_PORT)

        code = HOST_STARTUP_TEMPLATE.format(
            HostClass=HostClass,
            host=host,
            RIG_BUILDER_PATH=os.path.dirname(RIG_BUILDER_PATH),
            discoveryPort=discoveryPort
        )
        self.codeEdit.setPlainText(code)


class RigBuilderWindow(QFrame):
    def __init__(self):
        super().__init__()

        self.logger = logger
        self._refreshingUI = False
        self._progressCounter = 0
        
        self.setWindowTitle("Rig Builder {}".format(__version__))
        self.setGeometry(0, 0, 1300, 900)

        self.setWindowFlags(Qt.Window | Qt.WindowCloseButtonHint | Qt.WindowMinMaxButtonsHint)

        layout = QVBoxLayout()
        self.setLayout(layout)

        # --- Host picker row ---
        self.hostCombo = QComboBox()
        self.hostCombo.setPlaceholderText("No host")
        self.hostCombo.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.hostCombo.currentIndexChanged.connect(self._onHostComboChanged)
        connectionManager.discoveryServer.hostDiscovered.connect(self._refreshHostCombo)

        self.hostManageBtn = QPushButton("⚙️")
        self.hostManageBtn.setToolTip("Manage hosts")
        self.hostManageBtn.clicked.connect(self._onManageHosts)

        self.syncBtn = QPushButton("🔄")
        self.syncBtn.setToolTip("Sync all modules (reset local changes)")
        self.syncBtn.clicked.connect(self._onSyncRequested)

        self.aiChatBtn = QPushButton("💬")
        self.aiChatBtn.setToolTip("AI Chat (Ollama)")
        self.aiChatBtn.clicked.connect(self._onOpenAIChat)
 
        self.workspaceWidget = WorkspaceWidget(parent=self)
        self.workspaceWidget.workspaceChanged.connect(self._onWorkspaceChanged)
        self.workspaceWidget.aboutToChangeWorkspace.connect(self._onAboutToChangeWorkspace)

        self.autoSaveTimer = QTimer(self)
        self.autoSaveTimer.timeout.connect(self._onAutoSaveTimer)

        self.windowPinBtn = QPushButton("📌")
        self.windowPinBtn.setCheckable(True)
        self.windowPinBtn.setToolTip("Pin window (stays on top)")
        self.windowPinBtn.clicked.connect(self.pinWindow)
        self.windowPinBtn.setStyleSheet("QPushButton:checked { background-color: #3e7bd6; border-color: #6ea7ff; color: #ffffff; }")

        headerRow = QHBoxLayout()
        headerRow.addWidget(self.workspaceWidget)
        headerRow.addWidget(self.syncBtn)
        headerRow.addStretch()
        if IS_OLLAMA_AVAILABLE:
            headerRow.addWidget(self.aiChatBtn)
            headerRow.addStretch()
        headerRow.addWidget(self.hostCombo)
        headerRow.addWidget(self.hostManageBtn)
        headerRow.addWidget(self.windowPinBtn)
        layout.addLayout(headerRow)

        self.treeWidget = ModuleTreeWidget()
        self.treeWidget.selectionModel().selectionChanged.connect(self._onTreeSelectionChanged)
        self.treeWidget.addActions(getActions(self.menu()))
        self.treeWidget.setContextMenuPolicy(Qt.CustomContextMenu)
        self.treeWidget.customContextMenuRequested.connect(self._onTreeContextMenu)
        setActionsLocalShortcut(self.treeWidget)

        self.codeEditorWidget = CodeEditorWidget()
        self.codeEditorWidget.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Ignored)
        self.codeEditorWidget.editorWidget.setPlaceholderText("Your module code...")

        for label, func, hotkey in [
            ("Execute", self._onExecuteCode, "Ctrl+Enter"),
            ("Expose as Attribute", self._onExposeAsAttribute, "Ctrl+E")]:            
            action = QAction(label, self.codeEditorWidget.editorWidget)
            action.setShortcut(hotkey)
            action.triggered.connect(lambda *_, f=func: f())
            self.codeEditorWidget.editorWidget.addCustomAction(action)
        
        self.vscodeBtn = QPushButton("📝 Edit in VSCode")
        self.vscodeBtn.clicked.connect(self.editInVSCode)

        self.apiBrowser = ApiBrowser()

        self.attributesTabWidget = AttributesTabWidget()
        self.attributesTabWidget.moduleChanged.connect(lambda *_: self.treeWidget.moduleModel.layoutChanged.emit()) # refresh tree
        self.attributesTabWidget.executionRequested.connect(self._onModuleExecutionRequested)
        self.attributesTabWidget.attributesChanged.connect(self.codeEditorWidget.updateState)

        self.runBtn = QPushButton("🚀 Run")
        self.runBtn.setToolTip("Execute selected module inside the current host.")
        self.runBtn.setStyleSheet("background-color: #3e4f89")
        self.runBtn.clicked.connect(self.runModule)
        self.runBtn.setEnabled(False)

        self.moduleHistoryBrowser = ModuleHistoryBrowser()
        self.moduleHistoryBrowser.moduleAdditionRequested.connect(self._onModuleAdditionRequested)

        self.docBrowser = DocBrowser()
        self.docBrowser.moduleRequested.connect(self.addModuleBySpec)
        self.docBrowser.setEnabled(False)

        self.moduleBrowser = ModuleBrowser()
        self.moduleBrowser.modulesAutoReloadWatcher.fileChanged.connect(self.treeWidget.syncModule)
        
        self.workspaceWidget.updateRequested.connect(self.moduleBrowser.refreshModules)

        self.logWidget = LogWidget()
        self.logWidget.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Ignored)

        self.replWidget = REPLWidget()
        self.replWidget.executionRequested.connect(self._onReplExecute)

        self.progressBarWidget = MyProgressBar()
        self.progressBarWidget.hide()        

        self.aiChatDialog = AIChatDialog(parent=self)
        self.aiChatDialog.replaceCodeRequested.connect(self._onReplaceCodeRequested)
        self.aiChatDialog.replaceSelectedCodeRequested.connect(self._onReplaceSelectedCodeRequested)
        self.aiChatDialog.attributeAdded.connect(self._onAttributeChanged)
        self.aiChatDialog.attributeDataChanged.connect(self._onAttributeChanged)
        self.aiChatDialog.beforeSendMessage.connect(self.prepareContextForChat)

        # layout

        treeWithBtnWidget = QWidget()        
        treeWithBtnWidget.setLayout(QVBoxLayout())
        treeWithBtnWidget.layout().setContentsMargins(0, 0, 0, 0)
        treeWithBtnWidget.layout().addWidget(self.treeWidget)
        treeWithBtnWidget.layout().addWidget(self.runBtn)

        leftSplitter = WideSplitter(Qt.Vertical)
        leftSplitter.addWidget(treeWithBtnWidget)
        leftSplitter.addWidget(self.moduleBrowser)
        leftSplitter.setSizes([500,300])

        codeWithBtnWidget = QWidget()
        codeWithBtnWidget.setLayout(QVBoxLayout())
        codeWithBtnWidget.layout().setContentsMargins(0, 0, 0, 0)
        codeWithBtnWidget.layout().addWidget(self.codeEditorWidget)
        codeWithBtnWidget.layout().addWidget(self.vscodeBtn)

        centerSplitter = WideSplitter(Qt.Vertical)
        centerSplitter.addWidget(self.attributesTabWidget)
        centerSplitter.addWidget(codeWithBtnWidget)
        centerSplitter.setSizes([500, 300])

        rightSplitter = WideSplitter(Qt.Vertical)
        rightSplitter.addWidget(self.docBrowser)
        rightSplitter.addWidget(self.apiBrowser)
        rightSplitter.setSizes([500, 300])

        self.centerRightSplitter = WideSplitter(Qt.Horizontal)
        self.centerRightSplitter.addWidget(centerSplitter)
        self.centerRightSplitter.addWidget(rightSplitter)
        self.centerRightSplitter.setSizes([500, 200])
        self.centerRightSplitter.hide()

        self.toggleWidget = QWidget()
        self.toggleWidget.setLayout(QVBoxLayout())
        self.toggleWidget.layout().setContentsMargins(0, 0, 0, 0)
        self.toggleWidget.layout().addWidget(self.centerRightSplitter)
        self.toggleWidget.layout().addWidget(self.moduleHistoryBrowser)

        mainSplitter = WideSplitter(Qt.Horizontal)
        mainSplitter.addWidget(leftSplitter)
        mainSplitter.addWidget(self.toggleWidget)
        mainSplitter.setSizes([200, 500])

        layoutSplitter = WideSplitter(Qt.Vertical)
        layoutSplitter.addWidget(mainSplitter)
        
        logContainer = QWidget()
        logContainerLayout = QVBoxLayout(logContainer)
        logContainerLayout.setContentsMargins(0, 0, 0, 0)
        logContainerLayout.setSpacing(2)
        logContainerLayout.addWidget(self.logWidget)
        logContainerLayout.addWidget(self.replWidget)
        
        layoutSplitter.addWidget(logContainer)
        layoutSplitter.setSizes([500, 100])

        layout.addWidget(layoutSplitter)
        layout.addWidget(self.progressBarWidget)

        centerWindow(self)

        self.moduleHistoryBrowser.syncModuleHistory()
        self.moduleBrowser.modulesAutoReloadWatcher.setRoots([settings.modulesPath])
        self.moduleBrowser.refreshModules()

        self._splitters = {
            "version": 1,
            "widgets": [
                layoutSplitter,
                mainSplitter,
                leftSplitter,
                rightSplitter,
                centerSplitter,
                self.centerRightSplitter,
            ]
        }
        
        self.loadAppSettings()        
        connectionManager.discoveryServer.hostDiscovered.connect(self._refreshHostCombo)

    def _onTreeContextMenu(self, pos):
        self.menu().exec(self.treeWidget.mapToGlobal(pos))

    def _onModuleExecutionRequested(self, code: str):
        module = self.treeWidget.currentModule()
        if not module:
            return

        newModule = hostExecutor.executeModuleCode(module, code)
        if newModule is None:
            return

        idx = self.treeWidget.moduleModel.indexForModule(module)
        if idx.isValid():
            self.treeWidget.replaceModule(idx, newModule)
            self.attributesTabWidget.updateTabs(newModule)

    def _onReplExecute(self, code: str):
        """Execute general code from REPL on host."""
        if not code:
            return

        self.showLog()
        logger.info(f">> {code}")

        hostExecutor.executeCode(code)

    def _onExecuteCode(self):
        """Execute lines interactively with accumulated context."""        
        module = self.treeWidget.currentModule()
        if not module:
            return

        cursor = self.codeEditorWidget.editorWidget.textCursor()
        code = cursor.selectedText().replace("\u2029", "\n").strip()
        if not code:
            code = self.codeEditorWidget.editorWidget.toPlainText().strip()
        if not code:
            return

        self.showLog()
        
        maxLines = 5
        lines = code.splitlines()
        log = [f">> {line}" for line in lines[:maxLines]]
        if len(lines) > maxLines:
            if len(lines) > maxLines + 1:
                log.append(">> ...")
            log.append(f">> {lines[-1]}") # last line is always shown
            
        logger.info("\n".join(log))

        newModule = hostExecutor.executeModuleCode(module, code)
        if newModule is None:
            return

        idx = self.treeWidget.moduleModel.indexForModule(module)
        if idx.isValid():
            self.treeWidget.replaceModule(idx, newModule)
            self.attributesTabWidget.updateTabs(newModule)

    def _onExposeAsAttribute(self):
        module = self.treeWidget.currentModule()
        if not module:
            return

        cursor = self.codeEditorWidget.editorWidget.textCursor()
        code = cursor.selectedText().replace("\u2029", "\n").strip()
        if not code:
            return

        try:
            v = copyJson(eval(code))
        except:
            QMessageBox.critical(self, "Rig Builder", "Selected value is not JSON-compatible.")
            return

        name, ok = QInputDialog.getText(self, "Rig Builder", "Attribute name to expose:", QLineEdit.Normal)
        if not ok:
            return

        if not name:
            QMessageBox.critical(self, "Rig Builder", "Attribute name must be specified")
            return
        
        if module.findAttribute(name):
            QMessageBox.critical(self, "Rig Builder", "Attribute with this name already exists")
            return        

        category = self.attributesTabWidget.tabText(self.attributesTabWidget.currentIndex())
        attr = getAttributeFromValue(name, v, category)

        module.addAttribute(attr)

        self.attributesTabWidget.updateTabs(module)
        self.codeEditorWidget.editorWidget.textCursor().insertText(f"@{name}")
        logger.info(f"Attribute '{name}' exposed.")

    def _refreshHostCombo(self):
        """Update host selection dropdown based on discovered servers."""
        prevHost = self.hostCombo.currentData() or "Standalone"

        self.hostCombo.blockSignals(True)
        self.hostCombo.clear()

        # Get discovered hosts
        servers = connectionManager.servers()
        entries = sorted(servers.items(), key=lambda x: x[0].lower())
        
        for name, entry in entries:
            # Use icon for discovered hosts
            iconPath = os.path.join(RIG_BUILDER_PATH, "images", f"{entry['host']}.png")
            if os.path.exists(iconPath):
                self.hostCombo.addItem(QIcon(iconPath), name, userData=name)
            else:
                label = "📡 {} ({})".format(name, entry["host"])
                self.hostCombo.addItem(label, userData=name)

        if not servers:
            self.hostCombo.setPlaceholderText("No hosts discovered")
        
        # Try to restore selection
        idx = self.hostCombo.findData(prevHost)
        if idx >= 0:
            self.hostCombo.setCurrentIndex(idx)
        else:
            # If nothing selected, disconnect
            connectionManager.disconnect()
            self.hostCombo.setStyleSheet("")

        self.hostCombo.blockSignals(False)

        # If we have a selection but no active connection, try to connect
        if self.hostCombo.currentIndex() >= 0 and not connectionManager.isActive():
            self._onHostComboChanged(self.hostCombo.currentIndex())

    def _onHostComboChanged(self, index):
        """Automatically connect to the selected host."""
        name = self.hostCombo.currentData()
        
        if not name:
            connectionManager.disconnect()
            self.hostCombo.setStyleSheet("")
            return

        try:
            conn = connectionManager.connect(name, parent=self)
            conn.onConnectionLost.connect(self._onHostConnectionLost)
            
        except Exception as e:
            self.hostCombo.setStyleSheet("color: #ff6b6b;")
            connectionManager.disconnect()
        else:
            self.hostCombo.setStyleSheet("color: #6ea7ff; font-weight: bold;")
            ws = self.workspaceWidget.currentWorkspace()
            hostExecutor.switchWorkspace(ws.name)

    def _onHostConnectionLost(self, reason: str):
        connectionManager.disconnect()
        self.hostCombo.setStyleSheet("")
        logger.warning(f"Connection to host lost: {reason}")
        # Refresh to show dead hosts are gone (heartbeat should handle this anyway)
        self._refreshHostCombo()

    def _onSyncRequested(self):
        msg = "Sync all modules with the files on disk?\n\nYou may lose unsaved changes for those modules.\n\nContinue?"
        if QMessageBox.question(self, "Rig Builder", msg, QMessageBox.Yes | QMessageBox.No, QMessageBox.Yes) == QMessageBox.Yes:
            self.treeWidget.syncAllModules()

    def _onManageHosts(self):
        """Open a dialog to configure host discovery and networking."""
        dialog = HostManagerDialog(parent=self)
        dialog.hostsChanged.connect(self._refreshHostCombo)
        dialog.exec()

    def prepareContextForChat(self):
        """Prepare tools for AI to avoid threading issues."""
        m = self.treeWidget.currentModule()
        editor = self.codeEditorWidget.editorWidget
        
        self.aiChatDialog.aiToolsContext = {
            "code": editor.toPlainText(),
            "selectedCode":editor.textCursor().selectedText(),
            "host":self.hostCombo.currentData(),
            "workspace":self.workspaceWidget.currentWorkspace().name,
            "selectedModule":m
        }

    def _onAttributeChanged(self, module: Module, attr: Attribute):
        if module == self.treeWidget.currentModule():
            self.attributesTabWidget.updateTabs(module)

    def _onReplaceCodeRequested(self, module: Module, code: str):
        if module != self.treeWidget.currentModule():
            return

        editor = self.codeEditorWidget.editorWidget
        originalText = editor.toPlainText()
        
        if originalText == code:
            return

        dialog = DiffBrowserDialogWithConfirm(
            originalText=originalText, 
            currentText=code, 
            fromDesc="Current Code", 
            toDesc="AI Suggestion", 
            parent=self
        )
        if dialog.exec() == QDialog.Accepted:
            cursor = editor.textCursor()
            cursor.beginEditBlock()
            cursor.movePosition(QTextCursor.Start)
            cursor.movePosition(QTextCursor.End, QTextCursor.KeepAnchor)
            cursor.removeSelectedText()
            cursor.insertText(code)
            cursor.endEditBlock()

    def _onReplaceSelectedCodeRequested(self, module: Module, code: str):
        if module != self.treeWidget.currentModule():
            return

        editor = self.codeEditorWidget.editorWidget
        cursor = editor.textCursor()
        if not cursor.hasSelection():
            return        
        
        startPos = cursor.selectionStart()
        endPos = cursor.selectionEnd()
        
        doc = cursor.document()
        startBlock = doc.findBlock(startPos)
        endBlock = doc.findBlock(endPos)
        
        # If the endPos is exactly at the start of a block, the user selected up to the end of the previous block
        if endPos == endBlock.position() and startPos != endPos:
            endBlock = endBlock.previous()
            
        # Get indentation of the start block
        blockText = startBlock.text()
        indentation = ""
        for char in blockText:
            if char in (' ', '\t'):
                indentation += char
            else:
                break
                
        # Format the new code
        code = textwrap.dedent(code).strip('\n')
        indentedLines = [(indentation + line if line.strip() else line) for line in code.split('\n')]
        indentedCode = '\n'.join(indentedLines)
        
        # Expand selection to full blocks
        editCursor = QTextCursor(cursor)
        editCursor.setPosition(startBlock.position())
        editCursor.setPosition(endBlock.position(), QTextCursor.KeepAnchor)
        editCursor.movePosition(QTextCursor.EndOfBlock, QTextCursor.KeepAnchor)
        
        originalSnippet = editCursor.selectedText().replace('\u2029', '\n')
        
        if originalSnippet == indentedCode:
            return

        dialog = DiffBrowserDialogWithConfirm(
            originalText=originalSnippet, 
            currentText=indentedCode, 
            fromDesc="Current Selection", 
            toDesc="AI Suggestion", 
            parent=self
        )
        if dialog.exec() == QDialog.Accepted:
            editCursor.beginEditBlock()
            editCursor.insertText(indentedCode)
            editCursor.endEditBlock()

    def _onOpenAIChat(self):
        """Open the AI Chat dialog."""
        self.aiChatDialog.show()
        self.aiChatDialog.raise_()
        self.aiChatDialog.activateWindow()

    def pinWindow(self, state: bool):
        """Toggle 'Stay on Top' window flag."""
        self.setWindowFlag(Qt.WindowStaysOnTopHint, state)
        self.show()

    def menu(self):
        menu = QMenu(self)

        menu.addAction("New", self.treeWidget.insertModule, "Insert")
        menu.addAction("Import", self.treeWidget.importModule, "Ctrl+I")
        menu.addAction("Import script", self.treeWidget.importScript)
        menu.addSeparator()
        menu.addAction("Save", self.treeWidget.saveModules, "Ctrl+S")
        menu.addAction("Save as", partial(self.treeWidget.saveModules, forceDialog=True, generateNewUids=True))
        menu.addAction("Show in Explorer", self.browseModuleFile)
        menu.addAction("View edit history", self.showModuleInHistory, "Ctrl+H")
        menu.addAction("Diff vs File", self.diffModule, "Alt+D")        
        menu.addSeparator()
        menu.addAction("Duplicate", self.treeWidget.duplicateModule, "Ctrl+D")
        menu.addAction("Copy", self.treeWidget.copyModules, "Ctrl+C")
        menu.addAction("Cut", self.treeWidget.cutModules, "Ctrl+X")
        menu.addAction("Paste", self.treeWidget.pasteModules, "Ctrl+V")

        menu.addSeparator()
        menu.addAction("Sync with file", self.treeWidget.syncSelectedModules)
        menu.addAction("Embed", self.treeWidget.embedModule)
        menu.addAction("Mute", self.treeWidget.muteModule, "M")
        menu.addAction("Remove", self.treeWidget.removeModule, "Delete")

        menu.addSeparator()
        menu.addAction("Remove all", self.removeAllModules)
        menu.addSeparator()
        menu.addAction("Open User folder", self.openUserFolder)

        return menu

    def addModule(self, module: Module) -> Optional[Module]:
        """Add a module to the tree and return it."""
        idx = self.treeWidget.moduleModel.addModuleAt(module)
        if idx.isValid():
            return self.treeWidget.moduleModel.getModule(idx)
        return None

    def addModuleBySpec(self, spec: str):
        """Load and select module by spec (UID, relative or full path)."""
        try:
            module = Module.loadModule(spec)
        except ModuleNotFoundError:
            logger.warning("Module not found: {}".format(spec))
            return
        self.treeWidget.addModule(module)
        self.treeWidget.selectModule(module)

    def editInVSCode(self):
        module = self.treeWidget.currentModule()
        if not module:
            return         

        if not shutil.which(settings.vscode):
            msg = "Editor executable not found: {}\n\nPlease install the editor or update the VSCode command in the Workspace Manager.".format(settings.vscode)
            QMessageBox.warning(self,"Editor Error", msg)
            return
   
        def getFunctionDefinition(f: Callable[..., object], *, name: Optional[str] = None) -> str: # f(a,b,c=1) => 'def f(a,b,c=1):pass'
            signature = inspect.signature(f)
            args = []
            for p in signature.parameters.values():
                if p.default == p.empty:
                    args.append(p.name)
                else:
                    args.append("{}={}".format(p.name, p.default))
            return "def {}({}):pass".format(name or f.__name__, ", ".join(args))

        def getVariableValue(v: object) -> Optional[object]:
            try:
                jv = copyJson(v) # check if v is JSON serializable
            except:
                return None

            if isinstance(jv, str):
                return '\'' + jv.replace("\n", "\\n") + '\''
            return jv

        def onRunCodeFileChanged(filePath: str, modulePath: str):
            # Try to find the "live" module in the tree (it might have been replaced)
            root = self.treeWidget.moduleModel.rootModule()
            targetModule = root.findModuleByPath(modulePath)

            if not targetModule:
                logger.error("Could not find module for path: {}".format(modulePath))
                return

            with open(filePath, "r") as f:
                lines = f.read().splitlines()

            code = "\n".join(lines[1:]) # skip first line: import header file
            code = replaceAttrPrefixInverse(code)
            targetModule.setRunCode(code)
            
            # Refresh UI if this module is currently selected
            if self.treeWidget.currentModule() == targetModule:
                self.codeEditorWidget.updateState()

        def startTrackedFileThread(filePath: str, callback: Callable[..., None]):
            if filePath in trackFileChangesThreads:
                old_th = trackFileChangesThreads[filePath]
                old_th.stop()
                old_th.wait(1000)

            th = TrackFileChangesThread(filePath)
            th.fileChanged.connect(callback)
            th.start()
            trackFileChangesThreads[filePath] = th

        setupVscode()

        # generate header file
        fileName = module.path().lstrip("/").replace("/", "__")
        headerFile = os.path.join(RIG_BUILDER_USER_PATH, "vscode", "{}_header.py".format(fileName))
        runCodeFilePath = os.path.join(RIG_BUILDER_USER_PATH, "vscode", "{}.py".format(fileName))

        headerCode = []

        # expose API
        env = module.context()

        for k, v in env.items():
            if callable(v):
                headerCode.append(getFunctionDefinition(v, name=k))
            else:
                headerCode.append("{} = {}".format(k, getVariableValue(v)))

        with open(headerFile, "w") as f:
            f.write("\n".join(headerCode))

        with open(runCodeFilePath, "w") as f:
            headerModule = os.path.splitext(os.path.basename(headerFile))[0]
            code = replaceAttrPrefix(module.runCode())
            importLine = "from .{} import * # must be the first line".format(headerModule)
            f.write("\n".join([importLine, code]))

        # Use partial to bind modulePath, filePath will come from the signal
        callback = partial(onRunCodeFileChanged, modulePath=module.path())
        startTrackedFileThread(runCodeFilePath, callback)

        try:
            subprocess.Popen([settings.vscode, RIG_BUILDER_USER_PATH+"/vscode", "-g", runCodeFilePath], shell=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        except Exception as e:
            QMessageBox.warning(self, "Editor Error", f"Failed to launch editor: {str(e)}")

    def diffModule(self, *, reference: Optional[str] = None):
        module = self.treeWidget.currentModule()
        if not module:
            return

        path = UidManager.resolve(reference) if reference else UidManager.resolve(module.uid())
        if not path:
            QMessageBox.warning(self, "Rig Builder", "Can't find reference file")
            return

        path = os.path.normpath(path)
        currentXml = module.toXml()

        if not os.path.exists(path):
            QMessageBox.warning(self, "Rig Builder", "Can't find reference file: {}".format(path))
            return

        with open(path, "r", encoding="utf-8", errors="replace") as f:
            originalXml = f.read()

        if originalXml == currentXml:
            QMessageBox.information(self, "Rig Builder", "No changes detected.")
            return

        DiffBrowserDialog(originalXml, currentXml, path, "Current", parent=self).exec()
                    
    def removeAllModules(self):
        if QMessageBox.question(self, "Rig Builder", "Remove all modules?", QMessageBox.Yes | QMessageBox.No, QMessageBox.Yes) == QMessageBox.Yes:
            self.treeWidget.clear()

    def _onModuleAdditionRequested(self, module: Module):
        """Handle module addition from external browsers."""
        added = self.addModule(module)
        self.show()
        self.raise_()
        self.activateWindow()
        if added:
            self.treeWidget.selectModule(added)

    def browseModuleFile(self):
        for module in self.treeWidget.selectedModules():
            path = UidManager.resolve(module.uid())
            if module and os.path.exists(path):
                subprocess.call("explorer /select,\"{}\"".format(os.path.normpath(path)))

    def openUserFolder(self):
        subprocess.call("explorer \"{}\"".format(RIG_BUILDER_USER_PATH))

    def _onTreeSelectionChanged(self, selected, deselected):
        module = self.treeWidget.currentModule()
        en = module is not None
        
        self.runBtn.setEnabled(en)
        self.centerRightSplitter.setVisible(en)
        self.moduleHistoryBrowser.setVisible(not en)
        
        self.docBrowser.setEnabled(en)
        self.docBrowser.updateDoc(module)

        if module:
            self.attributesTabWidget.updateTabs(module)
            self.codeEditorWidget.module = module
            self.codeEditorWidget.updateState()            

    def showLog(self):
        self.logWidget.ensureCursorVisible()

    def onConnectionErrorCallback(self, text: str):
        QMessageBox.warning(self, "Rig Builder", text)
        connectionManager.disconnect()
        self.hostCombo.setStyleSheet("")
        self.cleanupRun()

    def onErrorCallback(self, text: str, tb: str):
        logger.error(f"{text}\n{tb}" if tb else text)
        self.showLog()
        self.cleanupRun()

    def onPrintCallback(self, text: str):
        logger.info(text)

    def cleanupRun(self):
        logHandler.flush()
        self.progressBarWidget.endProgress()
        self.runBtn.setEnabled(True)  

    def onRunCallback(self, path: str):
        logger.info(f"{path} is running...")
        self.progressBarWidget.stepProgress(self._progressCounter, path)
        self._progressCounter += 1

    def runModule(self):
        """Run module on the host server."""
        def getChildrenCount(m: Module) -> int:
            return sum(1 + getChildrenCount(ch) for ch in m.children())

        currentModule = self.treeWidget.currentModule()
        if not currentModule:
            return

        if not connectionManager.activeConnection():
            QMessageBox.warning(self, "Rig Builder", "Not connected to host server")
            return

        self.setFocus()
        self.showLog()
        self.runBtn.setEnabled(False)

        count = getChildrenCount(currentModule)
        self.progressBarWidget.initialize()
        self.progressBarWidget.beginProgress(currentModule.path(), count + 1)
        self._progressCounter = 0

        ts = time.strftime("%H:%M:%S")
        logger.info(f"Running on {connectionManager.activeServerName()} at {ts}")

        newModule = hostExecutor.runModule(currentModule)

        if newModule is not None:
            idx = self.treeWidget.moduleModel.indexForModule(currentModule)
            if idx.isValid():
                self.treeWidget.replaceModule(idx, newModule)
                self.attributesTabWidget.updateTabs(newModule)
            else:            
                QMessageBox.warning(self, "Rig Builder", "Could not find module in tree")
        
        self.cleanupRun()

        logger.info("Running done.\n")

    def showModuleInHistory(self):
        """Put selected module UID into history browser filter and clear selection so user can view history."""
        module = self.treeWidget.currentModule()
        if not module:
            return

        if not module.uid():
            return
            
        self.moduleHistoryBrowser.filterEdit.setText(module.uid())
        self.treeWidget.clearSelection()

    def _onAboutToChangeWorkspace(self):
        """Handle about to change workspace event."""
        if self.workspaceWidget.currentWorkspace():
            self.saveToWorkspace()
 
    def _onWorkspaceChanged(self, ws: workspace.Workspace):
        """Handle workspace change event."""
        self.loadFromWorkspace(ws)
        self.aiChatDialog.loadChat()
        self._updateAutoSaveInterval()
        self._refreshHostCombo()
        self.moduleHistoryBrowser.syncModuleHistory()
        self.moduleBrowser.modulesAutoReloadWatcher.setRoots([ws.settings.modulesPath])
        self.moduleBrowser.refreshModules()

        hostExecutor.switchWorkspace(ws.name)

        logger.info(f"Workspace changed: {ws.name}")
        
    def saveToWorkspace(self):
        """Save UI state to active workspace."""
        ws = self.workspaceWidget.currentWorkspace()
        
        # Sync current global settings into workspace settings before saving
        ws.settings.fromDict(settings.toDict())
        
        tree = self.treeWidget
        rootModules = tree.moduleModel.rootModule().children()
        allModules = workspace.flattenModules(rootModules)
        
        ws.file.modules = rootModules
        ws.file.expanded = [bool(tree.isExpanded(tree.moduleModel.indexForModule(m))) for m in allModules]
        ws.save()

    def loadFromWorkspace(self, ws: workspace.Workspace):
        """Populate UI from the Workspace object."""
        # Update workspace combo if it's not already correct
        self.workspaceWidget.combo.blockSignals(True)

        idx = self.workspaceWidget.combo.findData(ws)
        if idx >= 0:
            self.workspaceWidget.combo.setCurrentIndex(idx)
        self.workspaceWidget.combo.blockSignals(False)

        self.treeWidget.clear()

        for module in ws.file.modules:
            self.treeWidget.moduleModel.addModuleAt(module)

        if ws.file.expanded:
            rootModules = self.treeWidget.moduleModel.rootModule().children()
            allModules = workspace.flattenModules(rootModules)
            for m, isExpanded in zip(allModules, ws.file.expanded):
                if isExpanded:
                    idx = self.treeWidget.moduleModel.indexForModule(m)
                    if idx.isValid():
                        self.treeWidget.setExpanded(idx, True)

    def _updateAutoSaveInterval(self):
        """Update timer interval from global settings."""
        interval_ms = settings.autoSaveInterval * 60 * 1000
        self.autoSaveTimer.start(interval_ms)

    def saveAppSettings(self):
        """Save app-specific settings like active workspace and window geometry."""
        appSettings = QSettings("RigBuilder")
        appSettings.setValue("activeWorkspace", self.workspaceWidget.currentWorkspace().name)
        appSettings.setValue("geometry", self.saveGeometry())
        appSettings.setValue("pinned", self.windowPinBtn.isChecked())
        
        # Save splitter states
        for idx, splitter in enumerate(self._splitters["widgets"]):
            appSettings.setValue(f"splitter{idx}", splitter.saveState())
        appSettings.setValue(f"splitterVersion", self._splitters["version"])        
        appSettings.sync()

    def loadAppSettings(self):
        """Load app-specific settings."""
        appSettings = QSettings("RigBuilder")
        
        # Restore window geometry
        geometry = appSettings.value("geometry")
        if geometry:
            self.restoreGeometry(geometry)

        pinned = appSettings.value("pinned", False, type=bool)
        self.windowPinBtn.setChecked(pinned)
        self.pinWindow(pinned)
        
        # Restore splitter states
        splittersVersion = appSettings.value("splitterVersion", 0, type=int)
        if splittersVersion == self._splitters["version"]: # restore only if versions match
            for idx, splitter in enumerate(self._splitters["widgets"]):
                state = appSettings.value(f"splitter{idx}")
                if state:
                    splitter.restoreState(state)

        # Restore workspace
        workspaceName = appSettings.value("activeWorkspace", "default")
        if not Workspace.exists(workspaceName):
            logger.warning(f"Workspace '{workspaceName}' not found, switching to default.")
            workspaceName = "default"
        self.workspaceWidget.switchWorkspace(workspaceName)

    def _onAutoSaveTimer(self):
        """Handle periodic autosave."""
        self.saveToWorkspace()
        ws = self.workspaceWidget.currentWorkspace()
        timestamp = time.strftime("%H:%M")
        print(f"Workspace '{ws.name}' autosaved at {timestamp}")

    def closeEvent(self, event):
        # Terminate all file tracking threads before closing
        for thread in trackFileChangesThreads.values():
            if thread.isRunning():
                thread.stop()
                thread.wait(1000)  # Wait up to 1 second for thread to finish
        trackFileChangesThreads.clear()
        
        self.saveAppSettings()
        self.saveToWorkspace()

        # Call parent close event
        super().closeEvent(event)

def setupVscode():  # path to .vscode folder
    settings = {
        "python.autoComplete.extraPaths": [],
    }

    folder = os.path.join(RIG_BUILDER_USER_PATH, "vscode", ".vscode")
    os.makedirs(folder, exist_ok=True)
    settingsFile = os.path.join(folder, "settings.json")

    if os.path.exists(settingsFile):
        try:
            settings.update(loadJson(settingsFile))
        except Exception as e:
            logger.error(f"Failed to load VSCode settings from {settingsFile}: {e}")

    context = hostExecutor.executeCode("import sys;hostSysPath=sys.path")
    settings["python.autoComplete.extraPaths"] = context.get("hostSysPath", [])

    try:
        saveJson(settingsFile, settings)
    except Exception as e:
        logger.error(f"Failed to save VSCode settings to {settingsFile}: {e}")

def cleanupVscode():
    vscodeFolder = RIG_BUILDER_USER_PATH+"/vscode"
    if not os.path.exists(vscodeFolder):
        return
    
    for f in os.listdir(vscodeFolder):
        if f.endswith(".py") or any(f.endswith(ext) for ext in MODULE_EXTS): # remove module files
            os.remove(os.path.join(vscodeFolder, f))

cleanupVscode()


# global references
mainWindow = RigBuilderWindow()
logHandler.setTarget(mainWindow.logWidget)

hostExecutor.onConnectionError.connect(mainWindow.onConnectionErrorCallback)
hostExecutor.onPrint.connect(mainWindow.onPrintCallback)
hostExecutor.onError.connect(mainWindow.onErrorCallback)
hostExecutor.onRunCallback.connect(mainWindow.onRunCallback)
hostExecutor.beginProgress.connect(mainWindow.progressBarWidget.beginProgress)
hostExecutor.stepProgress.connect(mainWindow.progressBarWidget.stepProgress)
hostExecutor.endProgress.connect(mainWindow.progressBarWidget.endProgress)
