import time
import json
import re
import os
import subprocess
import inspect
import sys
import shutil
import logging
from xml.sax.saxutils import escape

from PySide6.QtCore import *
from PySide6.QtGui import *
from PySide6.QtWidgets import *

from .core import *
from .editor import *
from . import widgets
from .utils import *
from .ui_utils import *

DCC = os.getenv("RIG_BUILDER_DCC") or "maya"
ParentWindow = None

if DCC == "maya":
    import maya.cmds as cmds
    import maya.OpenMayaUI as omui
    import maya.OpenMaya as om

    def getMayaMainWindow():
        """Get Maya main window for PySide6"""
        try:
            from shiboken6 import wrapInstance
            return wrapInstance(int(omui.MQtUtil.mainWindow()), QMainWindow)
        except ImportError:
            return
    
    ParentWindow = getMayaMainWindow()

updateFilesThread = None 
trackFileChangesThreads = {} # by file path


# === GLOBAL LOGGING SYSTEM ===
class RigBuilderLogHandler(logging.Handler):
    """Custom log handler that redirects to logWidget."""
    def __init__(self):
        super().__init__()
        self.logWidget = None
        
    def setLogWidget(self, logWidget):
        """Connect handler to specific logWidget."""
        self.logWidget = logWidget
        
    def emit(self, record):
        if self.logWidget:
            msg = self.format(record)
            self.logWidget.write(msg + '\n')

def sendToServer(module):
    '''
    Send module to server with SVN, Git, Perforce or other VCS.
    '''
    module.sendToServer() # copy file to server and add to VCS
    return True

class TrackFileChangesThread(QThread):
    somethingChanged = Signal()

    def __init__(self, filePath):
        super().__init__()
        self.filePath = filePath

    def run(self):
        lastModified = os.path.getmtime(self.filePath)
        while True:
            currentModified = os.path.getmtime(self.filePath)
            if currentModified != lastModified:
                self.somethingChanged.emit()
                lastModified = currentModified
            time.sleep(1)

def updateFilesFromServer():
    def update():
        '''
        Update files from server with SVN, Git, Perforce or other VCS.
        '''
        pass

    global updateFilesThread
    if not updateFilesThread or not updateFilesThread.isRunning():
        updateFilesThread = MyThread(update)
        updateFilesThread.start()

class MyThread(QThread):
    def __init__(self, runFunction):
        super().__init__()
        self.runFunction = runFunction

    def run(self):
        self.runFunction()

class AttributesWidget(QWidget):
    def __init__(self, moduleItem, attributes, *, mainWindow=None, **kwargs):
        super().__init__(**kwargs)

        self.mainWindow = mainWindow
        self.moduleItem = moduleItem

        self._attributeAndWidgets = [] # [attribute, nameWidget, templateWidget]

        layout = QGridLayout()
        layout.setDefaultPositioning(2, Qt.Horizontal)
        layout.setColumnStretch(1, 1)
        self.setLayout(layout)

        def executor(cmd, env=None):
            envUI = self.mainWindow.envUI()
            Module.globalEnv = envUI # update environment for runtime modules

            localEnv = dict(envUI)
            localEnv.update(self.moduleItem.module.env())
            localEnv.update(env or {})

            with captureOutput(self.mainWindow.logWidget):
                try:
                    exec(cmd, localEnv)
                except Exception as e:
                    self.mainWindow.logger.error(str(e))
                    self.mainWindow.showLog()
                else:
                    if cmd: # in case command is specified, no command can be used for obtaining completions
                        self.updateWidgets()
                        self.updateWidgetStyles()
            return localEnv

        for idx, a in enumerate(attributes):
            templateWidget = widgets.TemplateWidgets[a.template()](executor=executor)
            nameWidget = QLabel(a.name())

            self._attributeAndWidgets.append((a, nameWidget, templateWidget))
            
            self.updateWidget(idx)
            self.updateWidgetStyle(idx)

            templateWidget.somethingChanged.connect(lambda idx=idx: self.widgetOnChange(idx))

            nameWidget.setAlignment(Qt.AlignRight)
            nameWidget.setStyleSheet("QLabel:hover:!pressed{ background-color: #666666; }")
            nameWidget.contextMenuEvent = lambda event, idx=idx: self.nameContextMenuEvent(event, idx)

            layout.addWidget(nameWidget)
            layout.addWidget(templateWidget)

        layout.addWidget(QLabel())
        layout.setRowStretch(layout.rowCount(), 1)

    def connectionMenu(self, menu, module, attrWidgetIndex, path="/"):
        attr, _, _ = self._attributeAndWidgets[attrWidgetIndex]

        subMenu = QMenu(module.name())

        for a in module.attributes():
            if a.template() == attr.template() and a.name(): # skip empty names as well
                subMenu.addAction(a.name(), Callback(self.connectAttr, path+module.name()+"/"+a.name(), attrWidgetIndex))

        for ch in module.children():
            self.connectionMenu(subMenu, ch, attrWidgetIndex, path+module.name()+"/")

        if subMenu.actions():
            menu.addMenu(subMenu)

    def nameContextMenuEvent(self, event, attrWidgetIndex):
        attr, _, _ = self._attributeAndWidgets[attrWidgetIndex]

        menu = QMenu(self)

        if self.moduleItem and self.moduleItem.parent():
            makeConnectionMenu = menu.addMenu("Make connection")

            for a in self.moduleItem.module.parent().attributes():
                if a.template() == attr.template() and a.name(): # skip empty names as well
                    makeConnectionMenu.addAction(a.name(), Callback(self.connectAttr, "/"+a.name(), attrWidgetIndex))

            for ch in self.moduleItem.module.parent().children():
                if ch is not self.moduleItem.module:
                    self.connectionMenu(makeConnectionMenu, ch, attrWidgetIndex)

        if attr.connect():
            menu.addAction("Break connection", Callback(self.disconnectAttr, attrWidgetIndex))

        menu.addSeparator()

        menu.addAction("Edit data", Callback(self.editData, attrWidgetIndex))
        menu.addSeparator()
        menu.addAction("Edit expression", Callback(self.editExpression, attrWidgetIndex))

        if attr.expression():
            menu.addAction("Evaluate expression", Callback(self.updateWidget, attrWidgetIndex))
            menu.addAction("Clear expression", Callback(self.clearExpression, attrWidgetIndex))

        menu.addSeparator()
        menu.addAction("Expose", Callback(self.exposeAttr, attrWidgetIndex))
        menu.addSeparator()
        menu.addAction("Reset", Callback(self.resetAttr, attrWidgetIndex))

        menu.popup(event.globalPos())

    def _wrapper(f):
        def inner(self, attrWidgetIndex, *args, **kwargs):
            attr, _, widget = self._attributeAndWidgets[attrWidgetIndex]
            with captureOutput(self.mainWindow.logWidget):
                try:
                    return f(self, attrWidgetIndex, *args, **kwargs)
                
                except Exception as e:
                    self.mainWindow.logger.error(f"{self.moduleItem.module.name()}.{attr.name()}: {str(e)}")

                    if type(e) == AttributeResolverError:
                        widget.blockSignals(True)
                        widget.setJsonData(attr.localData())
                        widget.blockSignals(False)

                    self.mainWindow.showLog()

        return inner
    
    @_wrapper
    def widgetOnChange(self, attrWidgetIndex):
        attr, _, widget = self._attributeAndWidgets[attrWidgetIndex]

        widgetData = widget.getJsonData()
        attr.setData(widgetData) # implicitly push

        previousData = {id(a):a.localData() for a in self.moduleItem.module.attributes()}
        modifiedAttrs = []
        for otherAttr in self.moduleItem.module.attributes():
            otherAttr.pull()
            if otherAttr.localData() != previousData[id(otherAttr)]:
                modifiedAttrs.append(otherAttr)

        for idx, (otherAttr, _, otherWidget) in enumerate(self._attributeAndWidgets): # update attributes' widgets
            if otherAttr in modifiedAttrs:
                with blockedWidgetContext(otherWidget) as w:
                    w.setJsonData(otherAttr.localData())
                self.updateWidgetStyle(idx)

        if id(attr) not in modifiedAttrs: # update the modification style anyway
            self.updateWidgetStyle(attrWidgetIndex)       

    @_wrapper
    def updateWidget(self, attrWidgetIndex):
        attr, _, widget = self._attributeAndWidgets[attrWidgetIndex]
        with blockedWidgetContext(widget) as w:
            w.setJsonData(attr.data()) # pull data

    def updateWidgets(self):
        for i in range(len(self._attributeAndWidgets)):
            self.updateWidget(i)

    def updateWidgetStyle(self, attrWidgetIndex):
        attr, nameWidget, widget = self._attributeAndWidgets[attrWidgetIndex]

        style = ""
        tooltip = []
        if attr.connect():
            tooltip.append("Connect: "+attr.connect())
        if attr.expression():
            tooltip.append("Expression:\n" + attr.expression())

        if attr.connect() and not attr.expression(): # only connection
            style = "TemplateWidget { border: 4px solid #6e6e39; background-color: #6e6e39 }"
        
        elif attr.expression() and not attr.connect(): # only expression
            style = "TemplateWidget { border: 4px solid #632094; background-color: #632094 }"
        
        elif attr.expression() and attr.connect(): # both
            style = "TemplateWidget { border: 4px solid rgb(0,0,0,0); background: QLinearGradient( x1: 0, y1: 0, x2: 1, y2:0, stop: 0 #6e6e39, stop: 1 #632094);}"

        nameWidget.setText(attr.name()+("*" if attr.modified() else ""))

        widget.setStyleSheet(style)
        widget.setToolTip("\n".join(tooltip))

    def updateWidgetStyles(self):
        for i in range(len(self._attributeAndWidgets)):
            self.updateWidgetStyle(i)

    def exposeAttr(self, attrWidgetIndex):
        attr, _, _ = self._attributeAndWidgets[attrWidgetIndex]

        if not self.moduleItem.module.parent():
            QMessageBox.warning(self, "Rig Builder", "Can't expose attribute to parent: no parent module")
            return

        if self.moduleItem.module.parent().findAttribute(attr.name()):
            QMessageBox.warning(self, "Rig Builder", "Can't expose attribute to parent: attribute already exists")
            return

        doUsePrefix = QMessageBox.question(self, "Rig Builder", "Use prefix for the exposed attribute name?", QMessageBox.Yes and QMessageBox.No, QMessageBox.Yes) == QMessageBox.Yes
        prefix = self.moduleItem.module.name() + "_" if doUsePrefix else ""
        expAttr = attr.copy()
        expAttr.setName(prefix + expAttr.name())
        self.moduleItem.module.parent().addAttribute(expAttr)
        self.connectAttr("/"+expAttr.name(), attrWidgetIndex)

    @_wrapper
    def editData(self, attrWidgetIndex):
        def save(data):
            @AttributesWidget._wrapper
            def _save(_, attrWidgetIndex):
                attr.setData(data[0]) # use [0] because data is a list
                self.updateWidget(attrWidgetIndex)
                self.updateWidgetStyle(attrWidgetIndex)
            _save(self, attrWidgetIndex)

        attr, _, _ = self._attributeAndWidgets[attrWidgetIndex]
        w = widgets.EditJsonDialog(attr.localData(), title="Edit data")
        w.saved.connect(save)
        w.show()

    def editExpression(self, attrWidgetIndex):
        def save(text):
            attr.setExpression(text)
            self.updateWidgets()
            self.updateWidgetStyle(attrWidgetIndex)

        attr, _, _ = self._attributeAndWidgets[attrWidgetIndex]

        words = set(self.mainWindow.envUI().keys()) | set(self.moduleItem.module.env().keys())
        placeholder = '# Example: value = ch("../someAttr") + 1 or data["items"] = [1,2,3]'
        w = widgets.EditTextDialog(attr.expression(), title="Edit expression for '{}'".format(attr.name()), placeholder=placeholder, words=words, python=True)
        w.saved.connect(save)
        w.show()

    def clearExpression(self, attrWidgetIndex):
        attr, _, _ = self._attributeAndWidgets[attrWidgetIndex]
        attr.setExpression("")
        self.updateWidgetStyle(attrWidgetIndex)

    def resetAttr(self, attrWidgetIndex):
        attr, _, _ = self._attributeAndWidgets[attrWidgetIndex]

        tmp = widgets.TemplateWidgets[attr.template()]()
        attr.setConnect("")
        attr.setData(tmp.getDefaultData())
        self.updateWidget(attrWidgetIndex)
        self.updateWidgetStyle(attrWidgetIndex)

    def disconnectAttr(self, attrWidgetIndex):
        attr, _, _ = self._attributeAndWidgets[attrWidgetIndex]
        attr.setConnect("")
        self.updateWidgetStyle(attrWidgetIndex)

    def connectAttr(self, connect, attrWidgetIndex):
        attr, _, _ = self._attributeAndWidgets[attrWidgetIndex]
        attr.setConnect(connect)
        self.updateWidget(attrWidgetIndex)
        self.updateWidgetStyle(attrWidgetIndex)

class AttributesTabWidget(QTabWidget):
    def __init__(self, moduleItem, *, mainWindow=None, **kwargs):
        super().__init__(**kwargs)

        self.mainWindow = mainWindow
        self.moduleItem = moduleItem
        self.tabsAttributes = {}
        self._attributesWidget = None

        self.searchAndReplaceDialog = SearchReplaceDialog(["In all tabs"])
        self.searchAndReplaceDialog.onReplace.connect(self.onReplace)

        self.currentChanged.connect(self.tabChanged)
        self.updateTabs()

    def contextMenuEvent(self, event):
        menu = QMenu(self)

        if self.moduleItem:
            menu.addAction("Edit attributes", self.editAttributes)
            menu.addSeparator()
            menu.addAction("Replace in values", self.searchAndReplaceDialog.exec_)

        menu.popup(event.globalPos())

    def editAttributes(self):
        dialog = EditAttributesDialog(self.moduleItem, self.currentIndex(), parent=mainWindow)
        dialog.exec()

        self.mainWindow.codeEditorWidget.updateState()
        self.updateTabs()

    def onReplace(self, old, new, opts):
        def replaceStringInData(data, old, new):
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

    def tabChanged(self, idx):
        if self.count() == 0:
            return

        idx = clamp(idx, 0, self.count()-1)

        title = self.tabText(idx)
        scrollArea = self.widget(idx)
        self._attributesWidget = AttributesWidget(self.moduleItem, self.tabsAttributes[title], mainWindow=self.mainWindow)
        scrollArea.setWidget(self._attributesWidget)
        self.setCurrentIndex(idx)

    def updateTabs(self):
        oldIndex = self.currentIndex()
        oldCount = self.count()

        self._attributesWidget = None
        self.tabsAttributes.clear()

        if not self.moduleItem:
            return

        self.blockSignals(True)

        tabTitlesInOrder = []
        for a in self.moduleItem.module.attributes():
            if a.category() not in self.tabsAttributes:
                self.tabsAttributes[a.category()] = []
                tabTitlesInOrder.append(a.category())

            self.tabsAttributes[a.category()].append(a)

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

        self.tabChanged(oldIndex)
        self.blockSignals(False)

    def updateWidgetStyles(self):
        if self._attributesWidget:
            self._attributesWidget.updateWidgetStyles()

class ModuleListDialog(QDialog):
    moduleSelected = Signal(str) # file path

    def __init__(self, **kwargs):
        super().__init__(**kwargs)

        self.setWindowTitle("Module Selector")

        layout = QVBoxLayout()
        self.setLayout(layout)

        gridLayout = QGridLayout()
        gridLayout.setDefaultPositioning(2, Qt.Horizontal)

        self.updateSourceWidget = QComboBox()
        self.updateSourceWidget.addItems(["All", "Server", "Local", "None"])
        self.updateSourceWidget.setCurrentIndex({"all":0, "server": 1, "local": 2, "": 3}[Module.UpdateSource])
        self.updateSourceWidget.currentIndexChanged.connect(lambda _=None: self.updateSource())

        self.modulesFromWidget = QComboBox()
        self.modulesFromWidget.addItems(["Server", "Local"])
        self.modulesFromWidget.currentIndexChanged.connect(lambda _=None: self.maskChanged())

        self.maskWidget = QLineEdit()
        self.maskWidget.textChanged.connect(self.maskChanged)

        gridLayout.addWidget(QLabel("Update source"))
        gridLayout.addWidget(self.updateSourceWidget)

        gridLayout.addWidget(QLabel("Modules from"))
        gridLayout.addWidget(self.modulesFromWidget)

        gridLayout.addWidget(QLabel("Filter"))
        gridLayout.addWidget(self.maskWidget)

        self.treeWidget = QTreeWidget()
        self.treeWidget.setHeaderLabels(["Module", "Modification time"])
        self.treeWidget.itemActivated.connect(self.treeItemActivated)
        self.treeWidget.header().setSectionResizeMode(QHeaderView.ResizeToContents)

        self.treeWidget.setSortingEnabled(True)
        self.treeWidget.sortItems(1, Qt.AscendingOrder)
        self.treeWidget.contextMenuEvent = self.treeContextMenuEvent

        self.loadingLabel = QLabel("Pulling modules from server...")
        self.loadingLabel.hide()

        layout.addLayout(gridLayout)
        layout.addWidget(self.treeWidget)
        layout.addWidget(self.loadingLabel)

        self.maskWidget.setFocus()

    def showEvent(self, event):
        pos = self.mapToParent(self.mapFromGlobal(QCursor.pos()))
        self.setGeometry(pos.x(), pos.y(), 600, 400)

        # update files from server
        self.loadingLabel.show()
        updateFilesFromServer()
        def f():
            Module.updateUidsCache()
            self.loadingLabel.hide()
            self.maskChanged()
        updateFilesThread.finished.connect(f)

        self.maskWidget.setFocus()

    def treeContextMenuEvent(self, event):
        menu = QMenu(self)
        menu.addAction("Locate", self.browseModuleDirectory)
        menu.popup(event.globalPos())

    def browseModuleDirectory(self):
        for item in self.treeWidget.selectedItems():
            if item.childCount() == 0: # files only
                subprocess.call("explorer /select,\"{}\"".format(os.path.normpath(item.filePath)))

    def treeItemActivated(self, item, _):
        if item.childCount() == 0:
            self.moduleSelected.emit(item.filePath)
            self.done(0)

    def updateSource(self):
        updateSource = self.updateSourceWidget.currentIndex()
        UpdateSourceFromInt = {0: "all", 1: "server", 2: "local", 3: ""}
        Module.UpdateSource = UpdateSourceFromInt[updateSource]

    def maskChanged(self):
        def findChildByText(text, parent, column=0):
            for i in range(parent.childCount()):
                ch = parent.child(i)
                if text == ch.text(column):
                    return ch

        modulesFrom = self.modulesFromWidget.currentIndex()
        modulesDirectory = RigBuilderPath+"\\modules" if modulesFrom == 0 else RigBuilderLocalPath+"\\modules"
        modules = list(Module.ServerUids.values()) if modulesFrom == 0 else list(Module.LocalUids.values())
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
                        font = ch.font(0)
                        font.setBold(True)
                        ch.setForeground(0, QColor(130, 130, 230))
                        ch.setFont(0, font)

                        dirItem.addChild(ch)
                        dirItem.setExpanded(True if mask else False)
                        dirItem = ch

            modtime = time.strftime("%Y/%m/%d %H:%M", time.localtime(os.path.getmtime(f)))
            item = QTreeWidgetItem([name, modtime])
            item.filePath = f
            dirItem.addChild(item)
            dirItem.setExpanded(True if mask else False)

class ModuleItem(QTreeWidgetItem):
    def __init__(self, module, **kwargs):
        super().__init__(**kwargs)
        self.module = module

        self.setFlags(Qt.ItemIsSelectable | Qt.ItemIsEnabled | Qt.ItemIsEditable | Qt.ItemIsDragEnabled | Qt.ItemIsDropEnabled)

    def clone(self):
        item = ModuleItem(self.module.copy())
        for i in range(self.childCount()):
            item.addChild(self.child(i).clone())
        return item

    def data(self, column, role):
        if column == 0: # name
            if role == Qt.EditRole:
                return self.module.name()

            elif role == Qt.DisplayRole:
                return self.module.name() + ("*" if self.module.modified() else " ")

            elif role == Qt.ForegroundRole:
                isParentMuted = False
                isParentReferenced = False

                parent = self.parent()
                while parent:
                    isParentMuted = isParentMuted or parent.module.muted()
                    isParentReferenced = isParentReferenced or parent.module.uid()
                    parent = parent.parent()

                color = QColor(200, 200, 200)

                if isParentReferenced:
                    color = QColor(140, 140, 180)

                if self.module.muted() or isParentMuted:
                    color = QColor(100, 100, 100)

                return color

            elif role == Qt.BackgroundRole:
                if not re.match("\\w*", self.module.name()):
                    return QColor(170, 50, 50)

                itemParent = self.parent()
                if itemParent and len([ch for ch in itemParent.module.children() if ch.name() == self.module.name()]) > 1:
                    return QColor(170, 50, 50)

                return super().data(column, role)

        elif column == 1: # path
            if role == Qt.DisplayRole:
                return self.module.relativePathString().replace("\\", "/") + " "

            elif role == Qt.EditRole:
                return "(not editable)"

            elif role == Qt.FontRole:
                font = QFont()
                font.setItalic(True)
                return font

            elif role == Qt.ForegroundRole:
                return QColor(125, 125, 125)

        elif column == 2: # source
            source = ""
            if self.module.loadedFromLocal():
                source = "local"
            elif self.module.loadedFromServer():
                source = "server"

            if role == Qt.DisplayRole:
                return source + " "

            elif role == Qt.EditRole:
                return "(not editable)"

            elif role == Qt.ForegroundRole:
                if source == "local":
                    return QColor(120, 220, 120)
                elif source == "server":
                    return QColor(120, 120, 120)

        elif column == 3: # uid
            if role == Qt.DisplayRole:
                return self.module.uid()[:8]
            elif role == Qt.EditRole:
                return "(not editable)"
            elif role == Qt.ForegroundRole:
                return QColor(125, 125, 170)
        else:
            return super().data(column, role)

    def setData(self, column, role, value):
        if column == 0:
            if role == Qt.EditRole:
                newName = replaceSpecialChars(value).strip()
                if self.parent():
                    existingNames = set([ch.name() for ch in self.parent().module.children() if ch is not self.module])
                    newName = findUniqueName(newName, existingNames)

                connections = self._saveConnections(self.module) # rename in connections
                self.module.setName(newName)
                self.treeWidget().resizeColumnToContents(column)
                self._updateConnections(connections)
        else:
            return super().setData(column, role, value)

    def _saveConnections(self, currentModule):
        connections = []
        for a in currentModule.attributes():
            connections.append({"attr":a, "module": currentModule, "connections":a.listConnections()})

        for ch in currentModule.children():
            connections += self._saveConnections(ch)
        return connections

    def _updateConnections(self, connections):
        for data in connections:
            srcAttr = data["attr"]
            module = data["module"]
            for a in data["connections"]:
                c = module.path().replace(a.module().path(inclusive=False), "") + "/" + srcAttr.name()
                a.setConnect(c) # update connection path
    
    # === UI API METHODS ===
    
    def getLogger(self):
        """Get logger from main window."""
        treeWidget = self.treeWidget()
        if treeWidget and treeWidget.mainWindow:
            return treeWidget.mainWindow.logger        
    
    def addAttribute(self, name, template, category="General", **kwargs):
        """Add attribute to this module. Returns Attribute instance."""
        attribute = Attribute()
        attribute.setName(name)
        attribute.setTemplate(template)
        attribute.setCategory(category)
        
        # Set additional properties from kwargs
        if 'connect' in kwargs:
            attribute.setConnect(kwargs['connect'])
        if 'expression' in kwargs:
            attribute.setExpression(kwargs['expression'])
        if 'data' in kwargs:
            attribute.setData(kwargs['data'])
        elif 'defaultValue' in kwargs:
            # Helper to set default value directly
            defaultData = widgets.TemplateWidgets[template]().getDefaultData()
            if 'default' in defaultData:
                defaultData[defaultData['default']] = kwargs['defaultValue']
            attribute.setData(defaultData)
        
        self.module.addAttribute(attribute)
        self.emitDataChanged()
        return attribute
    
    def removeAttribute(self, attrName):
        """Remove attribute by name."""
        attribute = self.module.findAttribute(attrName)
        if attribute:
            self.module.removeAttribute(attribute)
            self.emitDataChanged()
        else:
            self.getLogger().warning(f"Module '{self.module.name()}': Attribute '{attrName}' not found")
    
    def findAttribute(self, attrName):
        """Find attribute by name."""
        return self.module.findAttribute(attrName)
    
    def attributes(self):
        """Get all attributes for this module."""
        return self.module.attributes()
    
    def run(self):
        """Run this module programmatically."""
        self.module.run()
    
    def validateModule(self):
        """Validate this module and log any errors found. Returns True if valid."""
        hasErrors = False
        module = self.module
        
        # Check module name
        if not re.match(r"^\w+$", module.name()):
            self.getLogger().error(f"Module '{module.name()}': Invalid module name (only alphanumeric characters and underscore allowed)")
            hasErrors = True
        
        # Check for duplicate child names
        childNames = [ch.name() for ch in module.children()]
        duplicates = [name for name in childNames if childNames.count(name) > 1]
        if duplicates:
            self.getLogger().error(f"Module '{module.name()}': Duplicate child module names: {list(set(duplicates))}")
            hasErrors = True
        
        # Check attributes
        for attr in module.attributes():
            if not attr.template():
                self.getLogger().error(f"Module '{module.name()}': Attribute '{attr.name()}' has no template")
                hasErrors = True
            elif attr.template() not in widgets.TemplateWidgets:
                self.getLogger().error(f"Module '{module.name()}': Unknown template '{attr.template()}' for attribute '{attr.name()}'")
                hasErrors = True
            
            # Check attribute connections
            if attr.connect():
                try:
                    srcAttr = attr.findConnectionSource()
                    if not srcAttr:
                        self.getLogger().error(f"Module '{module.name()}': Attribute '{attr.name()}' has invalid connection '{attr.connect()}'")
                        hasErrors = True
                except Exception as e:
                    self.getLogger().error(f"Module '{module.name()}': Attribute '{attr.name()}' connection error: {str(e)}")
                    hasErrors = True
        
        return not hasErrors
    
    def saveModule(self, filePath=None):
        """Save this module to file."""
        outputPath = filePath or self.module.getSavePath()
        if not outputPath:
            self.getLogger().error(f"Module '{self.module.name()}': No file path specified for saving")
            return
            
        dirname = os.path.dirname(outputPath)
        if not os.path.exists(dirname):
            os.makedirs(dirname)
            
        self.module.saveToFile(outputPath)
        self.emitDataChanged()  # Update path display
    
    def addModule(self, childModule):
        """Add child module. Returns ModuleItem for the child."""
        if isinstance(childModule, str):
            # Create new module with given name
            module = Module()
            module.setName(childModule)
        else:
            # Assume it's already a Module instance
            module = childModule
        
        childItem = ModuleItem(module)
        self.addChild(childItem)
        self.module.addChild(module)
        self.emitDataChanged()
        return childItem
    
    def removeModule(self, childItem):
        """Remove child module."""
        if childItem in [self.child(i) for i in range(self.childCount())]:
            self.removeChild(childItem)
            self.module.removeChild(childItem.module)
            self.emitDataChanged()
        else:
            self.getLogger().warning(f"Module '{self.module.name()}': Child module not found")

class TreeWidget(QTreeWidget):
    def __init__(self, *, mainWindow=None, **kwargs):
        super().__init__(**kwargs)

        self.mainWindow = mainWindow
        self.dragItems = [] # using in drag & drop
        self.clipboard = []  # Module clipboard for copy/paste

        self.moduleListDialog = ModuleListDialog()
        self.moduleListDialog.moduleSelected.connect(self.addModuleFromBrowser)

        self.setHeaderLabels(["Name", "Path", "Source", "UID"])
        self.setSelectionMode(QAbstractItemView.ExtendedSelection) # ExtendedSelection

        self.header().setSectionResizeMode(QHeaderView.ResizeToContents)

        self.setDragEnabled(True)
        self.setDragDropMode(QAbstractItemView.InternalMove)
        self.setDropIndicatorShown(True)
        self.setAcceptDrops(True)

        self.setIndentation(30)

    def paintEvent(self, event):
        super().paintEvent(event)
        label = "Press TAB to load modules"

        fontMetrics = QFontMetrics(self.font())
        viewport = self.viewport()

        with QPainter(viewport) as painter:
            painter.setPen(QColor(90,90,90))
            painter.drawText(viewport.width() - getFontWidth(fontMetrics, label)-10, viewport.height()-10, label)

    def dragEnterEvent(self, event):
        super().dragEnterEvent(event)

        if event.mimeData().hasUrls():
            event.accept()            
        elif event.mouseButtons() == Qt.MiddleButton:
            self.dragItems = self.selectedItems()
        else:
            event.ignore()

    def dragMoveEvent(self, event):
        super().dragMoveEvent(event)

        if event.mimeData().hasUrls():
            event.setDropAction(Qt.CopyAction)

    def dropEvent(self, event):
        super().dropEvent(event)

        if event.mimeData().hasUrls():
            event.setDropAction(Qt.CopyAction)
            for url in event.mimeData().urls():
                path = url.toLocalFile()

                with captureOutput(self.mainWindow.logWidget):
                    try:
                        m = Module.loadFromFile(path)
                        m.update()
                        self.addTopLevelItem(self.makeItemFromModule(m))

                    except ET.ParseError as e:
                        self.mainWindow.logger.error(f"'{path}': {str(e)} - invalid module")
                        self.mainWindow.showLog()
        else:
            for item in self.dragItems:
                if item.module.parent(): # remove from old parent
                    item.module.parent().removeChild(item.module)

                newParent = item.parent()
                if newParent:
                    if newParent.module.findChild(item.module.name()):
                        existingNames = set([ch.name() for ch in newParent.module.children()])
                        item.module.setName(findUniqueName(item.module.name(), existingNames))

                    idx = newParent.indexOfChild(item)
                    newParent.module.insertChild(idx, item.module)
                    newParent.emitDataChanged()

            self.dragItems = []

    def makeItemFromModule(self, module):
        item = ModuleItem(module)

        for ch in module.children():
            item.addChild(self.makeItemFromModule(ch))

        return item

    def contextMenuEvent(self, event):
        self.mainWindow.menu().popup(event.globalPos())

    def sendModuleToServer(self):
        selectedItems = self.selectedItems()
        if not selectedItems:
            return

        msg = "\n".join([item.module.name() for item in selectedItems])

        if QMessageBox.question(self, "Rig Builder", "Send modules to server?\n"+msg, QMessageBox.Yes and QMessageBox.No, QMessageBox.Yes) != QMessageBox.Yes:
            return

        for item in selectedItems:
            if item.module.loadedFromLocal():
                if sendToServer(item.module):
                    QMessageBox.information(self, "Rig Builder", "Module '{}' has successfully been sent to server".format(item.module.name()))

            else:
                QMessageBox.warning(self, "Rig Builder", "Can't send '{}' to server.\nIt works for local modules only!".format(item.module.name()))

    def insertModule(self):
        m = Module()
        m.setName("module")
        item = self.makeItemFromModule(m)

        sel = self.selectedItems()
        if sel:
            sel[0].addChild(item)
            sel[0].module.addChild(item.module)
        else:
            self.addTopLevelItem(item)

    def importModule(self):
        sceneDir = RigBuilderLocalPath + "/modules"

        if DCC == "maya":
            sceneDir = os.path.dirname(om.MFileIO.currentFile())

        filePath, _ = QFileDialog.getOpenFileName(mainWindow, "Import", sceneDir, "*.xml")

        if not filePath:
            return

        Module.updateUidsCache()

        try:
            m = Module.loadFromFile(filePath)
            m.update()
            self.addTopLevelItem(self.makeItemFromModule(m))

        except ET.ParseError:
            self.mainWindow.logger.error(f"'{filePath}': invalid module")
            self.mainWindow.showLog()

    def saveModule(self):
        selectedItems = self.selectedItems()
        if not selectedItems:
            return

        msg = "\n".join(["{} -> {}".format(item.module.name(), item.module.getSavePath() or "N/A") for item in selectedItems])

        if QMessageBox.question(self, "Rig Builder", "Save modules?\n"+msg, QMessageBox.Yes and QMessageBox.No, QMessageBox.Yes) != QMessageBox.Yes:
            return

        for item in selectedItems:
            outputPath = item.module.getSavePath()

            if not outputPath:
                outputPath, _ = QFileDialog.getSaveFileName(mainWindow, "Save "+item.module.name(), RigBuilderLocalPath+"/modules/"+item.module.name(), "*.xml")

            if outputPath:
                dirname = os.path.dirname(outputPath)
                if not os.path.exists(dirname):
                    os.makedirs(dirname)

                try:
                    item.module.saveToFile(outputPath)
                except Exception as e:
                    QMessageBox.critical(self, "Rig Builder", "Can't save module '{}': {}".format(item.module.name(), str(e)))
                else:
                    item.emitDataChanged() # path changed
                    self.mainWindow.attributesTabWidget.updateWidgetStyles()

    def saveAsModule(self):
        for item in self.selectedItems():
            outputDir = os.path.dirname(item.module.filePath()) or RigBuilderLocalPath+"/modules"
            outputPath, _ = QFileDialog.getSaveFileName(mainWindow, "Save as "+item.module.name(), outputDir + "/" +item.module.name(), "*.xml")

            if outputPath:
                try:
                    item.module.saveToFile(outputPath, newUid=True)
                except Exception as e:
                    QMessageBox.critical(self, "Rig Builder", "Can't save module '{}': {}".format(item.module.name(), str(e)))
                else:
                    item.emitDataChanged() # path and uid changed
                    self.mainWindow.attributesTabWidget.updateWidgetStyles()

    def embedModule(self):
        selectedItems = self.selectedItems()
        if not selectedItems:
            return

        msg = "\n".join([item.module.name() for item in selectedItems])

        if QMessageBox.question(self, "Rig Builder", "Embed modules?\n"+msg, QMessageBox.Yes and QMessageBox.No, QMessageBox.Yes) != QMessageBox.Yes:
            return

        for item in selectedItems:
            item.module.embed()
            item.emitDataChanged() # path and uid changed

    def updateModule(self):
        selectedItems = self.selectedItems()
        if not selectedItems:
            return

        Module.updateUidsCache()

        msg = "\n".join([item.module.name() for item in selectedItems])
        if QMessageBox.question(self, "Rig Builder", "Update modules?\n"+msg, QMessageBox.Yes and QMessageBox.No, QMessageBox.Yes) != QMessageBox.Yes:
            return

        for item in selectedItems:
            if not item.module.uid():
                QMessageBox.warning(self, "Rig Builder", "Can't update module '{}': no uid".format(item.module.name()))
                continue

            item.module.update()

            newItem = self.makeItemFromModule(item.module)

            expanded = item.isExpanded()

            if item.parent():
                parent = item.parent()
                idx = parent.indexOfChild(item)
                parent.removeChild(item)
                parent.insertChild(idx, newItem)

                parent.module.removeChild(item.module)
                parent.module.insertChild(idx, newItem.module)

            else:
                parent = self.invisibleRootItem()
                idx = parent.indexOfChild(item)
                parent.removeChild(item)
                parent.insertChild(idx, newItem)

            newItem.setExpanded(expanded)
            newItem.setSelected(True)

    def muteModule(self):
        for item in self.selectedItems():
            if item.module.muted():
                item.module.unmute()
            else:
                item.module.mute()
            item.emitDataChanged()

    def duplicateModule(self):
        newItems = []
        for item in self.selectedItems():
            newItem = self.makeItemFromModule(item.module.copy())
            if item.parent():
                existingNames = set([ch.name() for ch in item.parent().module.children()])
                newItem.module.setName(findUniqueName(item.module.name(), existingNames))

            parent = item.parent()
            if parent:
                parent.addChild(newItem)
                parent.module.addChild(newItem.module)
            else:
                self.addTopLevelItem(newItem)

            newItems.append(newItem)

        self.clearSelection()
        for item in newItems:
            item.setSelected(True)

    def copyModules(self):
        """Copy selected modules to clipboard."""
        selectedItems = self.selectedItems()
        if not selectedItems:
            return
            
        self.clipboard = []
        for item in selectedItems:
            self.clipboard.append(item.module.copy())
        
        self.mainWindow.logger.info(f"Copied {len(self.clipboard)} module(s)")

    def cutModules(self):
        """Cut selected modules to clipboard."""
        selectedItems = self.selectedItems()
        if not selectedItems:
            return
            
        self.clipboard = []
        for item in selectedItems:
            self.clipboard.append(item.module.copy())
        
        self.mainWindow.logger.info(f"Cut {len(self.clipboard)} module(s)")
        
        # Remove the cut modules without confirmation
        self.removeModule(askConfirmation=False)

    def pasteModules(self):
        """Paste modules from clipboard."""
        if not self.clipboard:
            return
            
        selectedItems = self.selectedItems()
        parent = selectedItems[0] if selectedItems else None
        
        pastedItems = []
        for module in self.clipboard:
            newModule = module.copy()  # Make another copy to avoid reference issues
            
            # Ensure unique names
            if parent:
                existingNames = set([ch.name() for ch in parent.module.children()])
                newModule.setName(findUniqueName(newModule.name(), existingNames))
            
            newItem = self.makeItemFromModule(newModule)
            
            if parent:
                parent.addChild(newItem)
                parent.module.addChild(newModule)
            else:
                self.addTopLevelItem(newItem)
            
            pastedItems.append(newItem)
        
        # Select pasted items
        self.clearSelection()
        for item in pastedItems:
            item.setSelected(True)
            
        self.mainWindow.logger.info(f"Pasted {len(pastedItems)} module(s)")

    def removeModule(self, *, askConfirmation=True):
        selectedItems = self.selectedItems()
        if not selectedItems:
            return

        if askConfirmation:
            msg = "\n".join([item.module.name() for item in selectedItems])
            if QMessageBox.question(self, "Rig Builder", "Remove modules?\n"+msg, QMessageBox.Yes and QMessageBox.No, QMessageBox.Yes) != QMessageBox.Yes:
                return

        for item in selectedItems:
            parent = item.parent()
            if parent:
                parent.removeChild(item)
                parent.module.removeChild(item.module)
                parent.emitDataChanged()
            else:
                self.invisibleRootItem().removeChild(item)

    def addModuleFromBrowser(self, modulePath):
        m = Module.loadFromFile(modulePath)
        m.update()
        self.addTopLevelItem(self.makeItemFromModule(m))

        # add to recent modules
        recentModules = self.mainWindow.infoWidget.recentModules
        for rm in list(recentModules):
            if rm.uid() == m.uid(): # remove the previous one
                recentModules.remove(rm)
                break

        recentModules.insert(0, m)
        if len(recentModules) > 10:
            recentModules.pop()

        return m

    def browseModuleSelector(self, *, mask=None, updateSource=None, modulesFrom=None):
        if mask:
            self.moduleListDialog.maskWidget.setText(mask)

        if updateSource:
            self.moduleListDialog.updateSourceWidget.setCurrentIndex({"all":0, "server": 1, "local": 2, "": 3}[updateSource])

        if modulesFrom:
            self.moduleListDialog.modulesFromWidget.setCurrentIndex({"server": 0, "local": 1}[modulesFrom])

        self.moduleListDialog.exec()

    def event(self, event):
        if event.type() == QEvent.KeyPress:
            if event.key() == Qt.Key_Tab:
                self.browseModuleSelector()
                self.mainWindow.updateInfo()
                event.accept()
                return True

        return QTreeWidget.event(self, event)

class TemplateSelectorDialog(QDialog):
    selectedTemplate = Signal(str)

    def __init__(self, **kwargs):
        super().__init__(**kwargs)

        self.setWindowTitle("Template Selector")
        self.setGeometry(0, 0, 700, 500)

        layout = QVBoxLayout()
        self.setLayout(layout)

        self.filterWidget = QLineEdit()
        self.filterWidget.textChanged.connect(self.updateTemplates)

        scrollWidget = QWidget()
        scrollArea = QScrollArea()
        scrollArea.setWidget(scrollWidget)
        scrollArea.setWidgetResizable(True)

        self.gridLayout = QGridLayout()
        scrollWidget.setLayout(self.gridLayout)

        self.gridLayout.setDefaultPositioning(3, Qt.Horizontal)
        self.gridLayout.setColumnStretch(1, 1)

        layout.addWidget(self.filterWidget)
        layout.addWidget(scrollArea)
        self.filterWidget.setFocus()

        self.updateTemplates()
        centerWindow(self)

    def selectTemplate(self, t):
        self.selectedTemplate.emit(t)
        self.done(0)

    def updateTemplates(self):
        clearLayout(self.gridLayout)

        filterText = self.filterWidget.text()

        for t in sorted(widgets.TemplateWidgets.keys()):
            if not filterText or re.search(filterText, t, re.IGNORECASE):
                self.gridLayout.addWidget(QLabel(t))
                w  = widgets.TemplateWidgets[t]()
                w.setJsonData(w.getDefaultData())
                self.gridLayout.addWidget(w)

                selectBtn = QPushButton("Select")
                selectBtn.clicked.connect(lambda _=None,t=t: self.selectTemplate(t))
                self.gridLayout.addWidget(selectBtn)

class EditTemplateWidget(QWidget):
    Clipboard = []
    nameChanged = Signal(str, str)

    def __init__(self, name, template, **kwargs):
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
        self.nameWidget.mouseDoubleClickEvent = self.nameMouseDoubleClickEvent
        self.nameWidget.contextMenuEvent = self.nameContextMenuEvent
        self.nameWidget.setStyleSheet("QLabel:hover:!pressed{ background-color: #666666; }")

        self.templateWidget = widgets.TemplateWidgets[template]()

        buttonsLayout = QHBoxLayout()
        buttonsLayout.setContentsMargins(0,0,0,0)
        upBtn = QPushButton("<")
        upBtn.setFixedSize(25, 25)
        upBtn.clicked.connect(self.upBtnClicked)

        downBtn = QPushButton(">")
        downBtn.setFixedSize(25, 25)
        downBtn.clicked.connect(self.downBtnClicked)

        removeBtn = QPushButton("x")
        removeBtn.setFixedSize(25, 25)
        removeBtn.clicked.connect(self.removeBtnClicked)

        buttonsLayout.addWidget(upBtn)
        buttonsLayout.addWidget(downBtn)
        buttonsLayout.addWidget(removeBtn)

        layout.addWidget(self.nameWidget)
        layout.addWidget(self.templateWidget)
        layout.addLayout(buttonsLayout)

    def nameContextMenuEvent(self, event):
        menu = QMenu(self)

        menu.addAction("Copy", self.copyTemplate)

        if EditTemplateWidget.Clipboard and EditTemplateWidget.Clipboard[0]["template"] == self.template:
            menu.addAction("Paste", Callback(self.templateWidget.setJsonData, EditTemplateWidget.Clipboard[0]["data"]))

        menu.popup(event.globalPos())

    def copyTemplate(self):
        module = {"data": self.templateWidget.getJsonData(),
                  "template": self.template,
                  "name": self.nameWidget.text()}

        EditTemplateWidget.Clipboard = [module]

    def nameMouseDoubleClickEvent(self, event):
        oldName = self.nameWidget.text()
        newName, ok = QInputDialog.getText(self, "Rig Builder", "New name", QLineEdit.Normal, oldName)
        if ok:
            newName = replaceSpecialChars(newName)
            self.nameWidget.setText(newName)
            self.nameChanged.emit(oldName, newName)

    def removeBtnClicked(self):
        if QMessageBox.question(self, "Rig Builder", "Remove '{}' attribute?".format(self.nameWidget.text()), QMessageBox.Yes and QMessageBox.No, QMessageBox.Yes) == QMessageBox.Yes:
            self.copyTemplate()
            self.deleteLater()

    def downBtnClicked(self):
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

    def upBtnClicked(self):
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

    def __init__(self, moduleItem, category, **kwargs):
        super().__init__(**kwargs)

        self.moduleItem = moduleItem
        self.category = category

        layout = QVBoxLayout()
        self.setLayout(layout)

        self.attributesLayout = QVBoxLayout()

        for a in self.moduleItem.module.attributes():
            if a.category() == self.category:
                w = self.insertCustomWidget(a.template())
                w.nameWidget.setText(a.name())
                w.templateWidget.setJsonData(a.data())
                w.attrConnect = a.connect()
                w.attrExpression = a.expression()
                w.attrModified = a.modified()

        layout.addLayout(self.attributesLayout)
        layout.addStretch()

    def contextMenuEvent(self, event):
        menu = QMenu(self)

        menu.addAction("Add", self.addTemplateAttribute)
        menu.addAction("Copy visible", self.copyVisibleAttributes)

        if EditTemplateWidget.Clipboard:
            menu.addAction("Paste", self.pasteAttribute)

        menu.popup(event.globalPos())

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

    def addTemplateAttribute(self):
        selector = TemplateSelectorDialog(parent=mainWindow)
        selector.selectedTemplate.connect(lambda t: self.insertCustomWidget(t))
        selector.exec()

    def insertCustomWidget(self, template, row=None):
        if not widgets.TemplateWidgets.get(template):
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
    def __init__(self, moduleItem, currentIndex=0, **kwargs):
        super().__init__(**kwargs)

        self.moduleItem = moduleItem
        self.tempRunCode = moduleItem.module.runCode()

        self.setTabBar(QTabBar())
        self.setMovable(True)
        self.setTabsClosable(True)
        self.tabBar().mouseDoubleClickEvent = self.tabBarMouseDoubleClickEvent
        self.tabCloseRequested.connect(self.tabCloseRequest)

        tabTitlesInOrder = []
        for a in self.moduleItem.module.attributes():
            if a.category() not in tabTitlesInOrder:
                tabTitlesInOrder.append(a.category())

        for t in tabTitlesInOrder:
            self.addTabCategory(t)

        if self.count() == 0:
            self.addTabCategory("General")

        self.setCurrentIndex(currentIndex)

    def addTabCategory(self, category):
        w = EditAttributesWidget(self.moduleItem, category)
        w.nameChanged.connect(self.nameChangedCallback)

        scrollArea = QScrollArea()
        scrollArea.setWidget(w)
        scrollArea.setWidgetResizable(True)
        self.addTab(scrollArea, category)
        self.setCurrentIndex(self.count()-1)

    def nameChangedCallback(self, oldName, newName):
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
            attr = self.moduleItem.module.findAttribute(oldName)
            if attr:
                for a in attr.listConnections():
                    c = self.moduleItem.module.path().replace(attr.module().path(inclusive=False), "") + "/" + newName # update connection path
                    a.setConnect(c)

    def tabBarMouseDoubleClickEvent(self, event):
        super().mouseDoubleClickEvent(event)

        idx = self.currentIndex()
        newName, ok = QInputDialog.getText(self, "Rig Builder", "New name", QLineEdit.Normal, self.tabText(idx))
        if ok:
            self.setTabText(idx, newName)

    def tabCloseRequest(self, i):
        if QMessageBox.question(self, "Rig Builder", "Remove '{}' tab?".format(self.tabText(i)), QMessageBox.Yes and QMessageBox.No, QMessageBox.Yes) == QMessageBox.Yes:
            self.setCurrentIndex(i-1)
            self.clearTab(i)

    def contextMenuEvent(self, event):
        menu = QMenu(self)
        menu.addAction("New tab", Callback(self.addTabCategory, "Untitled"))
        menu.popup(event.globalPos())

    def clearTab(self, i):
        self.widget(i).deleteLater()
        self.removeTab(i)

    def clearTabs(self):
        for _ in range(self.count()):
            self.clearTab(0)
        self.clear()

class EditAttributesDialog(QDialog):
    def __init__(self, moduleItem, currentIndex=0, **kwargs):
        super().__init__(**kwargs)

        self.moduleItem = moduleItem

        self.setWindowTitle("Edit Attributes - " + self.moduleItem.module.name())
        self.setGeometry(0, 0, 800, 600)

        layout = QVBoxLayout()
        self.setLayout(layout)

        self.tabWidget = EditAttributesTabWidget(self.moduleItem, currentIndex)

        okBtn = QPushButton("Ok")
        okBtn.clicked.connect(self.saveAttributes)
        cancelBtn = QPushButton("Cancel")
        cancelBtn.clicked.connect(self.close)

        hlayout = QHBoxLayout()
        hlayout.addWidget(okBtn)
        hlayout.addWidget(cancelBtn)

        layout.addWidget(self.tabWidget)
        layout.addLayout(hlayout)

        centerWindow(self)

    def saveAttributes(self):
        self.moduleItem.module.removeAttributes()

        for i in range(self.tabWidget.count()):
            attrsLayout = self.tabWidget.widget(i).widget().attributesLayout # tab/scrollArea/EditAttributesWidget

            for k in range(attrsLayout.count()):
                w = attrsLayout.itemAt(k).widget()

                a = Attribute()
                a.setName(w.nameWidget.text())
                a.setData(w.templateWidget.getJsonData())
                a.setTemplate(w.template)
                a.setCategory(self.tabWidget.tabText(i))
                a.setConnect(w.attrConnect)
                a.setExpression(w.attrExpression)
                self.moduleItem.module.addAttribute(a)

        self.moduleItem.module.setRunCode(self.tabWidget.tempRunCode)
        self.moduleItem.emitDataChanged()
        self.accept()

class CodeEditorWidget(CodeEditorWithNumbersWidget):
    def __init__(self, moduleItem=None, *, mainWindow=None, **kwargs):
        super().__init__(**kwargs)

        self.mainWindow = mainWindow
        self.moduleItem = moduleItem
        self._skipSaving = False

        self.editorWidget.textChanged.connect(self.codeChanged)

        self.updateState()

    def codeChanged(self):
        if not self.moduleItem or self._skipSaving:
            return

        self.moduleItem.module.setRunCode(self.editorWidget.toPlainText())
        self.moduleItem.emitDataChanged()

    def updateState(self):
        if not self.moduleItem:
            return

        self.editorWidget.ignoreStates = True
        self._skipSaving = True
        self.editorWidget.setText(self.moduleItem.module.runCode())
        self._skipSaving = False
        self.editorWidget.ignoreStates = False

        self.editorWidget.document().clearUndoRedoStacks()
        self.generateCompletionWords()

        self.editorWidget.preset = id(self.moduleItem)
        self.editorWidget.loadState()

    def generateCompletionWords(self):
        if not self.moduleItem:
            return

        words = set(self.mainWindow.envUI().keys()) | set(self.moduleItem.module.env().keys())

        for a in self.moduleItem.module.attributes():
            words.add("@" + a.name())
            words.add("@" + a.name() + "_data")
            words.add("@set_" + a.name())

        self.editorWidget.words = words

class LogHighligher(QSyntaxHighlighter):
    def __init__(self, parent):
        super().__init__(parent)

        self.highlightingRules = []

        warningFormat = QTextCharFormat()
        warningFormat.setForeground(QColor(250, 150, 90))
        self.highlightingRules.append(("(?i)\\b\\w*warning\\b", warningFormat))

        errorFormat = QTextCharFormat()
        errorFormat.setForeground(QColor(250, 90, 90))
        self.highlightingRules.append(("(?i)\\b\\w*error\\b", errorFormat))

    def highlightBlock(self, text):
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

    def write(self, txt):
        self.insertPlainText(txt)
        self.ensureCursorVisible()
        QApplication.processEvents()

class WideSplitterHandle(QSplitterHandle):
    def __init__(self, orientation, parent, **kwargs):
        super().__init__(orientation, parent, **kwargs)

    def paintEvent(self, event):
        with QPainter(self) as painter:
            brush = QBrush()
            brush.setStyle(Qt.Dense6Pattern)
            brush.setColor(QColor(150, 150, 150))
            painter.fillRect(event.rect(), QBrush(brush))

class WideSplitter(QSplitter):
    def __init__(self, orientation, **kwargs):
        super().__init__(orientation, **kwargs)
        self.setHandleWidth(16)

    def createHandle(self):
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

    def updateWithState(self, state):
        trimText = lambda text, size: "..." + text[-size+3:]  if len(text) > size else " "*(size-len(text)) + text
        self.labelWidget.setText(trimText(state["text"], self.labelSize))
        self.progressBarWidget.setValue(state["value"])
        self.progressBarWidget.setMaximum(state["max"])

    def beginProgress(self, text, count, updatePercent=0.01):
        q = {"text": text, "max": count, "value": 0, "updatePercent":updatePercent}
        self.queue.append(q)
        self.updateWithState(q)
        self.show()

    def stepProgress(self, value, text=None):
        q = self.queue[-1]
        q["value"] = value

        updateValue = int(clamp(q["max"] * q["updatePercent"], 1, q["max"]))

        if not q["updatePercent"] or value % updateValue == 0:
            if text:
                q["text"] = text
            self.updateWithState(q)
            QApplication.processEvents()

    def endProgress(self):
        self.queue.pop()
        if not self.queue:
            self.hide()
        else:
            q = self.queue[-1] # get latest state
            self.updateWithState(q)


class RigBuilderWindow(QFrame):
    # === API SIGNALS ===
    moduleSelected = Signal(object)  # ModuleItem
    moduleAdded = Signal(object)     # ModuleItem  
    moduleRemoved = Signal(object)   # ModuleItem
    moduleChanged = Signal(object)   # ModuleItem
    attributeChanged = Signal(object, object)  # ModuleItem, Attribute
    
    def __init__(self):
        super().__init__(parent=ParentWindow)

        self.setWindowTitle("Rig Builder")
        self.setGeometry(0, 0, 1300, 700)

        self.setWindowFlags(self.windowFlags() | Qt.Window)

        layout = QVBoxLayout()
        self.setLayout(layout)

        self.logWidget = LogWidget()
        self.logWidget.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Ignored)
        
        # Create isolated logger for this window
        self.logger = logging.getLogger(f'rigbuilder.window_{id(self)}')
        self.logger.setLevel(logging.DEBUG)
        
        # Create isolated log handler for this window
        self.logHandler = RigBuilderLogHandler()
        self.logHandler.setLogWidget(self.logWidget)
        self.logHandler.setFormatter(logging.Formatter('%(levelname)s: %(message)s'))
        self.logger.addHandler(self.logHandler)

        self.attributesTabWidget = AttributesTabWidget(None, mainWindow=self)
        self.attributesTabWidget.hide()

        self.treeWidget = TreeWidget(mainWindow=self)
        self.treeWidget.itemSelectionChanged.connect(self.treeItemSelectionChanged)

        self.codeEditorWidget = CodeEditorWidget(mainWindow=self)
        self.codeEditorWidget.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Ignored)
        self.codeEditorWidget.editorWidget.setPlaceholderText("Your module code...")

        vscodeBtn = QPushButton("Edit in VSCode")
        vscodeBtn.clicked.connect(self.editInVSCode)
        codeWidget = QWidget()
        codeWidget.setLayout(QVBoxLayout())
        codeWidget.layout().addWidget(vscodeBtn)
        codeWidget.layout().addWidget(self.codeEditorWidget)

        self.runBtn = QPushButton("Run!")
        self.runBtn.setStyleSheet("background-color: #3e4f89")
        self.runBtn.clicked.connect(self.runModule)
        self.runBtn.hide()

        self.infoWidget = QTextBrowser()
        self.infoWidget.anchorClicked.connect(self.infoLinkClicked)
        self.infoWidget.setOpenLinks(False)
        self.infoWidget.recentModules = []
        self.updateInfo()


        attrsToolsWidget = QWidget()
        attrsToolsWidget.setLayout(QVBoxLayout())
        attrsToolsWidget.layout().addWidget(self.infoWidget)
        attrsToolsWidget.layout().addWidget(self.attributesTabWidget)
        attrsToolsWidget.layout().addWidget(self.runBtn)

        hsplitter = WideSplitter(Qt.Horizontal)
        hsplitter.addWidget(self.treeWidget)
        hsplitter.addWidget(attrsToolsWidget)
        hsplitter.setSizes([400, 600])

        self.vsplitter = WideSplitter(Qt.Vertical)
        self.vsplitter.addWidget(hsplitter)
        self.vsplitter.addWidget(codeWidget)
        self.vsplitter.addWidget(self.logWidget)
        self.vsplitter.setSizes([400, 0, 0])

        self.vsplitter.splitterMoved.connect(self.codeSplitterMoved)
        self.codeEditorWidget.setEnabled(False)

        self.progressBarWidget = MyProgressBar()
        self.progressBarWidget.hide()

        self.treeWidget.addActions(getActions(self.menu()))
        setActionsLocalShortcut(self.treeWidget)

        layout.addWidget(self.vsplitter)
        layout.addWidget(self.progressBarWidget)

        centerWindow(self)

    def menu(self):
        menu = QMenu(self)

        menu.addAction("New", self.treeWidget.insertModule, "Insert")
        menu.addAction("Import", self.treeWidget.importModule, "Ctrl+I")
        menu.addSeparator()
        menu.addAction("Save", self.treeWidget.saveModule, "Ctrl+S")
        menu.addAction("Save as", self.treeWidget.saveAsModule)
        menu.addAction("Send to server", self.treeWidget.sendModuleToServer)
        menu.addSeparator()

        menu.addAction("Locate file", self.locateModuleFile)
        menu.addAction("Copy tool code", self.copyToolCode)
        menu.addSeparator()
        menu.addAction("Duplicate", self.treeWidget.duplicateModule, "Ctrl+D")
        menu.addSeparator()
        menu.addAction("Copy", self.treeWidget.copyModules, "Ctrl+C")
        menu.addAction("Cut", self.treeWidget.cutModules, "Ctrl+X")
        if self.treeWidget.clipboard:
            menu.addAction("Paste", self.treeWidget.pasteModules, "Ctrl+V")
        menu.addSeparator()

        diffMenu = menu.addMenu("Diff")
        diffMenu.addAction("vs File", lambda: self.diffModule())
        diffMenu.addAction("vs Server", lambda: self.diffModule(reference="server"))

        menu.addAction("Update", self.treeWidget.updateModule, "Ctrl+U")
        menu.addAction("Embed", self.treeWidget.embedModule)

        menu.addSeparator()
        menu.addAction("Mute", self.treeWidget.muteModule, "M")
        menu.addAction("Remove", self.treeWidget.removeModule, "Delete")
        menu.addAction("Clear all", self.clearAllModules)

        menu.addAction("Documentation", self.showDocumenation)

        return menu

    def editInVSCode(self):
        def getFunctionDefinition(f, *, name=None): # f(a,b,c=1) => 'def f(a,b,c=1):pass'
            signature = inspect.signature(f)
            args = []
            for p in signature.parameters.values():
                if p.default == p.empty:
                    args.append(p.name)
                else:
                    args.append("{}={}".format(p.name, p.default))
            return "def {}({}):pass".format(name or f.__name__, ", ".join(args))

        def getVariableValue(v):
            if type(v) == str:
                return '"' + v + '"'

            try:
                _ = json.dumps(v) # check if v is JSON serializable
            except:
                return None

            return v
        
        def onFileChangeCallback(module, filePath):    
            with open(filePath, "r") as f:
                lines = f.read().splitlines()

            code = "\n".join(lines[1:]) # skip first line: import predefined things
            code = re.sub(r"\battr_(\w+)\b", r'@\1', code)
            module.setRunCode(code)
            self.codeEditorWidget.updateState()

        selectedItems = self.treeWidget.selectedItems()
        if not selectedItems:
            return
        
        setupVscode()        
        
        module = selectedItems[0].module

        # generate predefined things
        fileName = module.path().replace("/", "__")
        predefinedFile = "{}/vscode/{}_predef.py".format(RigBuilderLocalPath, fileName)
        moduleFile = "{}/vscode/{}.py".format(RigBuilderLocalPath, fileName)

        predefinedCode = []

        # expose attributes
        for a in module.attributes():
            predefinedCode.append("attr_{} = {}".format(a.name(), getVariableValue(a.get())))
            predefinedCode.append(getFunctionDefinition(a.set, name="attr_set_"+a.name()))
            predefinedCode.append("attr_{}_data = {}".format(a.name(), a.data()))

        # expose API
        env = {}
        env.update(module.env())
        env.update(self.envUI()) # ui functions

        for k, v in env.items():
            if callable(v):
                predefinedCode.append(getFunctionDefinition(v))
            else:
                predefinedCode.append("{} = {}".format(k, getVariableValue(v)))

        with open(predefinedFile, "w") as f:
            f.write("\n".join(predefinedCode))

        with open(moduleFile, "w") as f:
            predefinedModule = os.path.splitext(os.path.basename(predefinedFile))[0]
            code = re.sub(r'@(\w+)', r'attr_\1', module.runCode())
            importLine = "from .{} import * # must be the first line".format(predefinedModule)
            f.write("\n".join([importLine, code]))
        
        if moduleFile in trackFileChangesThreads:
            trackFileChangesThreads[moduleFile].terminate()
        
        th = TrackFileChangesThread(moduleFile)
        th.somethingChanged.connect(lambda module=module, path=moduleFile: onFileChangeCallback(module, path))
        th.start()
        trackFileChangesThreads[moduleFile] = th
        
        if not shutil.which(Settings["vscode"]):
            QMessageBox.warning(self, "Editor Error", f"Editor executable not found: {Settings['vscode']}\n\nPlease install the editor or update the path in settings.json")
            return
            
        try:
            subprocess.Popen([Settings["vscode"], RigBuilderLocalPath+"/vscode", "-g", moduleFile], shell=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        except Exception as e:
            QMessageBox.warning(self, "Editor Error", f"Failed to launch editor: {str(e)}")

    def diffModule(self, *, reference=None):
        import webbrowser
        import html
        import difflib
        diff = difflib.HtmlDiff(wrapcolumn=120)

        selectedItems = self.treeWidget.selectedItems()
        if not selectedItems:
            return
        
        module = selectedItems[0].module
        
        path = module.referenceFile(source=reference) if reference else module.filePath()
        if path:
            path = os.path.normpath(path)
            currentXml = module.toXml()

            with open(path, "r") as f:
                originalXml = f.read()

            tmpFile = os.path.expandvars("$TEMP/rigBuilderDiff.html")
            diffHtml = diff.make_file(originalXml.splitlines(), currentXml.splitlines(), 
                                      fromdesc=html.escape(path), 
                                      todesc="Current",
                                      context=True, numlines=3)
            with open(tmpFile, "w") as f:
                f.write(diffHtml)
            webbrowser.open("file://"+tmpFile)
        else:
            QMessageBox.warning(self, "Rig Builder", "Can't find reference file")
                    
    def copyToolCode(self):
        selectedItems = self.treeWidget.selectedItems()
        if selectedItems:
            item = selectedItems[0]
            if item.module.loadedFromLocal() or item.module.loadedFromServer():
                code = '''import rigBuilder;rigBuilder.RigBuilderTool(r"{}").show()'''.format(item.module.relativePath())
                QApplication.clipboard().setText(code)
            else:
                QMessageBox.critical(self, "Rig Builder", "Module must be loaded from local or server!")

    def clearAllModules(self):
        if QMessageBox.question(self, "Rig Builder", "Remove all modules?", QMessageBox.Yes and QMessageBox.No, QMessageBox.Yes) == QMessageBox.Yes:
            self.treeWidget.clear()

    def showDocumenation(self):
        subprocess.Popen(["explorer", "https://github.com/azagoruyko/rigBuilder/wiki/Documentation"])

    def locateModuleFile(self):
        for item in self.treeWidget.selectedItems():
            if item and os.path.exists(item.module.filePath()):
                subprocess.call("explorer /select,\"{}\"".format(os.path.normpath(item.module.filePath())))

    def treeItemSelectionChanged(self):
        selectedItems = self.treeWidget.selectedItems()
        en = True if selectedItems else False
        self.attributesTabWidget.setVisible(en)
        self.runBtn.setVisible(en)
        self.infoWidget.setVisible(not en)
        self.codeEditorWidget.setEnabled(en and not self.isCodeEditorHidden())

        if selectedItems:
            item = selectedItems[0]

            self.attributesTabWidget.moduleItem = item
            self.attributesTabWidget.updateTabs()

            if self.codeEditorWidget.isEnabled():
                self.codeEditorWidget.moduleItem = item
                self.codeEditorWidget.updateState()
            
            # Validate module and log errors
            if not item.validateModule():
                # Show log if validation failed
                self.showLog()
            
            # Emit API signal
            self.moduleSelected.emit(item)

    def infoLinkClicked(self, url):
        scheme = url.scheme()
        path = url.path()

        self.treeWidget.browseModuleSelector(mask=path+".", modulesFrom="server" if scheme == "server" else "local")
        self.updateInfo()

    def updateInfo(self):
        self.infoWidget.clear()
        template = []

        # recent modules
        template.append("<center><h2 style='background-color: #666666'>Recent modules</h2></center>")

        for m in self.infoWidget.recentModules:
            prefix = "local" if m.loadedFromLocal() else "server"
            relPath = m.relativePath().replace(".xml","").replace("\\", "/")
            template.append("<p><a style='color: #55aaee' href='{0}:{1}'>{1}</a> {0}</p>".format(prefix, relPath))

        # recent updates
        template.append("<center><h2 style='background-color: #666666'>Recent updates</h2></center>")

        # local modules
        def displayFiles(files, *, local):
            prefix = "local" if local else "server"
            for k, v in files.items():
                if v:
                    template.append("<h3 style='background-color: #393939'>{}</h3>".format(escape(k)))
                    root = RigBuilderLocalPath+"/modules" if local else RigBuilderPath+"/modules"
                    for file in v:
                        relPath = calculateRelativePath(file, root).replace(".xml", "").replace("\\", "/")
                        template.append("<p><a style='color: #55aaee' href='{0}:{1}'>{1}</a></p>".format(prefix, escape(relPath)))

        files = categorizeFilesByModificationTime(Module.LocalUids.values())
        if files:
            template.append("<h2 style='background-color: #444444'>Local modules</h2>")
            displayFiles(files, local=True)

        files = categorizeFilesByModificationTime(Module.ServerUids.values())
        if files:
            template.append("<h2 style='background-color: #444444'>Server modules</h2>")
            displayFiles(files, local=False)

        self.infoWidget.insertHtml("".join(template))
        self.infoWidget.moveCursor(QTextCursor.Start)

    def isCodeEditorHidden(self):
        return self.vsplitter.sizes()[1] == 0 # code section size

    def codeSplitterMoved(self, sz, n):
        selectedItems = self.treeWidget.selectedItems()

        if self.isCodeEditorHidden():
            self.codeEditorWidget.setEnabled(False)

        elif not self.codeEditorWidget.isEnabled() and selectedItems:
            self.codeEditorWidget.moduleItem = selectedItems[0]
            self.codeEditorWidget.updateState()
            self.codeEditorWidget.setEnabled(True)

    def showLog(self):
        sizes = self.vsplitter.sizes()
        if sizes[-1] < 10:
            sizes[-1] = 200
            self.vsplitter.setSizes(sizes)
        self.logWidget.ensureCursorVisible()

    def envUI(self):
        return {"beginProgress": self.progressBarWidget.beginProgress,
                "stepProgress": self.progressBarWidget.stepProgress,
                "endProgress": self.progressBarWidget.endProgress,
                "currentTabIndex": self.attributesTabWidget.currentIndex()}    

    def runModule(self, moduleItem=None):
        """Run module with full UI support (progress, undo, logging)."""
        # Determine which module to run
        if moduleItem:
            currentItem = moduleItem
        else:
            selectedItems = self.selectedModules()
            if not selectedItems:
                self.logger.warning("No module selected for execution")
                return
            currentItem = selectedItems[0]

        self.logger.info(f"Running module: {currentItem.module.name()}")

        def uiCallback(module):
            self.logger.info(f"{module.path()} is running...")
            self.progressBarWidget.stepProgress(self.progressCounter, module.path())
            self.progressCounter += 1

        def getChildrenCount(item):
            count = 0
            for i in range(item.childCount()):
                count += 1
                count += getChildrenCount(item.child(i))
            return count

        self.setFocus()

        self.logWidget.clear()
        self.showLog()

        with captureOutput(self.logWidget):
            startTime = time.time()

            self.progressBarWidget.initialize()
            self.progressCounter = 0

            count = getChildrenCount(currentItem)
            self.progressBarWidget.beginProgress(currentItem.module.name(), count+1)

            muted = currentItem.module.muted()
            currentItem.module.unmute()

            Module.globalEnv = self.envUI() # for runtime module

            # Run with Maya undo support if available
            try:
                if DCC == "maya":
                    cmds.undoInfo(ock=True) # open undo chunk
                    
                currentItem.module.run(uiCallback=uiCallback)
                
            except ModuleRuntimeError as e:
                self.logger.error(str(e))
            except Exception as e:
                self.logger.error(f"Unexpected error in module '{currentItem.module.name()}': {str(e)}")
                printErrorStack()
            finally:
                if DCC == "maya":
                    cmds.undoInfo(cck=True) # close undo chunk
                    
                if muted:
                    currentItem.module.mute()

                executionTime = time.time() - startTime
                self.logger.info(f"Execution completed in {executionTime:.2f}s")

        self.progressBarWidget.endProgress()
        self.attributesTabWidget.updateTabs()

    # === API METHODS FOR MODULE MANAGEMENT ===
    
    def addModule(self, moduleOrPath, parent=None):
        """Add module to the tree. Returns ModuleItem or None if failed."""
        try:
            if isinstance(moduleOrPath, str):
                # Load from file path
                module = Module.loadFromFile(moduleOrPath)
                module.update()
            else:
                # Assume it's already a Module instance
                module = moduleOrPath
            
            moduleItem = self.treeWidget.makeItemFromModule(module)
            
            if parent:
                parent.addChild(moduleItem)
                parent.module.addChild(module)
            else:
                self.treeWidget.addTopLevelItem(moduleItem)
            
            self.moduleAdded.emit(moduleItem)
            return moduleItem
            
        except Exception as e:
            self.logger.error(f"Adding module: {e}")
            return
    
    def removeModule(self, moduleItem):
        """Remove module from tree."""
        if not moduleItem:
            self.logger.warning("Cannot remove module: moduleItem is None")
            return
            
        parent = moduleItem.parent()
        if parent:
            parent.removeChild(moduleItem)
            parent.module.removeChild(moduleItem.module)
            parent.emitDataChanged()
        else:
            self.treeWidget.invisibleRootItem().removeChild(moduleItem)
        
        self.moduleRemoved.emit(moduleItem)
    
    def selectedModules(self):
        """Get list of currently selected ModuleItems."""
        return self.treeWidget.selectedItems()

    def currentModule(self):
        """Get currently selected module."""
        return self.treeWidget.currentItem()
    
    def selectModule(self, moduleItem):
        """Select specific module in tree."""
        if moduleItem:
            self.treeWidget.clearSelection()
            moduleItem.setSelected(True)
            self.treeWidget.setCurrentItem(moduleItem)
    
    def findModule(self, nameOrPath):
        """Find module by name or path in tree."""
        iterator = QTreeWidgetItemIterator(self.treeWidget)
        while iterator.value():
            item = iterator.value()
            if isinstance(item, ModuleItem):
                if (item.module.name() == nameOrPath or 
                    item.module.path() == nameOrPath):
                    return item
            iterator += 1
    
    def createEmptyModule(self, name="module", parent=None):
        """Create new empty module and add to tree."""
        module = Module()
        module.setName(name)
        return self.addModule(module, parent)
    
    def loadModuleFromFile(self, filePath):
        """Load module from XML file and add to tree."""
        return self.addModule(filePath)

    def closeEvent(self, event):
        # Stop MCP server if running
        #if self.mcpServer:
        #    self.mcpServer.stopServer()
        
        # Terminate all file tracking threads before closing
        for thread in trackFileChangesThreads.values():
            if thread.isRunning():
                thread.terminate()
                thread.wait(1000)  # Wait up to 1 second for thread to finish
        trackFileChangesThreads.clear()
        
        # Call parent close event
        super().closeEvent(event)

def RigBuilderTool(spec, child=None, *, size=None): # spec can be full path, relative path, uid
    module = Module.loadModule(spec)
    if not module:
        print(f"Cannot load '{spec}' module")
        return

    if child is not None:
        if type(child) == str:
            module = module.findChild(child)

        elif type(child) == int:
            module = module.children()[child]

        if not module:
            print(f"Cannot find '{child}' child")
            return

    w = RigBuilderWindow()
    w.setWindowTitle("Rig Builder Tool - {}".format(module.relativePath()))
    w.treeWidget.addTopLevelItem(w.treeWidget.makeItemFromModule(module))
    w.treeWidget.setCurrentItem(w.treeWidget.topLevelItem(0))

    w.codeEditorWidget.hide()
    w.treeWidget.hide()

    centerWindow(w)

    if size:
        if type(size) in [int, float]:
            size = [size, size]
        w.resize(size[0], size[1])
    else: # auto size
        w.adjustSize()

    return w

def setupVscode(): # path to .vscode folder
    settings = {
        "python.autoComplete.extraPaths": [],
        "python.analysis.extraPaths": [],
        "github.copilot.editor.enableAutoCompletions": True,
        "github.copilot.advanced": {}
    }

    folder = RigBuilderLocalPath+"/vscode/.vscode"
    os.makedirs(folder, exist_ok=True)
    settingsFile = folder+"/settings.json"

    if os.path.exists(settingsFile):        
        with open(settingsFile, "r") as f:
            settings.update(json.load(f))

    # add paths
    for path in sys.path:
        path = path.replace("\\", "/")
        for section in ["python.autoComplete.extraPaths", "python.analysis.extraPaths"]:
            if path not in settings[section]:
                settings[section].append(path)

    with open(settingsFile, "w") as f:
        json.dump(settings, f, indent=4)

def cleanupVscode():
    vscodeFolder = RigBuilderLocalPath+"/vscode"
    if not os.path.exists(vscodeFolder):
        return
    
    for f in os.listdir(vscodeFolder):
        if f.endswith(".py"): # remove python files
            os.remove(os.path.join(vscodeFolder, f))

ModulesAPI.update(widgets.WidgetsAPI) # Update API
cleanupVscode()

mainWindow = RigBuilderWindow() # Initialize main window
