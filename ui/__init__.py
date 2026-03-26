import time
import json
import re
import os
import subprocess
import inspect
import sys
import shutil
import logging
import fnmatch
import xml.etree.ElementTree as ET
from functools import partial
from typing import Callable, Optional, List, Tuple

from ..qt import *
from .. import __version__
from ..core import *
from .editor import CodeEditorWithNumbersWidget
from .docBrowser import DocBrowser
from .moduleHistoryBrowser import ModuleHistoryWidget
from .diffBrowser import DiffBrowserDialog
from ..widgets.ui import TemplateWidgets, EditTextDialog, EditJsonDialog
from ..utils import *
from .utils import *
from ..client.connectionManager import connectionManager
from ..client.hostExecutor import hostExecutor
from ..server.hosts import AVAILABLE_HOSTS, HOST_STARTUP_TEMPLATE
from .widgetPresetManager import WidgetPresetManager, PresetEditorDialog
from .fileTracker import TrackFileChangesThread, trackFileChangesThreads, DirectoryWatcher
from .logger import logger, logHandler


class AttributesWidget(QWidget):
    moduleChanged = Signal(object) # Module
    executionRequested = Signal(str)

    def __init__(self, module: Module, category: str, **kwargs):
        super().__init__(**kwargs)

        self.module = module
        self.category = category

        self.attributes = []
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
        titleAction = menu.addAction(attr.name())
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
            style = "TemplateWidget { border: 4px solid rgba(110, 110, 57, 0.45); background-color: rgba(110, 110, 57, 0.25) }"
        
        elif attr.expression() and not attr.connect(): # only expression (magenta)
            style = "TemplateWidget { border: 4px solid rgba(99, 32, 148, 0.45); background-color: rgba(99, 32, 148, 0.25) }"
        
        elif attr.expression() and attr.connect(): # both
            style = "TemplateWidget { border: 4px solid rgba(0,0,0,0); background: qlineargradient(x1: 0, y1: 0, x2: 1, y2: 0, stop: 0 rgba(110, 110, 57, 0.25), stop: 1 rgba(99, 32, 148, 0.25)); }"

        nameWidget.setText(attr.name()+("*" if attr.modified() else ""))

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

        doUsePrefix = QMessageBox.question(self, "Rig Builder", "Use prefix for the exposed attribute name?", QMessageBox.Yes and QMessageBox.No, QMessageBox.Yes) == QMessageBox.Yes
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

        tmp = TemplateWidgets[attr.template()]()
        attr.setConnect("")
        attr.setData(tmp.getDefaultData())
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

        self.currentChanged.connect(self._onTabChanged)

    def contextMenuEvent(self, event: QContextMenuEvent):
        menu = QMenu(self)

        if self.module:
            menu.addAction("Edit attributes", self.editAttributes)
            menu.addSeparator()
            menu.addAction("Replace in values", self.searchAndReplaceDialog.exec)

        menu.popup(event.globalPos())

    def editAttributes(self):
        dialog = EditAttributesDialog(self.module, self.currentIndex(), parent=self)
        dialog.exec()

        self.attributesChanged.emit()
        self.updateTabs()

    def _onReplace(self, old: str, new: str, opts: Dict[str, bool]):
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

    def _onTabChanged(self, idx: int):
        self.selectTab(idx)

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

class ModuleBrowserTreeWidget(QTreeWidget):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.middlePressPos = QPoint()

        self.setHeaderLabels(["Module", "Modification time"])
        self.header().setSectionResizeMode(QHeaderView.ResizeToContents)
        self.setSortingEnabled(True)
        self.sortItems(1, Qt.DescendingOrder)

        self.setDragEnabled(True)
        self.setAcceptDrops(False)
        self.setDropIndicatorShown(False)
        self.setDragDropMode(QAbstractItemView.DragOnly)
        self.setDefaultDropAction(Qt.CopyAction)
        self.setMinimumHeight(100)

    def _collectDraggedModulePaths(self) -> list[str]:
        modulePaths = []
        for item in self.selectedItems():
            filePath = getattr(item, "filePath", "")
            if filePath:
                modulePaths.append(filePath)
        return modulePaths

    def _startModuleDrag(self):
        modulePaths = self._collectDraggedModulePaths()
        if not modulePaths:
            return

        mimeData = QMimeData()
        mimeData.setUrls([QUrl.fromLocalFile(path) for path in modulePaths])

        drag = QDrag(self)
        drag.setMimeData(mimeData)
        drag.exec(Qt.CopyAction)

    def startDrag(self, supportedActions: Qt.DropActions):
        del supportedActions
        self._startModuleDrag()

    def mousePressEvent(self, event: QMouseEvent):
        if event.button() == Qt.MiddleButton:
            self.middlePressPos = event.pos()
            item = self.itemAt(event.pos())
            if item:
                if not (event.modifiers() & (Qt.ControlModifier | Qt.ShiftModifier)):
                    self.clearSelection()
                item.setSelected(True)
                self.setCurrentItem(item)
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event: QMouseEvent):
        if event.buttons() & Qt.MiddleButton:
            if (event.pos() - self.middlePressPos).manhattanLength() >= QApplication.startDragDistance():
                self._startModuleDrag()
                self.middlePressPos = QPoint()
                event.accept()
                return
        super().mouseMoveEvent(event)

    def contextMenuEvent(self, event: QContextMenuEvent):
        menu = QMenu(self)
        menu.addAction("Locate", self.browseModuleDirectory)
        menu.addAction("Open public folder", self.openPublicModulesFolder)
        menu.addAction("Open private folder", self.openPrivateModulesFolder)
        menu.addSeparator()
        menu.addAction("Set public modules folder...", self.parent().browsePublicModulesPath)
        menu.addAction("Reset public modules folder", self.parent().resetPublicModulesPath)
        menu.addSeparator()
        menu.addAction("Refresh", self.parent().refreshModules)
        menu.popup(event.globalPos())

    def browseModuleDirectory(self):
        for item in self.selectedItems():
            if item.childCount() == 0:
                subprocess.call("explorer /select,\"{}\"".format(os.path.normpath(item.filePath)))

    def openPublicModulesFolder(self):
        folderPath = getPublicModulesPath()
        subprocess.call("explorer \"{}\"".format(folderPath))

    def openPrivateModulesFolder(self):
        folderPath = getPrivateModulesPath()
        subprocess.call("explorer \"{}\"".format(folderPath))

class ModuleSelectorWidget(QWidget):
    """Embeddable module selector with filter, source options, and module tree."""
    modulesReloaded = Signal()

    def __init__(self, **kwargs):
        super().__init__(**kwargs)

        layout = QVBoxLayout()
        layout.setContentsMargins(0, 0, 0, 0)
        self.setLayout(layout)

        self.updateSourceWidget = QComboBox()
        self.updateSourceWidget.addItems(["All", "Public", "Private", "None"])
        self.updateSourceWidget.setCurrentIndex({"all": 0, "public": 1, "private": 2, "": 3}[Module.UpdateSource])
        self.updateSourceWidget.currentIndexChanged.connect(partial(self.updateSource))

        self.modulesFromButtonGroup = QButtonGroup(self)
        self.modulesFromPublicRadio = QRadioButton("Public")
        self.modulesFromPrivateRadio = QRadioButton("Private")
        self.modulesFromButtonGroup.addButton(self.modulesFromPublicRadio, 0)
        self.modulesFromButtonGroup.addButton(self.modulesFromPrivateRadio, 1)
        self.modulesFromPublicRadio.setChecked(True)
        self.modulesFromButtonGroup.buttonClicked.connect(self.applyMask)

        self.maskWidget = QLineEdit()
        self.maskWidget.setPlaceholderText("Filter modules...")
        self.maskWidget.textChanged.connect(self.applyMask)

        self.clearFilterButton = QPushButton("🧹 Clear")
        self.clearFilterButton.clicked.connect(self.maskWidget.clear)
        self.clearFilterButton.hide()
        self.maskWidget.textChanged.connect(self._onMaskTextChanged)

        filterLayout = QHBoxLayout()
        filterLayout.addWidget(QLabel("Filter"))
        filterLayout.addWidget(self.maskWidget)
        filterLayout.addWidget(self.clearFilterButton)
        layout.addLayout(filterLayout)

        self.treeWidget = ModuleBrowserTreeWidget()

        controlsLayout = QHBoxLayout()
        controlsLayout.addWidget(QLabel("Modules from"))
        controlsLayout.addWidget(self.modulesFromPublicRadio)
        controlsLayout.addWidget(self.modulesFromPrivateRadio)
        controlsLayout.addStretch()
        controlsLayout.addWidget(QLabel("Update source"))
        controlsLayout.addWidget(self.updateSourceWidget)

        layout.addWidget(self.treeWidget)
        layout.addLayout(controlsLayout)

        self.refreshModules()

    def refreshModules(self):
        """Internal refresh used by startup and auto-reload flows."""
        Module.updateUidsCache()
        self.applyMask()

    def updateSource(self):
        updateSource = self.updateSourceWidget.currentIndex()
        UpdateSourceFromInt = {0: "all", 1: "public", 2: "private", 3: ""}
        Module.UpdateSource = UpdateSourceFromInt[updateSource]

    def browsePublicModulesPath(self):
        current = getPublicModulesPath()
        folder = QFileDialog.getExistingDirectory(self, "Public modules folder", current)
        if folder:
            Settings["publicModulesPath"] = folder
            Module.updateUidsCache()
            self.applyMask()

    def resetPublicModulesPath(self):
        Settings["publicModulesPath"] = ""
        Module.updateUidsCache()
        self.applyMask()

    def getModulesRootDirectory(self) -> str:
        modulesFrom = self.modulesFromButtonGroup.checkedId()
        return getPublicModulesPath() if modulesFrom == 0 else getPrivateModulesPath()

    def _onMaskTextChanged(self, text: str):
        self.clearFilterButton.setVisible(bool(text))

    def applyMask(self, *_):
        """Rebuild module tree from mask and source settings. Accepts optional args from Qt signals."""
        def findChildByText(text: str, parent: QTreeWidgetItem, column: int = 0):
            for i in range(parent.childCount()):
                ch = parent.child(i)
                if text == ch.text(column):
                    return ch

        modulesFrom = self.modulesFromButtonGroup.checkedId()
        modulesDirectory = self.getModulesRootDirectory()
        modules = list(Module.PublicUids.values()) if modulesFrom == 0 else list(Module.PrivateUids.values())
        modules = sorted(modules)

        self.treeWidget.clear()

        mask = self.maskWidget.text().split() # split by spaces, '/folder mask /other mask'

        # make tree dict from module files
        for f in modules:
            relativePath = os.path.relpath(f, modulesDirectory)
            relativeDir = os.path.dirname(relativePath)
            name, _ = os.path.splitext(os.path.basename(f))

            okMask = True
            dirMask = "/"+relativePath.replace("\\", "/")+"/"
            for m in mask:
                if not re.search(re.escape(m), dirMask, re.IGNORECASE):
                    okMask = False
                    break

            if not okMask:
                continue

            dirItem = self.treeWidget.invisibleRootItem()
            if relativeDir:
                for p in relativeDir.split("\\"):
                    ch = findChildByText(p, dirItem)
                    if ch:
                        dirItem = ch
                    else:
                        ch = QTreeWidgetItem([p, ""])
                        ch.setFlags((ch.flags() | Qt.ItemIsEnabled | Qt.ItemIsSelectable) & ~Qt.ItemIsDragEnabled)
                        font = ch.font(0)
                        font.setBold(True)
                        ch.setForeground(0, QColor(130, 130, 230))
                        ch.setFont(0, font)

                        dirItem.addChild(ch)
                        dirItem.setExpanded(True if mask else False)
                        dirItem = ch

            modtime = time.strftime("%Y/%m/%d %H:%M", time.localtime(os.path.getmtime(f)))
            item = QTreeWidgetItem([name, modtime])
            item.setFlags(item.flags() | Qt.ItemIsDragEnabled)
            item.filePath = f
            dirItem.addChild(item)
            dirItem.setExpanded(True if mask else False)


class ModuleModel(QAbstractItemModel):
    """
    Qt Model for Module hierarchy.
    Enables MVC pattern where Module is the single source of truth.
    """
    def __init__(self, rootModule: Optional[Module] = None, parent=None):
        super().__init__(parent)
        self._rootModule = rootModule or Module()
        self._draggedModules = [] # Temporary storage for internal drag and drop

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
        return 4 # Name, Path, Source, UID

    def data(self, index, role=Qt.DisplayRole):
        if not index.isValid():
            return None

        module = index.internalPointer()
        column = index.column()

        if role == Qt.DisplayRole or role == Qt.EditRole:
            if column == 0:
                return module.name()+("*" if module.modified() else "")

            elif column == 1:
                return module.relativePathString().replace("\\", "/") + " "

            elif column == 2:
                source = ""
                if module.loadedFromPrivate(): source = "private"
                elif module.loadedFromPublic(): source = "public"
                return source + " "

            elif column == 3:
                return module.uid()[:8]

        elif role == Qt.ForegroundRole:
            if column == 0:
                isParentMuted = False
                isParentReferenced = False
                p = module.parent()
                while p:
                    isParentMuted = isParentMuted or p.muted()
                    isParentReferenced = isParentReferenced or p.uid()
                    p = p.parent()
                
                color = QColor(200, 200, 200)
                if isParentReferenced: color = QColor(140, 140, 180)
                if module.muted() or isParentMuted: color = QColor(100, 100, 100)
                return color

            elif column == 1:
                return QColor(125, 125, 125)

            elif column == 2:
                if module.loadedFromPrivate(): return QColor(120, 220, 120)
                return QColor(120, 120, 120)

            elif column == 3:
                return QColor(125, 125, 170)

        elif role == Qt.BackgroundRole:
            if column == 0:
                if not re.match("\\w*", module.name()):
                    return QColor(170, 50, 50)
                
                p = module.parent()
                if p and len([ch for ch in p.children() if ch.name() == module.name()]) > 1:
                    return QColor(170, 50, 50)
        
        elif role == Qt.FontRole:
            if column == 1:
                font = QFont()
                font.setItalic(True)
                return font

        return None

    def setData(self, index, value, role=Qt.EditRole):
        if index.isValid() and role == Qt.EditRole:
            module = index.internalPointer()
            column = index.column()
            if column == 0:
                newName = replaceSpecialChars(str(value)).strip()
                p = module.parent()
                if p:
                    existingNames = set([ch.name() for ch in p.children() if ch is not module])
                    newName = findUniqueName(newName, existingNames)
                
                # Handle connection updates (migrated from ModuleItem)
                connections = self._saveConnections(module)
                module.setName(newName)
                self._updateConnections(connections)
                
                self.dataChanged.emit(index, index)
                return True
        return False

    def _saveConnections(self, currentModule: "Module"):
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
            return ["Name", "Path", "Source", "UID"][section]
        return None

    def flags(self, index):
        if not index.isValid():
            return Qt.ItemIsDropEnabled
        return Qt.ItemIsSelectable | Qt.ItemIsEnabled | Qt.ItemIsEditable | Qt.ItemIsDragEnabled | Qt.ItemIsDropEnabled

    # Helpers for structural changes
    def addModuleAt(self, module: Module, parentIndex: QModelIndex = QModelIndex(), row: int = -1):
        parentModule = parentIndex.internalPointer() if parentIndex.isValid() else self._rootModule
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
        if data.hasFormat("application/x-rigbuilder-module-internal") or data.hasUrls():
            return True
        return False

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
                if filePath and filePath.endswith(MODULE_EXT):
                    try:
                        m = Module.loadModule(filePath)
                        self.addModuleAt(m, parent, row)
                        row += 1
                    except Exception:
                        continue
            return True

        # Internal move is handled by the view/model if we return True and it was a MoveAction,
        # but since we are using custom Module tree, we should handle it ourselves if needed.
        # Actually, if we use InternalMove in the view, it calls removeRows/insertRows.        
        
        # If it's internal move (reordering)
        if data.hasFormat("application/x-rigbuilder-module-internal"):
            if not self._draggedModules:
                return False

            for m in self._draggedModules:
                oldParent = m.parent() or self._rootModule
                oldRow = oldParent.children().index(m)
                
                # Adjust target row if moving within same parent
                targetRow = row
                if oldParent == parentModule and oldRow < targetRow:
                    targetRow -= 1

                # Prevent moving into itself
                temp = parentModule
                while temp:
                    if temp == m: return False
                    temp = temp.parent()

                oldParentIdx = self.indexForModule(oldParent) if oldParent != self._rootModule else QModelIndex()
                
                self.beginMoveRows(oldParentIdx, oldRow, oldRow, parent, row)
                oldParent.removeChild(m)
                parentModule.insertChild(targetRow, m)
                self.endMoveRows()
                
                if targetRow <= row: row += 1
            
            self._draggedModules = []
            return True
        
        return False


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
        parentModule._children[row] = newModule
        newModule._parent = parentModule
        # Re-link children (they might have been lost in serialization/deserialization if not deep)
        for child in newModule.children():
            child._parent = newModule
        self.endResetModel()

class TreeWidget(QTreeView):
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

    def mousePressEvent(self, event: QMouseEvent):
        if event.button() == Qt.MiddleButton:
            self.middlePressPos = event.pos()
            idx = self.indexAt(event.pos())
            if idx.isValid():
                if not (event.modifiers() & (Qt.ControlModifier | Qt.ShiftModifier)):
                    self.selectionModel().clearSelection()
                self.selectionModel().select(idx, QItemSelectionModel.Select | QItemSelectionModel.Rows)
                self.setCurrentIndex(idx)
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
        self.setCurrentIndex(newIdx)
        self.scrollTo(newIdx)

    def selectModule(self, module: Module):
        idx = self.moduleModel.indexForModule(module)
        if idx.isValid():
            self.selectionModel().select(idx, QItemSelectionModel.ClearAndSelect | QItemSelectionModel.Rows)
            self.setCurrentIndex(idx)
            self.scrollTo(idx)

    def importModule(self):
        filePath, _ = QFileDialog.getOpenFileName(self.window(), "Import", getPrivateModulesPath(), "*.xml")
        if not filePath:
            return

        Module.updateUidsCache()
        try:
            m = Module.loadModule(filePath)
            self.moduleModel.addModuleAt(m)
        except ET.ParseError:
            logger.error(f"'{filePath}': invalid module")
            self.window().showLog()

    def importScript(self):
        filePath, _ = QFileDialog.getOpenFileName(self.window(), "Import script", getPrivateModulesPath(), "Python (*.py);;All files (*)")
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

    def saveModule(self):
        selectedIndices = self.selectionModel().selectedRows()
        if not selectedIndices:
            return

        modules = self.selectedModules()
        msg = "\n".join(["{} -> {}".format(m.name(), m.getSavePath() or "N/A") for m in modules])

        if QMessageBox.question(self.window(), "Rig Builder", "Save modules?\n"+msg, QMessageBox.Yes and QMessageBox.No, QMessageBox.Yes) != QMessageBox.Yes:
            return

        shouldCommit, commitMessage = False, ""
        if self.window().moduleHistoryWidget.isHistoryTrackingEnabled():
            shouldCommit, commitMessage = self.window().moduleHistoryWidget.showCommitMessageDialog()

        for idx in selectedIndices:
            module = self.moduleModel.getModule(idx)
            outputPath = module.getSavePath()

            if not outputPath:
                outputPath, _ = QFileDialog.getSaveFileName(self.window(), "Save "+module.name(), os.path.join(getPrivateModulesPath(), module.name()), "*.xml")

            if outputPath:
                dirname = os.path.dirname(outputPath)
                if not os.path.exists(dirname):
                    os.makedirs(dirname)

                try:
                    module.saveToFile(outputPath)
                except Exception as e:
                    QMessageBox.critical(self.window(), "Rig Builder", "Can't save module '{}': {}".format(module.name(), str(e)))
                else:
                    if shouldCommit:
                        if not moduleHistoryBrowser.recordModuleSave(module, commitMessage):
                            QMessageBox.critical(self.window(), "Rig Builder", "Can't save history for '{}'".format(module.name()))
                    
                    self.moduleModel.dataChanged.emit(idx, idx) # refresh display
                    self.window().attributesTabWidget.updateWidgetStyles()

        self.window().moduleHistoryWidget.updateModuleHistory()

    def saveAsModule(self):
        selectedIndices = self.selectionModel().selectedRows()
        if not selectedIndices:
            return

        shouldCommit, commitMessage = False, ""
        if self.window().moduleHistoryWidget.isHistoryTrackingEnabled():
            shouldCommit, commitMessage = self.window().moduleHistoryWidget.showCommitMessageDialog()

        for idx in selectedIndices:
            module = self.moduleModel.getModule(idx)
            outputDir = os.path.dirname(module.filePath()) or getPrivateModulesPath()
            outputPath, _ = QFileDialog.getSaveFileName(self.window(), "Save as "+module.name(), outputDir + "/" + module.name(), "*.xml")

            if outputPath:
                try:
                    module.saveToFile(outputPath, newUid=True)
                except Exception as e:
                    QMessageBox.critical(self.window(), "Rig Builder", "Can't save module '{}': {}".format(module.name(), str(e)))
                else:
                    if shouldCommit:
                        moduleHistoryBrowser.recordModuleSave(module, commitMessage)
                        
                    self.moduleModel.dataChanged.emit(idx, idx) # refresh display
                    self.window().attributesTabWidget.updateWidgetStyles()

        self.window().moduleHistoryWidget.updateModuleHistory()

    def embedModule(self):
        modules = self.selectedModules()
        if not modules:
            return

        msg = "\n".join([m.name() for m in modules])

        if QMessageBox.question(self.window(), "Rig Builder", "Embed modules?\n"+msg, QMessageBox.Yes and QMessageBox.No, QMessageBox.Yes) != QMessageBox.Yes:
            return

        selectedIndices = self.selectionModel().selectedRows()
        for idx in selectedIndices:
            module = self.moduleModel.getModule(idx)
            module.embed()
            self.moduleModel.dataChanged.emit(idx, idx)

    def updateModule(self):
        modules = self.selectedModules()
        if not modules:
            return

        Module.updateUidsCache()

        msg = "\n".join([m.name() for m in modules])
        if QMessageBox.question(self.window(), "Rig Builder", "Update modules?\n"+msg, QMessageBox.Yes and QMessageBox.No, QMessageBox.Yes) != QMessageBox.Yes:
            return

        selectedIndices = self.selectionModel().selectedRows()
        for idx in selectedIndices:
            module = self.moduleModel.getModule(idx)
            if not module.uid():
                QMessageBox.warning(self.window(), "Rig Builder", "Can't update module '{}': no uid".format(module.name()))
                continue

            module.update()
            # Since update() changes many things, emit layoutChanged or reset the model
            self.moduleModel.layoutChanged.emit()

    def muteModule(self):
        selectedIndices = self.selectionModel().selectedRows()
        for idx in selectedIndices:
            module = self.moduleModel.getModule(idx)
            if module.muted():
                module.unmute()
            else:
                module.mute()
            self.moduleModel.dataChanged.emit(idx, idx)

    def duplicateModule(self):
        selectedIndices = self.selectionModel().selectedRows(0)
        if not selectedIndices:
            return

        # Duplicate each selected module exactly once.
        selectedItems = []
        seenModuleIds = set()
        for idx in selectedIndices:
            module = self.moduleModel.getModule(idx)
            if not module:
                continue

            moduleId = id(module)
            if moduleId in seenModuleIds:
                continue

            seenModuleIds.add(moduleId)
            parentModule = module.parent() or self.moduleModel.rootModule()
            row = parentModule.children().index(module)
            selectedItems.append((parentModule, row, module))

        if not selectedItems:
            return

        # Insert bottom-up so earlier inserts do not shift later target rows.
        selectedItems.sort(key=lambda item: (id(item[0]), item[1]), reverse=True)

        newIndices = []
        for parentModule, row, sourceModule in selectedItems:
            newModule = sourceModule.copy()
            existingNames = {child.name() for child in parentModule.children()}
            newModule.setName(findUniqueName(sourceModule.name(), existingNames))

            parentIdx = QModelIndex()
            if parentModule is not self.moduleModel.rootModule():
                parentIdx = self.moduleModel.indexForModule(parentModule)

            newIndices.append(self.moduleModel.addModuleAt(newModule, parentIdx, row + 1))

        self.selectionModel().clearSelection()
        for idx in newIndices:
            if idx.isValid():
                self.selectionModel().select(idx, QItemSelectionModel.Select | QItemSelectionModel.Rows)

    def copyModules(self):
        """Copy selected modules to clipboard."""
        modules = self.selectedModules()
        if not modules:
            return
            
        self.clipboard = []
        for m in modules:
            self.clipboard.append(m.copy())
        
    def cutModules(self):
        """Cut selected modules to clipboard."""
        modules = self.selectedModules()
        if not modules:
            return
            
        self.clipboard = []
        for m in modules:
            self.clipboard.append(m.copy())
        
        self.removeModule(askConfirmation=False)

    def pasteModules(self):
        """Paste modules from clipboard."""
        if not self.clipboard:
            return

        parentIdx = self.currentIndex()
        if not self.selectionModel().hasSelection() or not parentIdx.isValid():
            parentIdx = QModelIndex()
            
        parentModule = self.moduleModel.getModule(parentIdx) or self.moduleModel.rootModule()

        pastedIndices = []
        for module in self.clipboard:
            newModule = module.copy()
            
            # Ensure unique names
            existingNames = set([ch.name() for ch in parentModule.children()])
            newModule.setName(findUniqueName(newModule.name(), existingNames))
            
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
            if QMessageBox.question(self.window(), "Rig Builder", "Remove modules?\n"+msg, QMessageBox.Yes and QMessageBox.No, QMessageBox.Yes) != QMessageBox.Yes:
                return

        # Sort indices in reverse order to avoid shifting issues when removing
        sortedIndices = sorted(selectedIndices, key=lambda x: x.row(), reverse=True)
        for idx in sortedIndices:
            self.moduleModel.removeModule(idx)

    def publishModule(self):
        """Publish selected modules."""
        modules = self.selectedModules()
        if not modules:
            return

        msg = "\n".join([m.name() for m in modules])
        if QMessageBox.question(self.window(), "Rig Builder", "Publish modules?\n"+msg, QMessageBox.Yes and QMessageBox.No, QMessageBox.Yes) != QMessageBox.Yes:
            return

        for m in modules:
            publishModule(m)
        
        self.moduleModel.layoutChanged.emit() # refresh display as source might change

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

class EditTemplateWidget(QWidget):
    Clipboard = []
    nameChanged = Signal(str, str)

    def __init__(self, name: str, template: str, **kwargs):
        super().__init__(**kwargs)

        self.template = template
        self.attrConnect = ""
        self.attrExpression = ""
        self.attrModified = False

        layout = QHBoxLayout()
        layout.setContentsMargins(0,0,0,0)
        self.setLayout(layout)

        self.nameWidget = QLabel(name)
        self.nameWidget.setAlignment(Qt.AlignRight)
        self.nameWidget.setFixedWidth(self.fontMetrics().averageCharWidth()*20)
        self.nameWidget.setCursor(Qt.PointingHandCursor)
        self.nameWidget.mouseDoubleClickEvent = self.nameMouseDoubleClickEvent
        self.nameWidget.contextMenuEvent = self.nameContextMenuEvent

        self.templateWidget = TemplateWidgets[template]()

        buttonsLayout = QHBoxLayout()
        buttonsLayout.setContentsMargins(0,0,0,0)
        upBtn = QPushButton("🔼")
        upBtn.setFixedSize(35, 25)
        upBtn.setToolTip("Move attribute up")
        upBtn.clicked.connect(self._onUpBtnClicked)

        downBtn = QPushButton("🔽")
        downBtn.setFixedSize(35, 25)
        downBtn.setToolTip("Move attribute down")
        downBtn.clicked.connect(self._onDownBtnClicked)

        removeBtn = QPushButton("❌")
        removeBtn.setFixedSize(35, 25)
        removeBtn.setToolTip("Remove attribute")
        removeBtn.clicked.connect(self._onRemoveBtnClicked)

        buttonsLayout.addWidget(upBtn)
        buttonsLayout.addWidget(downBtn)
        buttonsLayout.addWidget(removeBtn)

        layout.addWidget(self.nameWidget)
        layout.addWidget(self.templateWidget)
        layout.addLayout(buttonsLayout)

    def nameContextMenuEvent(self, event: QContextMenuEvent):
        menu = QMenu(self)
        titleAction = menu.addAction(self.nameWidget.text())
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
        presetsMenu.addAction("Save as Preset...", self._saveAsPreset)

        menu.popup(event.globalPos())

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
        if QMessageBox.question(self, "Rig Builder", "Remove '{}' attribute?".format(self.nameWidget.text()), QMessageBox.Yes and QMessageBox.No, QMessageBox.Yes) == QMessageBox.Yes:
            self.copyTemplate()
            self.deleteLater()

    def _onDownBtnClicked(self):
        editAttrsWidget = self.parent()
        idx = editAttrsWidget.attributesLayout.indexOf(self)
        if idx < editAttrsWidget.attributesLayout.count()-1:
            w = editAttrsWidget.insertCustomWidget(self.template, idx+2)
            w.templateWidget.setJsonData(self.templateWidget.getJsonData())
            w.nameWidget.setText(self.nameWidget.text())
            w.attrConnect = self.attrConnect
            w.attrExpression = self.attrExpression
            w.attrModified = self.attrModified
            self.deleteLater()

    def _onUpBtnClicked(self):
        editAttrsWidget = self.parent()
        idx = editAttrsWidget.attributesLayout.indexOf(self)
        if idx > 0:
            w = editAttrsWidget.insertCustomWidget(self.template, idx-1)
            w.templateWidget.setJsonData(self.templateWidget.getJsonData())
            w.nameWidget.setText(self.nameWidget.text())
            w.attrConnect = self.attrConnect
            w.attrExpression = self.attrExpression
            w.attrModified = self.attrModified
            self.deleteLater()

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
                w.attrModified = a.modified()

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
                presetsMenu.addAction(f"{name} ({data['template']})", partial(self._addFromPreset, data))        

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

    def _addFromPreset(self, presetData: dict):
        template = presetData["template"]
        data = presetData["data"]
        w = self.insertCustomWidget(template)
        if w:
            w.templateWidget.setJsonData(data)
            # Find unique name for the new attribute
            existingNames = {self.attributesLayout.itemAt(k).widget().nameWidget.text() for k in range(self.attributesLayout.count()) if self.attributesLayout.itemAt(k).widget()}
            w.nameWidget.setText(findUniqueName("attr_preset", existingNames))

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

        self.setTabBar(QTabBar())
        self.setMovable(True)
        self.setTabsClosable(True)
        self.tabBar().mouseDoubleClickEvent = self.tabBarMouseDoubleClickEvent
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

    def tabBarMouseDoubleClickEvent(self, event: QMouseEvent):
        super().mouseDoubleClickEvent(event)

        idx = self.currentIndex()
        newName, ok = QInputDialog.getText(self, "Rig Builder", "New name", QLineEdit.Normal, self.tabText(idx))
        if ok:
            self.setTabText(idx, newName)

    def _onTabCloseRequested(self, i: int):
        if QMessageBox.question(self, "Rig Builder", "Remove '{}' tab?".format(self.tabText(i)), QMessageBox.Yes and QMessageBox.No, QMessageBox.Yes) == QMessageBox.Yes:
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
        self.clear()

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
        origModuleModified = module.modified()

        newAttrs = self.buildAttributesFromTabs()
        newRunCode = self.tabWidget.tempRunCode

        module.removeAttributes()

        anythingChanged = len(origAttrs) != len(newAttrs)
        for a in newAttrs:
            module.addAttribute(a)
            if not a.name():
                continue

            orig = origByName.get(a.name())
            if orig is None or not attrMetaEqual(orig, a) or orig.modified():
                a._modified = True
                anythingChanged = True

        if module.runCode() != newRunCode:
            module.setRunCode(newRunCode)
            anythingChanged = True

        if not anythingChanged and not origModuleModified:
            module._modified = False

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
        # The model should ideally emit dataChanged, but since runCode isn't in columns,
        # we might just notify the window or emit an internal signal if needed.
        # For now, let's keep it simple.

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

        self.editorWidget.preset = id(self.module)
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

    def write(self, txt: str):
        self.insertPlainText(txt)
        self.ensureCursorVisible()

    def flush(self):
        return


class WideSplitterHandle(QSplitterHandle):
    def __init__(self, orientation: Qt.Orientation, parent: QWidget, **kwargs):
        super().__init__(orientation, parent, **kwargs)

    def paintEvent(self, event: QPaintEvent):
        painter = QPainter()
        if painter.begin(self):
            try:
                brush = QBrush()
                brush.setStyle(Qt.Dense6Pattern)
                brush.setColor(QColor(150, 150, 150))
                painter.fillRect(event.rect(), QBrush(brush))
            finally:
                painter.end()

class WideSplitter(QSplitter):
    def __init__(self, orientation: Qt.Orientation, width: int = 16, **kwargs):
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

    def updateWithState(self, state: Dict[str, object]):
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

# --- Server Management Dialog ---
class ManageHostsDialog(QDialog):
    hostsChanged = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)

        self.setWindowTitle("Manage Hosts")
        self.resize(480, 500)
        layout = QVBoxLayout(self)

        self.listWidget = QListWidget()
        layout.addWidget(self.listWidget)

        formLayout = QGridLayout()
        self.nameEdit = QLineEdit(); self.nameEdit.setPlaceholderText("Name (e.g. Maya 2025)")
        self.hostCombo = QComboBox()
        self.addressEdit = QLineEdit("localhost")
        self.repPortEdit = QLineEdit(); self.repPortEdit.setPlaceholderText("REP port")
        self.pubPortEdit = QLineEdit(); self.pubPortEdit.setPlaceholderText("PUB port")

        # Populate host types using server/hosts utility
        self.hostCombo.addItems(AVAILABLE_HOSTS)
        
        for row, (label, widget) in enumerate([
            ("Name", self.nameEdit), ("Host", self.hostCombo), ("Address", self.addressEdit),
            ("REP port", self.repPortEdit), ("PUB port", self.pubPortEdit)]):
            formLayout.addWidget(QLabel(label), row, 0)
            formLayout.addWidget(widget, row, 1)
        layout.addLayout(formLayout)

        self.codeEdit = QPlainTextEdit()
        self.codeEdit.setReadOnly(True)
        self.codeEdit.setFixedHeight(60)
        
        copyLayout = QHBoxLayout()
        copyLayout.addWidget(QLabel("Startup code:"))
        copyLayout.addStretch()
        self.copyBtn = QPushButton("📋")
        self.copyBtn.setToolTip("Copy to clipboard")
        self.copyBtn.clicked.connect(self._copyCode)
        copyLayout.addWidget(self.copyBtn)
        
        layout.addLayout(copyLayout)
        layout.addWidget(self.codeEdit)

        btnLayout = QHBoxLayout()
        addBtn = QPushButton("➕ Add")
        removeBtn = QPushButton("🗑️ Remove selected")
        closeBtn = QPushButton("🚪 Close")
        btnLayout.addWidget(addBtn)
        btnLayout.addWidget(removeBtn)
        btnLayout.addStretch()
        btnLayout.addWidget(closeBtn)
        layout.addLayout(btnLayout)

        addBtn.clicked.connect(self._add)
        removeBtn.clicked.connect(self._remove)
        closeBtn.clicked.connect(self.accept)

        self.listWidget.itemSelectionChanged.connect(self._onSelectionChanged)
        self.listWidget.itemDoubleClicked.connect(self._onItemDoubleClicked)
        self.hostCombo.currentIndexChanged.connect(self._refreshCode)
        self.addressEdit.textChanged.connect(self._refreshCode)
        self.repPortEdit.textChanged.connect(self._refreshCode)
        self.pubPortEdit.textChanged.connect(self._refreshCode)

        self._refreshList()

    def _onItemDoubleClicked(self, item):
        name = item.data(Qt.UserRole)
        entry = connectionManager.findServer(name)
        if entry:
            self.nameEdit.setText(name)
            
            idx = self.hostCombo.findText(entry["host"])
            self.hostCombo.setCurrentIndex(idx)

            self.addressEdit.setText(entry["address"])
            self.repPortEdit.setText(str(entry["rep_port"]))
            self.pubPortEdit.setText(str(entry["pub_port"]))
            self._refreshCode()

    def _onSelectionChanged(self):
        item = self.listWidget.currentItem()
        if item:
            self._onItemDoubleClicked(item)

    def _refreshCode(self):
        host = self.hostCombo.currentText().lower()
        if host == "standalone":
            self.codeEdit.setPlainText("# Standalone server is normally started from the UI")
            return

        HostClass = host.capitalize() + "Server"
        rep = self.repPortEdit.text() or "0"
        pub = self.pubPortEdit.text() or "0"

        try:
            code = HOST_STARTUP_TEMPLATE.format(
                HostClass=HostClass,
                host=host,
                rigBuilderPath=os.path.dirname(RigBuilderPath),
                rep_port=rep,
                pub_port=pub
            )
            self.codeEdit.setPlainText(code)
        except Exception as e:
            self.codeEdit.setPlainText("# Error generating code: " + str(e))

    def _copyCode(self):
        QApplication.clipboard().setText(self.codeEdit.toPlainText())
        self.copyBtn.setText("✅")
        QTimer.singleShot(1500, lambda: self.copyBtn.setText("📋"))

    def _refreshList(self):
        self.listWidget.clear()
        servers = connectionManager.servers()
        for name in sorted(servers.keys(), key=lambda x: x.lower()):
            entry = servers[name]
            label = "{} | {} | {}:{}/{}".format(
                name, entry["host"],
                entry["address"], entry["rep_port"], entry["pub_port"])
            
            item = QListWidgetItem(label)
            item.setData(Qt.UserRole, name)
            self.listWidget.addItem(item)

    def _add(self):
        try:
            connectionManager.addServer(
                self.nameEdit.text().strip(), self.hostCombo.currentText().strip(),
                self.addressEdit.text().strip(),
                int(self.repPortEdit.text() or "0"), int(self.pubPortEdit.text() or "0"))

            self.hostsChanged.emit()
            self._refreshList()
            self.nameEdit.clear(); self.repPortEdit.clear(); self.pubPortEdit.clear()

        except Exception as e:
            QMessageBox.warning(self, "Error", str(e))

    def _remove(self):
        item = self.listWidget.currentItem()
        if not item:
            return
            
        name = item.data(Qt.UserRole)
        connectionManager.removeServer(name)
        self.hostsChanged.emit()
        self._refreshList()


class RigBuilderWindow(QFrame):
    aboutToRunModule = Signal()

    def __init__(self):
        super().__init__()
        self.modulesAutoReloadWatcher = None

        self.setWindowTitle("Rig Builder {}".format(__version__))
        self.setGeometry(0, 0, 1300, 700)

        self.setWindowFlags(Qt.Window | Qt.WindowCloseButtonHint | Qt.WindowMinMaxButtonsHint)

        layout = QVBoxLayout()
        self.setLayout(layout)

        self.logWidget = LogWidget()
        self.logWidget.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Ignored)
        
        self._progressCounter = 0

        self.treeWidget = TreeWidget()
        self.treeWidget.selectionModel().selectionChanged.connect(self._onTreeSelectionChanged)

        self.attributesTabWidget = AttributesTabWidget()
        self.attributesTabWidget.moduleChanged.connect(partial(self.treeWidget.moduleModel.layoutChanged.emit)) # refresh tree
        self.attributesTabWidget.executionRequested.connect(self._onModuleExecutionRequested)
        self.attributesTabWidget.attributesChanged.connect(lambda: self.codeEditorWidget.updateState())

        self.codeEditorWidget = CodeEditorWidget()
        self.codeEditorWidget.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Ignored)
        self.codeEditorWidget.editorWidget.setPlaceholderText("Your module code...")

        self.vscodeBtn = QPushButton("📝 Edit in VSCode")
        self.vscodeBtn.clicked.connect(self.editInVSCode)
        self.vscodeBtn.setContextMenuPolicy(Qt.CustomContextMenu)
        self.vscodeBtn.customContextMenuRequested.connect(self.onVscodeBtnContextMenu)

        self.codeWidget = QWidget()
        self.codeWidget.setLayout(QVBoxLayout())
        self.codeWidget.layout().addWidget(self.codeEditorWidget)
        self.codeWidget.layout().addWidget(self.vscodeBtn)

        self.runBtn = QPushButton("🚀 Run")
        self.runBtn.setStyleSheet("background-color: #3e4f89")
        self.runBtn.clicked.connect(self.runModule)
        self.runBtn.hide()

        # --- Host picker row ---
        self.hostCombo = QComboBox()
        self.hostCombo.setPlaceholderText("No host")
        self.hostCombo.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self._refreshHostCombo()

        self.hostConnectBtn = QPushButton("🔗")
        self.hostConnectBtn.setCheckable(True)
        self.hostConnectBtn.setToolTip("Connect to selected host")
        self.hostConnectBtn.clicked.connect(self._onHostConnectClicked)

        self.hostManageBtn = QPushButton("⚙️")
        self.hostManageBtn.setToolTip("Manage hosts")
        self.hostManageBtn.clicked.connect(self._onManageHosts)

        self.windowPinBtn = QPushButton("📌")
        self.windowPinBtn.setCheckable(True)
        self.windowPinBtn.setToolTip("Pin window (stays on top)")
        self.windowPinBtn.clicked.connect(self._onTogglePin)
        self.windowPinBtn.setStyleSheet("QPushButton:checked { background-color: #3e7bd6; border-color: #6ea7ff; color: #ffffff; }")

        hostRow = QHBoxLayout()
        hostRow.setContentsMargins(0, 0, 0, 5)
        hostRow.addWidget(self.hostCombo)
        hostRow.addWidget(self.hostConnectBtn)
        hostRow.addWidget(self.hostManageBtn)
        hostRow.addWidget(self.windowPinBtn)

        self.hostRowWidget = QWidget()
        self.hostRowWidget.setLayout(hostRow)
        self.hostRowWidget.setStyleSheet("border-bottom: 1px solid #444; padding-bottom: 2px;")

        self.moduleHistoryWidget = ModuleHistoryWidget(self)
        self.moduleHistoryWidget.moduleAdditionRequested.connect(self._onModuleAdditionRequested)

        self.docBrowser = DocBrowser()
        self.docBrowser.moduleRequested.connect(self.selectModuleBySpec)

        self.rightSplitter = WideSplitter(Qt.Vertical, 4)
        self.rightSplitter.addWidget(self.attributesTabWidget)
        self.rightSplitter.addWidget(self.docBrowser)
        self.rightSplitter.setSizes([400, 100])
        self.rightSplitter.hide()

        rightWidget = QWidget()
        rightWidget.setLayout(QVBoxLayout())
        rightWidgetLayout = rightWidget.layout()
        rightWidgetLayout.setContentsMargins(0, 0, 0, 0)
        rightWidgetLayout.addWidget(self.moduleHistoryWidget)
        rightWidgetLayout.addWidget(self.rightSplitter)
        rightWidgetLayout.addWidget(self.runBtn)

        self.moduleSelectorWidget = ModuleSelectorWidget()

        self.leftSplitter = WideSplitter(Qt.Vertical, 8)
        self.leftSplitter.addWidget(self.treeWidget)
        self.leftSplitter.addWidget(self.moduleSelectorWidget)
        self.leftSplitter.setSizes([300, 200])

        self.mainContentSplitter = WideSplitter(Qt.Horizontal)
        self.mainContentSplitter.addWidget(self.leftSplitter)
        self.mainContentSplitter.addWidget(rightWidget)
        self.mainContentSplitter.setSizes([400, 600])

        self.workspaceSplitter = WideSplitter(Qt.Vertical)
        self.workspaceSplitter.addWidget(self.mainContentSplitter)
        self.workspaceSplitter.addWidget(self.codeWidget)
        self.workspaceSplitter.addWidget(self.logWidget)
        self.workspaceSplitter.setSizes([400, 0, 0])

        self.workspaceSplitter.splitterMoved.connect(self._onCodeSplitterMoved)
        self.codeWidget.setEnabled(False)

        self.progressBarWidget = MyProgressBar()
        self.progressBarWidget.hide()        
        self.treeWidget.addActions(getActions(self.menu()))
        setActionsLocalShortcut(self.treeWidget)

        layout.addWidget(self.hostRowWidget)
        layout.addWidget(self.workspaceSplitter)
        layout.addWidget(self.progressBarWidget)

        self.setupModulesAutoReloadWatcher()
        centerWindow(self)

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

    def setupModulesAutoReloadWatcher(self):
        """Setup the modules auto-reload watcher."""
        def onModulesReloaded():
            Module.updateUidsCache()
            self.moduleSelectorWidget.applyMask()

        watchRoots = [getPublicModulesPath(), getPrivateModulesPath()]
        self.modulesAutoReloadWatcher = DirectoryWatcher(
            watchRoots,
            filePatterns=["*.xml"],
            debounceMs=700,
            recursive=True,
            parent=self)

        self.modulesAutoReloadWatcher.somethingChanged.connect(onModulesReloaded)

    def _refreshHostCombo(self):
        """Repopulate the host dropdown from hosts.json."""
        self.hostCombo.blockSignals(True)
        self.hostCombo.clear()

        # Sort on UI side
        entries = sorted(connectionManager.servers().items(), key=lambda x: x[0].lower())
        for name, entry in entries:
            label = "{} ({})".format(name, entry["host"])
            self.hostCombo.addItem(label, userData=name)

        self.hostCombo.blockSignals(False)

    def _resetHostConnectionRow(self):
        """Disconnected UI state for the host row (no message boxes)."""
        self.hostConnectBtn.blockSignals(True)
        self.hostConnectBtn.setChecked(False)
        self.hostConnectBtn.setText("🔗")
        self.hostConnectBtn.setToolTip("Connect to selected host")
        self.hostConnectBtn.setEnabled(True)
        self.hostCombo.setEnabled(True)
        self.hostRowWidget.setStyleSheet("")
        self.hostConnectBtn.blockSignals(False)
        self.cleanupRun()

    def _onHostConnectionLost(self, reason: str):
        connectionManager.disconnect()
        QMessageBox.critical(self, "Rig Builder", "Connection to host lost.\n\n{}".format(reason))
        self._resetHostConnectionRow()

    def _onHostConnectClicked(self, checked: bool):
        """Toggle connection to the selected host."""

        name = self.hostCombo.currentData()

        if not checked or not name:
            connectionManager.disconnect()
            self._resetHostConnectionRow()
            return

        self.hostConnectBtn.setText("⏳ Connecting...")
        self.hostConnectBtn.setToolTip("Connecting...")
        self.hostConnectBtn.setEnabled(False)
        self.hostCombo.setEnabled(False)

        try:
            conn = connectionManager.connect(name, parent=self)
            conn.onConnectionLost.connect(self._onHostConnectionLost)

        except Exception as e:
            QMessageBox.warning(self, "Rig Builder", str(e))
            self._resetHostConnectionRow()
            return

        self.hostConnectBtn.setText("✂️")
        self.hostConnectBtn.setToolTip("Disconnect from host")
        self.hostConnectBtn.setEnabled(True)
        self.hostCombo.setEnabled(False)
        self.hostRowWidget.setStyleSheet("QWidget { color: #66cc66; }")

    def _onManageHosts(self):
        """Open a simple dialog to add/remove hosts."""
        dialog = ManageHostsDialog(parent=self)
        dialog.hostsChanged.connect(self._refreshHostCombo)
        dialog.exec()

    def _onTogglePin(self, checked: bool):
        """Toggle 'Stay on Top' window flag and update opacity."""
        self.setWindowFlag(Qt.WindowStaysOnTopHint, checked)
        self.show()

    def menu(self):
        menu = QMenu(self)

        menu.addAction("New", self.treeWidget.insertModule, "Insert")
        menu.addAction("Import", self.treeWidget.importModule, "Ctrl+I")
        menu.addAction("Import script", self.treeWidget.importScript)
        menu.addSeparator()
        menu.addAction("Save", self.treeWidget.saveModule, "Ctrl+S")
        menu.addAction("Save as", self.treeWidget.saveAsModule)
        menu.addAction("Publish", self.treeWidget.publishModule, "Ctrl+P")
        menu.addSeparator()

        menu.addAction("Locate file", self.locateModuleFile)
        menu.addAction("View edit history", self.showModuleInHistory, "Ctrl+H")
        menu.addSeparator()
        menu.addAction("Duplicate", self.treeWidget.duplicateModule, "Ctrl+D")
        menu.addSeparator()
        menu.addAction("Copy", self.treeWidget.copyModules, "Ctrl+C")
        menu.addAction("Cut", self.treeWidget.cutModules, "Ctrl+X")
        menu.addAction("Paste", self.treeWidget.pasteModules, "Ctrl+V")
        menu.addSeparator()

        diffMenu = menu.addMenu("Diff")
        diffMenu.addAction("vs File", self.diffModule, "Alt+D")
        diffMenu.addAction("vs Public", partial(self.diffModule, reference="public"), "Ctrl+Alt+D")

        menu.addAction("Update", self.treeWidget.updateModule, "Ctrl+U")
        menu.addAction("Embed", self.treeWidget.embedModule)

        menu.addSeparator()
        menu.addAction("Mute", self.treeWidget.muteModule, "M")
        menu.addAction("Remove", self.treeWidget.removeModule, "Delete")
        menu.addAction("Remove all", self.removeAllModules)

        menu.addAction("Documentation", self.showDocumenation, "F1")
        menu.addSeparator()
        menu.addAction("API Browser", self.openApiBrowser)
        menu.addAction("Function Browser", self.openFunctionBrowser)

        return menu

    def onVscodeBtnContextMenu(self, pos):
        menu = QMenu(self)
        menu.addAction("Set VSCode command", self.setVscodeCommand)
        menu.exec(self.vscodeBtn.mapToGlobal(pos))

    def setVscodeCommand(self):
        currentCommand = Settings.get("vscode", "vscode.exe")
        message = "VSCode command."
        command, ok = QInputDialog.getText(self, "Rig Builder", message, QLineEdit.Normal, currentCommand)
        if not ok:
            return

        Settings["vscode"] = command.strip()
        saveSettings()

    def addModule(self, module: Module) -> Optional[Module]:
        """Add a module to the tree and return it."""
        idx = self.treeWidget.moduleModel.addModuleAt(module)
        if idx.isValid():
            return self.treeWidget.moduleModel.getModule(idx)
        return None

    def selectModule(self, module: Module):
        """Select a module in the tree."""
        self.treeWidget.selectModule(module)

    def selectModuleBySpec(self, spec: str):
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

        if not shutil.which(Settings["vscode"]):
            msg = "Editor executable not found: {}\n\nPlease install the editor or update the VSCode command from the button context menu.".format(Settings["vscode"])
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
            if type(v) == str:
                return '"' + v + '"'
            try:
                jv = copyJson(v) # check if v is JSON serializable
            except Exception:
                return None
            return jv

        def onRunCodeFileChanged(filePath: str, uid: str, modulePath: str):
            # Try to find the "live" module in the tree (it might have been replaced)
            root = self.treeWidget.moduleModel.rootModule()
            targetModule = None

            def findByUid(m, uid):
                if m.uid() == uid: return m
                for ch in m.children():
                    res = findByUid(ch, uid)
                    if res: return res
                return None

            if uid:
                targetModule = findByUid(root, uid)
            
            if not targetModule:
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
            th.somethingChanged.connect(callback)
            th.start()
            trackFileChangesThreads[filePath] = th

        setupVscode()

        # generate header file
        fileName = module.path().lstrip("/").replace("/", "__")
        headerFile = os.path.join(RigBuilderPrivatePath, "vscode", "{}_header.py".format(fileName))
        runCodeFilePath = os.path.join(RigBuilderPrivatePath, "vscode", "{}.py".format(fileName))

        headerCode = []

        # expose attributes
        for a in module.attributes():
            headerCode.append("{}{} = {}".format(ATTR_PREFIX, a.name(), getVariableValue(a.get())))
            headerCode.append(getFunctionDefinition(a.set, name="{}set_{}".format(ATTR_PREFIX, a.name())))
            headerCode.append("{}{}_data = {}".format(ATTR_PREFIX, a.name(), a.localData()))

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

        startTrackedFileThread(runCodeFilePath, partial(onRunCodeFileChanged, runCodeFilePath, module.uid(), module.path()))

        try:
            subprocess.Popen([Settings["vscode"], RigBuilderPrivatePath+"/vscode", "-g", runCodeFilePath], shell=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        except Exception as e:
            QMessageBox.warning(self, "Editor Error", f"Failed to launch editor: {str(e)}")

    def diffModule(self, *, reference: Optional[str] = None):
        module = self.treeWidget.currentModule()
        if not module:
            return

        path = module.referenceFile(source=reference) if reference else module.filePath()
        if not path:
            QMessageBox.warning(self, "Rig Builder", "Can't find reference file")
            return

        path = os.path.normpath(path)
        currentXml = module.toXml()
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            originalXml = f.read()

        DiffBrowserDialog(originalXml, currentXml, path, "Current", parent=self).exec()
                    
    def removeAllModules(self):
        if QMessageBox.question(self, "Rig Builder", "Remove all modules?", QMessageBox.Yes and QMessageBox.No, QMessageBox.Yes) == QMessageBox.Yes:
            self.treeWidget.clear()

    def showDocumenation(self):
        subprocess.Popen(["explorer", "https://github.com/azagoruyko/rigBuilder/wiki/Documentation"])

    def openApiBrowser(self):
        from .apiBrowser import showApiBrowser
        showApiBrowser(parent=self)

    def openFunctionBrowser(self):
        from .functionBrowser import showFunctionBrowser
        browser = showFunctionBrowser(parent=self)
        browser.moduleAdditionRequested.connect(self._onModuleAdditionRequested)

    def _onModuleAdditionRequested(self, module: Module):
        """Handle module addition from external browsers."""
        added = self.addModule(module)
        self.show()
        self.raise_()
        self.activateWindow()
        if added:
            self.selectModule(added)

    def locateModuleFile(self):
        for module in self.treeWidget.selectedModules():
            if module and os.path.exists(module.filePath()):
                subprocess.call("explorer /select,\"{}\"".format(os.path.normpath(module.filePath())))

    def _onTreeSelectionChanged(self, selected, deselected):
        module = self.treeWidget.currentModule()
        en = module is not None
        self.rightSplitter.setVisible(en)
        self.runBtn.setVisible(en)
        self.moduleHistoryWidget.setVisible(not en)
        self.docBrowser.setVisible(en)
        self.codeWidget.setEnabled(en and not self.isCodeEditorHidden())

        if module:
            self.attributesTabWidget.updateTabs(module)

            if self.codeWidget.isEnabled():
                self.codeEditorWidget.module = module
                self.codeEditorWidget.updateState()
            
        self.docBrowser.updateDoc(module)


    def isCodeEditorHidden(self) -> bool:
        return self.workspaceSplitter.sizes()[1] == 0 # code section size

    def _onCodeSplitterMoved(self, sz: int, n: int):
        if self.isCodeEditorHidden():
            self.codeWidget.setEnabled(False)

        elif not self.codeWidget.isEnabled():
            module = self.treeWidget.currentModule()
            if module:
                self.codeEditorWidget.module = module
                self.codeEditorWidget.updateState()
                self.codeWidget.setEnabled(True)

    def showLog(self):
        sizes = self.workspaceSplitter.sizes()
        if sizes[-1] < 10:
            sizes[-1] = 200
            self.workspaceSplitter.setSizes(sizes)
        self.logWidget.ensureCursorVisible()

    def onConnectionErrorCallback(self, text: str):
        QMessageBox.warning(self, "Rig Builder", text)
        self._resetHostConnectionRow()
        self.cleanupRun()

    def onErrorCallback(self, text: str, tb: str):
        logger.error(text)
        printErrorStack()
        self.showLog()
        self.cleanupRun()

    def onPrintCallback(self, text: str):
        logger.info(text)

    def cleanupRun(self):
        self.progressBarWidget.endProgress()
        self.runBtn.setEnabled(True)  

    def onRunCallback(self, path: str):
        logger.info(f"{path} is running...")
        self.progressBarWidget.stepProgress(self._progressCounter, path)
        self._progressCounter += 1

    def onFinishedCallback(self):
        logger.info("Done!")

    def runModule(self):
        """Run module on the host server."""
        def getChildrenCount(m: Module) -> int:
            count = 0
            for ch in m.children():
                count += 1
                count += getChildrenCount(ch)
            return count

        currentModule = self.treeWidget.currentModule()
        if not currentModule:
            return

        self.setFocus()
        self.logWidget.clear()
        self.showLog()
        self.runBtn.setEnabled(False)

        count = getChildrenCount(currentModule)
        self.progressBarWidget.initialize()
        self.progressBarWidget.beginProgress(currentModule.path(), count + 1)
        self._progressCounter = 0

        self.aboutToRunModule.emit()
        ts = time.strftime("%Y-%m-%d %H:%M:%S")
        logger.info(f"[{ts}] Running on {connectionManager.activeServerName()}")

        newModule = hostExecutor.runModule(currentModule)

        if newModule is not None:
            idx = self.treeWidget.moduleModel.indexForModule(currentModule)
            if idx.isValid():
                self.treeWidget.replaceModule(idx, newModule)
                self.attributesTabWidget.updateTabs(newModule)
            else:            
                QMessageBox.warning(self, "Rig Builder", "Could not find module in tree")
        
        self.cleanupRun()

    def showModuleInHistory(self):
        """Put selected module UID into history browser filter and clear selection so user can view history."""
        module = self.treeWidget.currentModule()
        if not module:
            return

        if not module.uid():
            return
            
        self.moduleHistoryWidget.filterEdit.setText(module.uid())
        self.treeWidget.clearSelection()

    def closeEvent(self, event):
        # Terminate all file tracking threads before closing
        for thread in trackFileChangesThreads.values():
            if thread.isRunning():
                thread.stop()
                thread.wait(1000)  # Wait up to 1 second for thread to finish
        trackFileChangesThreads.clear()
        
        # Call parent close event
        super().closeEvent(event)

def setupVscode():  # path to .vscode folder
    settings = {
        "python.autoComplete.extraPaths": [],
    }

    folder = os.path.join(RigBuilderPrivatePath, "vscode", ".vscode")
    os.makedirs(folder, exist_ok=True)
    settingsFile = os.path.join(folder, "settings.json")

    if os.path.exists(settingsFile):
        with open(settingsFile, "r") as f:
            settings.update(json.load(f))

    context = hostExecutor.executeCode("import sys;hostSysPath=sys.path")
    settings["python.autoComplete.extraPaths"] = context.get("hostSysPath", [])

    with open(settingsFile, "w") as f:
        json.dump(settings, f, indent=4)

def cleanupVscode():
    vscodeFolder = RigBuilderPrivatePath+"/vscode"
    if not os.path.exists(vscodeFolder):
        return
    
    for f in os.listdir(vscodeFolder):
        if f.endswith(".py") or f.endswith(MODULE_EXT): # remove module files
            os.remove(os.path.join(vscodeFolder, f))

# global references

mainWindow = RigBuilderWindow()
logHandler.setTarget(mainWindow.logWidget)

hostExecutor.onConnectionError.connect(mainWindow.onConnectionErrorCallback)
hostExecutor.onPrint.connect(mainWindow.onPrintCallback)
hostExecutor.onError.connect(mainWindow.onErrorCallback)
hostExecutor.onRunCallback.connect(mainWindow.onRunCallback)
hostExecutor.onFinished.connect(mainWindow.onFinishedCallback)
hostExecutor.beginProgress.connect(mainWindow.progressBarWidget.beginProgress)
hostExecutor.stepProgress.connect(mainWindow.progressBarWidget.stepProgress)
hostExecutor.endProgress.connect(mainWindow.progressBarWidget.endProgress)
