import time
import json
import re
import os
import subprocess
import sys
from xml.sax.saxutils import escape

from PySide2.QtGui import *
from PySide2.QtCore import *
from PySide2.QtWidgets import *

from .classes import *
from .editor import *
from . import widgets
from .utils import *

DCC = os.getenv("RIG_BUILDER_DCC") or "maya"
ParentWindow = None

if DCC == "maya":
    import maya.cmds as cmds
    import maya.OpenMayaUI as omui
    import maya.OpenMaya as om
    from shiboken2 import wrapInstance
    ParentWindow = wrapInstance(int(omui.MQtUtil.mainWindow()), QMainWindow)

updateFilesThread = None

def sendToServer(module):
    '''
    Send module to server with SVN, Git, Perforce or other VCS.
    '''
    module.sendToServer() # copy file to server and add to VCS
    return True

def updateFilesFromServer():
    '''
    Update files from server with SVN, Git, Perforce or other VCS.
    '''
    def update():
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

class EditJsonDialog(QDialog):
    saved = Signal(dict)

    def __init__(self, data, *, title="Edit"):
        super().__init__(parent=QApplication.activeWindow())

        self.setWindowTitle(title)
        self.setGeometry(0, 0, 600, 400)

        layout = QVBoxLayout()
        self.setLayout(layout)

        self.jsonWidget = widgets.JsonWidget(data)

        okBtn = QPushButton("OK")
        okBtn.clicked.connect(self.saveAndClose)

        layout.addWidget(self.jsonWidget)
        layout.addWidget(okBtn)
        centerWindow(self)

    def saveAndClose(self):
        dataList = self.jsonWidget.toJsonList()
        if dataList:
            self.saved.emit(dataList[0]) # keep the first item only
            self.accept()

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
            envUI = self.mainWindow.getEnvUI()
            RuntimeModule.env = envUI # update environment for runtime modules

            localEnv = dict(envUI)
            localEnv.update(self.moduleItem.module.getEnv())
            localEnv.update(env or {})

            with captureOutput(self.mainWindow.logWidget):
                try:
                    exec(cmd, localEnv)
                except Exception as e:
                    print("Error: "+str(e))
                    self.mainWindow.showLog()
                else:
                    self.updateWidgets()
            return localEnv

        for a in attributes:
            templateWidget = widgets.TemplateWidgets[a.template](executor=executor)
            nameWidget = QLabel(a.name)

            self._attributeAndWidgets.append((a, nameWidget, templateWidget))
            idx = len(self._attributeAndWidgets) - 1 # index of widgets

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

        subMenu = QMenu(module.name)

        for a in module.getAttributes():
            if a.template == attr.template:
                subMenu.addAction(a.name, Callback(self.connectAttr, path+module.name+"/"+a.name, attrWidgetIndex))

        for ch in module.getChildren():
            self.connectionMenu(subMenu, ch, attrWidgetIndex, path+module.name+"/")

        if subMenu.actions():
            menu.addMenu(subMenu)

    def nameContextMenuEvent(self, event, attrWidgetIndex):
        attr, _, _ = self._attributeAndWidgets[attrWidgetIndex]

        menu = QMenu(self)

        if self.moduleItem and self.moduleItem.parent():
            makeConnectionMenu = QMenu("Make connection")
            for a in self.moduleItem.module.parent.getAttributes():
                if a.template == attr.template:
                    makeConnectionMenu.addAction(a.name, Callback(self.connectAttr, "/"+a.name, attrWidgetIndex))

            for ch in self.moduleItem.module.parent.getChildren():
                if ch is self.moduleItem.module:
                    continue

                self.connectionMenu(makeConnectionMenu, ch, attrWidgetIndex)

            menu.addMenu(makeConnectionMenu)

        if attr.connect:
            menu.addAction("Break connection", Callback(self.disconnectAttr, attrWidgetIndex))

        menu.addSeparator()

        menu.addAction("Edit data", Callback(self.editData, attrWidgetIndex))
        menu.addSeparator()
        menu.addAction("Edit expression", Callback(self.editExpression, attrWidgetIndex))

        if attr.expression:
            menu.addAction("Evaluate expression", Callback(self.updateWidget, attrWidgetIndex))
            menu.addAction("Clear expression", Callback(self.clearExpression, attrWidgetIndex))

        menu.addSeparator()
        menu.addAction("Expose", Callback(self.exposeAttr, attrWidgetIndex))
        menu.addSeparator()
        menu.addAction("Reset", Callback(self.resetAttr, attrWidgetIndex))

        menu.popup(event.globalPos())

    def _wrapper(f):
        def inner(self, attrWidgetIndex, *args, **kwargs):
            attr, _, _ = self._attributeAndWidgets[attrWidgetIndex]
            with captureOutput(self.mainWindow.logWidget):
                try:
                    return f(self, attrWidgetIndex, *args, **kwargs)
                
                except Exception as e:
                    print("Error: {}.{}: {}".format(self.moduleItem.module.name, attr.name, str(e)))
                    self.mainWindow.showLog()                    

        return inner
    
    @_wrapper
    def widgetOnChange(self, attrWidgetIndex):
        attr, _, widget = self._attributeAndWidgets[attrWidgetIndex]

        previousAttrsData = {id(otherAttr): copyJson(otherAttr.data) for otherAttr in self.moduleItem.module.getAttributes()}

        runtimeAttr = RuntimeAttribute(self.moduleItem.module, attr)
        widgetData = widget.getJsonData()
        runtimeAttr.data = copyJson(widgetData)
        runtimeAttr.push()

        modifiedAttrs = []        
        for otherAttr in self.moduleItem.module.getAttributes():
            RuntimeAttribute(self.moduleItem.module, otherAttr).pull()

            if otherAttr.data != previousAttrsData[id(otherAttr)]:
                otherAttr.modified = True
                modifiedAttrs.append(otherAttr)

        for idx, (otherAttr, _, _) in enumerate(self._attributeAndWidgets): # update attributes' widgets
            if otherAttr in modifiedAttrs:
                self.updateWidget(idx)
                self.updateWidgetStyle(idx)

        if attr.data != widgetData:
            widget.blockSignals(True)
            widget.setJsonData(attr.data)
            widget.blockSignals(False)
            self.updateWidgetStyle(attrWidgetIndex)       

    @_wrapper
    def updateWidget(self, attrWidgetIndex):
        attr, _, widget = self._attributeAndWidgets[attrWidgetIndex]

        runtimeAttr = RuntimeAttribute(self.moduleItem.module, attr)
        runtimeAttr.pull()

        widget.blockSignals(True)
        widget.setJsonData(runtimeAttr.data)
        widget.blockSignals(False)

    def updateWidgets(self):
        for i in range(len(self._attributeAndWidgets)):
            self.updateWidget(i)

    def updateWidgetStyle(self, attrWidgetIndex):
        attr, nameWidget, widget = self._attributeAndWidgets[attrWidgetIndex]

        style = ""
        tooltip = []
        if attr.connect:
            tooltip.append("Connect: "+attr.connect)
        if attr.expression:
            tooltip.append("Expression:\n" + attr.expression)

        if attr.connect and not attr.expression: # only connection
            style = "TemplateWidget { border: 4px solid #6e6e39; background-color: #6e6e39 }"
        
        elif attr.expression and not attr.connect: # only expression
            style = "TemplateWidget { border: 4px solid #632094; background-color: #632094 }"
        
        elif attr.expression and attr.connect: # both
            style = "TemplateWidget { border: 4px solid rgb(0,0,0,0); background: QLinearGradient( x1: 0, y1: 0, x2: 1, y2:0, stop: 0 #6e6e39, stop: 1 #632094);}"

        nameWidget.setText(attr.name+("*" if attr.modified else ""))

        widget.setStyleSheet(style)
        widget.setToolTip("\n".join(tooltip))

    def updateWidgetStyles(self):
        for i in range(len(self._attributeAndWidgets)):
            self.updateWidgetStyle(i)

    def exposeAttr(self, attrWidgetIndex):
        attr, _, _ = self._attributeAndWidgets[attrWidgetIndex]

        if not self.moduleItem.module.parent:
            QMessageBox.warning(self, "Rig Builder", "Can't expose attribute to parent: no parent module")
            return

        if self.moduleItem.module.parent.findAttribute(attr.name):
            QMessageBox.warning(self, "Rig Builder", "Can't expose attribute to parent: attribute already exists")
            return

        doUsePrefix = QMessageBox.question(self, "Rig Builder", "Use prefix for the exposed attribute name?", QMessageBox.Yes and QMessageBox.No, QMessageBox.Yes) == QMessageBox.Yes
        prefix = self.moduleItem.module.name + "_" if doUsePrefix else ""
        expAttr = attr.copy()
        expAttr.name = prefix + expAttr.name
        self.moduleItem.module.parent.addAttribute(expAttr)
        self.connectAttr("/"+expAttr.name, attrWidgetIndex)

    def editData(self, attrWidgetIndex):
        def save(data):
            attr.data = data
            self.updateWidget(attrWidgetIndex)

        attr, _, _ = self._attributeAndWidgets[attrWidgetIndex]
        w = EditJsonDialog(attr.data, title="Edit data")
        w.saved.connect(save)
        w.show()

    def editExpression(self, attrWidgetIndex):
        def save(text):
            attr.expression = text
            self.updateWidgets()
            self.updateWidgetStyle(attrWidgetIndex)

        attr, _, _ = self._attributeAndWidgets[attrWidgetIndex]

        words = set(self.mainWindow.getEnvUI().keys()) | set(self.moduleItem.module.getEnv().keys())
        placeholder = '# Example: value = ch("../someAttr") + 1 or data["items"] = [1,2,3]'
        w = widgets.EditTextDialog(attr.expression, title="Edit expression for '{}'".format(attr.name), placeholder=placeholder, words=words, python=True)
        w.saved.connect(save)
        w.show()

    def clearExpression(self, attrWidgetIndex):
        attr, _, _ = self._attributeAndWidgets[attrWidgetIndex]
        attr.expression = ""
        self.updateWidgetStyle(attrWidgetIndex)

    def resetAttr(self, attrWidgetIndex):
        attr, _, _ = self._attributeAndWidgets[attrWidgetIndex]

        tmp = widgets.TemplateWidgets[attr.template]()
        attr.data = tmp.getDefaultData()
        attr.connect = ""
        self.updateWidget(attrWidgetIndex)
        self.updateWidgetStyle(attrWidgetIndex)

    def disconnectAttr(self, attrWidgetIndex):
        attr, _, _ = self._attributeAndWidgets[attrWidgetIndex]
        attr.connect = ""
        self.updateWidgetStyle(attrWidgetIndex)

    def connectAttr(self, connect, attrWidgetIndex):
        attr, _, _ = self._attributeAndWidgets[attrWidgetIndex]
        attr.connect = connect
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
        dialog.exec_()

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
            if attr.hasDefault():
                v = replaceStringInData(attr.getDefaultValue(), old, new)
                attr.setDefaultValue(v)

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
        for a in self.moduleItem.module.getAttributes():
            if a.category not in self.tabsAttributes:
                self.tabsAttributes[a.category] = []
                tabTitlesInOrder.append(a.category)

            self.tabsAttributes[a.category].append(a)

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
                return self.module.name

            elif role == Qt.DisplayRole:
                return self.module.name + ("*" if self.module.modified else " ")

            elif role == Qt.ForegroundRole:
                isParentMuted = False
                isParentReferenced = False

                parent = self.parent()
                while parent:
                    isParentMuted = isParentMuted or parent.module.muted
                    isParentReferenced = isParentReferenced or parent.module.uid
                    parent = parent.parent()

                color = QColor(200, 200, 200)

                if isParentReferenced:
                    color = QColor(140, 140, 180)

                if self.module.muted or isParentMuted:
                    color = QColor(100, 100, 100)

                return color

            elif role == Qt.BackgroundRole:
                if not re.match("\\w*", self.module.name):
                    return QColor(170, 50, 50)

                itemParent = self.parent()
                if itemParent and len([ch for ch in itemParent.module.getChildren() if ch.name == self.module.name]) > 1:
                    return QColor(170, 50, 50)

                return super().data(column, role)

        elif column == 1: # path
            if role == Qt.DisplayRole:
                return self.module.getRelativeLoadedPathString().replace("\\", "/") + " "

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
            if self.module.isLoadedFromLocal():
                source = "local"
            elif self.module.isLoadedFromServer():
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
                return self.module.uid[:8]
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
                    existingNames = set([ch.name for ch in self.parent().module.getChildren()])
                    newName = findUniqueName(newName, existingNames)

                connections = self._saveConnections(self.module) # rename in connections
                self.module.name = newName
                self.treeWidget().resizeColumnToContents(column)
                self._updateConnections(connections)
        else:
            return super().setData(column, role, value)

    def clearModifiedFlag(self, *, attrFlag=True, moduleFlag=True, children=True): # clear modified flag on embeded modules
        if moduleFlag:
            self.module.modified = False
            self.emitDataChanged()

        if attrFlag:
            for a in self.module.getAttributes():
                a.modified = False

        if children:
            for i in range(self.childCount()):
                ch = self.child(i)
                if not ch.module.uid: # embeded module
                    ch.clearModifiedFlag(attrFlag=True, moduleFlag=True, children=True)
                else: # only direct children
                    ch.clearModifiedFlag(attrFlag=True, moduleFlag=False, children=False)

    def _saveConnections(self, currentModule):
        connections = []
        for a in currentModule.getAttributes():
            connections.append({"attr":a, "module": currentModule, "connections":currentModule.listConnections(a)})

        for ch in currentModule.getChildren():
            connections += self._saveConnections(ch)
        return connections

    def _updateConnections(self, connections):
        for data in connections:
            srcAttr = data["attr"]
            module = data["module"]
            for m, a in data["connections"]:
                a.connect = module.getPath().replace(m.getPath(inclusive=False), "") + "/" + srcAttr.name # update connection path

class TreeWidget(QTreeWidget):
    def __init__(self, *, mainWindow=None, **kwargs):
        super().__init__(**kwargs)

        self.mainWindow = mainWindow
        self.dragItems = [] # using in drag & drop

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

        painter = QPainter(viewport)
        painter.setPen(QColor(90,90,90))
        painter.drawText(viewport.width() - fontMetrics.width(label)-10, viewport.height()-10, label)

    def dragEnterEvent(self, event):
        super().dragEnterEvent(event)

        if event.mimeData().hasUrls():
            event.accept()

        if event.mouseButtons() == Qt.MiddleButton:
            self.dragItems = self.selectedItems()
        else:
            event.ignore()

    def dragMoveEvent(self, event):
        super().dragMoveEvent(event)

        if event.mimeData().hasUrls():
            event.setDropAction(Qt.CopyAction)

    def dropEvent(self, event):
        for item in self.dragItems:
            if item.parent():
                item.parent().module.modified = True
                item.parent().emitDataChanged()
            
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
                        print(e)
                        print("Error '{}': invalid module".format(path))
                        self.mainWindow.showLog()
        else:
            for item in self.dragItems:
                if item.module.parent: # remove from old parent
                    item.module.parent.removeChild(item.module)

                newParent = item.parent()
                if newParent:
                    idx = newParent.indexOfChild(item)
                    newParent.module.insertChild(idx, item.module)
                    
                    newParent.module.modified = True
                    newParent.emitDataChanged()

            self.dragItems = []

    def makeItemFromModule(self, module):
        item = ModuleItem(module)

        for ch in module.getChildren():
            item.addChild(self.makeItemFromModule(ch))

        return item

    def contextMenuEvent(self, event):
        menu = QMenu(self)
        for m in self.mainWindow.menu.findChildren(QMenu):
            if m.title():
                for a in m.actions():
                    menu.addAction(a)
                menu.addSeparator()
        menu.popup(event.globalPos())

    def sendModuleToServer(self):
        selectedItems = self.selectedItems()
        if not selectedItems:
            return

        msg = "\n".join([item.module.name for item in selectedItems])

        if QMessageBox.question(self, "Rig Builder", "Send modules to server?\n"+msg, QMessageBox.Yes and QMessageBox.No, QMessageBox.Yes) != QMessageBox.Yes:
            return

        for item in selectedItems:
            if item.module.isLoadedFromLocal():
                if sendToServer(item.module):
                    QMessageBox.information(self, "Rig Builder", "Module '{}' has successfully been sent to server".format(item.module.name))

            else:
                QMessageBox.warning(self, "Rig Builder", "Can't send '{}' to server.\nIt works for local modules only!".format(item.module.name))

    def insertModule(self):
        item = self.makeItemFromModule(Module("module"))

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
            print("Error '{}': invalid module".format(filePath))
            self.mainWindow.showLog()

    def saveModule(self):
        selectedItems = self.selectedItems()
        if not selectedItems:
            return

        msg = "\n".join(["{} -> {}".format(item.module.name, item.module.getSavePath() or "N/A") for item in selectedItems])

        if QMessageBox.question(self, "Rig Builder", "Save modules?\n"+msg, QMessageBox.Yes and QMessageBox.No, QMessageBox.Yes) != QMessageBox.Yes:
            return

        for item in selectedItems:
            outputPath = item.module.getSavePath()

            if not outputPath:
                outputPath, _ = QFileDialog.getSaveFileName(mainWindow, "Save "+item.module.name, RigBuilderLocalPath+"/modules/"+item.module.name, "*.xml")

            if outputPath:
                dirname = os.path.dirname(outputPath)
                if not os.path.exists(dirname):
                    os.makedirs(dirname)

                item.module.saveToFile(outputPath)
                item.emitDataChanged() # path changed
                item.clearModifiedFlag()
                self.mainWindow.attributesTabWidget.updateWidgetStyles()

    def saveAsModule(self):
        for item in self.selectedItems():
            outputDir = os.path.dirname(item.module.loadedFrom) or RigBuilderLocalPath+"/modules"
            outputPath, _ = QFileDialog.getSaveFileName(mainWindow, "Save as "+item.module.name, outputDir + "/" +item.module.name, "*.xml")

            if outputPath:
                item.module.uid = generateUid()
                item.module.saveToFile(outputPath)
                item.emitDataChanged() # path and uid changed
                item.clearModifiedFlag()
                self.mainWindow.attributesTabWidget.updateWidgetStyles()

    def embedModule(self):
        selectedItems = self.selectedItems()
        if not selectedItems:
            return

        msg = "\n".join([item.module.name for item in selectedItems])

        if QMessageBox.question(self, "Rig Builder", "Embed modules?\n"+msg, QMessageBox.Yes and QMessageBox.No, QMessageBox.Yes) != QMessageBox.Yes:
            return

        for item in selectedItems:
            item.module.uid = ""
            item.module.loadedFrom = ""
            item.emitDataChanged() # path and uid changed

    def updateModule(self):
        selectedItems = self.selectedItems()
        if not selectedItems:
            return

        Module.updateUidsCache()

        msg = "\n".join([item.module.name for item in selectedItems])
        if QMessageBox.question(self, "Rig Builder", "Update modules?\n"+msg, QMessageBox.Yes and QMessageBox.No, QMessageBox.Yes) != QMessageBox.Yes:
            return

        for item in selectedItems:
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

    def muteModule(self):
        for item in self.selectedItems():
            item.module.muted = not item.module.muted
            item.emitDataChanged()

    def duplicateModule(self):
        newItems = []
        for item in self.selectedItems():
            newItem = self.makeItemFromModule(item.module.copy())
            if item.parent():
                existingNames = set([ch.name for ch in item.parent().module.getChildren()])
                newItem.module.name = findUniqueName(item.module.name, existingNames)

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

    def removeModule(self):
        selectedItems = self.selectedItems()
        if not selectedItems:
            return

        msg = "\n".join([item.module.name for item in selectedItems])

        if QMessageBox.question(self, "Rig Builder", "Remove modules?\n"+msg, QMessageBox.Yes and QMessageBox.No, QMessageBox.Yes) != QMessageBox.Yes:
            return

        for item in selectedItems:
            parent = item.parent()
            if parent:
                parent.removeChild(item)
                parent.module.removeChild(item.module)

                parent.module.modified = True
                parent.emitDataChanged()
            else:
                self.invisibleRootItem().removeChild(item)

    def addModuleFromBrowser(self, modulePath):
        m = Module.loadFromFile(modulePath)
        m.update()
        self.addTopLevelItem(self.makeItemFromModule(m))

        # add to recent modules
        if m not in self.mainWindow.infoWidget.recentModules:
            self.mainWindow.infoWidget.recentModules.insert(0, m)
            if len(self.mainWindow.infoWidget.recentModules) > 10:
                self.mainWindow.infoWidget.recentModules.pop()

        return m

    def browseModuleSelector(self, *, mask=None, updateSource=None, modulesFrom=None):
        if mask:
            self.moduleListDialog.maskWidget.setText(mask)

        if updateSource:
            self.moduleListDialog.updateSourceWidget.setCurrentIndex({"all":0, "server": 1, "local": 2, "": 3}[updateSource])

        if modulesFrom:
            self.moduleListDialog.modulesFromWidget.setCurrentIndex({"server": 0, "local": 1}[modulesFrom])

        self.moduleListDialog.exec_()

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
            w.attrCallback = self.attrCallback
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
            w.attrCallback = self.attrCallback
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

        for a in self.moduleItem.module.getAttributes():
            if a.category == self.category:
                w = self.insertCustomWidget(a.template)
                w.nameWidget.setText(a.name)
                w.templateWidget.setJsonData(a.data)
                w.attrConnect = a.connect
                w.attrExpression = a.expression
                w.attrModified = a.modified

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
        selector.exec_()

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
        maxWidth = max([fontMetrics.width(self.attributesLayout.itemAt(k).widget().nameWidget.text()) for k in range(self.attributesLayout.count())])
        for k in range(self.attributesLayout.count()):
            w = self.attributesLayout.itemAt(k).widget()
            w.nameWidget.setFixedWidth(maxWidth)

class EditAttributesTabWidget(QTabWidget):
    def __init__(self, moduleItem, currentIndex=0, **kwargs):
        super().__init__(**kwargs)

        self.moduleItem = moduleItem
        self.tempRunCode = moduleItem.module.runCode

        self.setTabBar(QTabBar())
        self.setMovable(True)
        self.setTabsClosable(True)
        self.tabBar().mouseDoubleClickEvent = self.tabBarMouseDoubleClickEvent
        self.tabCloseRequested.connect(self.tabCloseRequest)

        tabTitlesInOrder = []
        for a in self.moduleItem.module.getAttributes():
            if a.category not in tabTitlesInOrder:
                tabTitlesInOrder.append(a.category)

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
            for m, a in self.moduleItem.module.listConnections(self.moduleItem.module.findAttribute(oldName)):
                a.connect = self.moduleItem.module.getPath().replace(m.getPath(inclusive=False), "") + "/" + newName # update connection path

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

        self.setWindowTitle("Edit Attributes - " + self.moduleItem.module.name)
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
        self.moduleItem.module.clearAttributes()

        for i in range(self.tabWidget.count()):
            attrsLayout = self.tabWidget.widget(i).widget().attributesLayout # tab/scrollArea/EditAttributesWidget

            for k in range(attrsLayout.count()):
                w = attrsLayout.itemAt(k).widget()

                a = Attribute(w.nameWidget.text())
                a.data = w.templateWidget.getJsonData()
                a.template = w.template
                a.category = self.tabWidget.tabText(i)
                a.connect = w.attrConnect
                a.expression = w.attrExpression
                a.modified = w.attrModified
                self.moduleItem.module.addAttribute(a)

        self.moduleItem.module.runCode = self.tabWidget.tempRunCode
        self.moduleItem.module.modified = True
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

        self.moduleItem.module.runCode = self.editorWidget.toPlainText()
        self.moduleItem.module.modified = True
        self.moduleItem.emitDataChanged()

    def updateState(self):
        if not self.moduleItem:
            return

        self.editorWidget.ignoreStates = True
        self._skipSaving = True
        self.editorWidget.setText(self.moduleItem.module.runCode)
        self._skipSaving = False
        self.editorWidget.ignoreStates = False

        self.editorWidget.document().clearUndoRedoStacks()
        self.generateCompletionWords()

        self.editorWidget.preset = id(self.moduleItem)
        self.editorWidget.loadState()

    def generateCompletionWords(self):
        if not self.moduleItem:
            return

        words = set(self.mainWindow.getEnvUI().keys()) | set(self.moduleItem.module.getEnv().keys())

        for a in self.moduleItem.module.getAttributes():
            words.add("@" + a.name)
            words.add("@" + a.name + "_data")
            words.add("@set_" + a.name)

        self.editorWidget.words = words

class LogHighligher(QSyntaxHighlighter):
    def __init__(self, parent):
        super().__init__(parent)

        self.highlightingRules = []

        warningFormat = QTextCharFormat()
        warningFormat.setForeground(QColor(250, 150, 90))
        warningRegexp = QRegExp("\\b\\w*warning\\b")
        warningRegexp.setCaseSensitivity(Qt.CaseInsensitive)
        self.highlightingRules.append((warningRegexp, warningFormat))

        errorFormat = QTextCharFormat()
        errorFormat.setForeground(QColor(250, 90, 90))
        errorRegexp = QRegExp("\\b\\w*error\\b")
        errorRegexp.setCaseSensitivity(Qt.CaseInsensitive)
        self.highlightingRules.append((errorRegexp, errorFormat))

    def highlightBlock(self, text):
        for pattern, format in self.highlightingRules:
            if not pattern:
                continue

            expression = QRegExp(pattern)
            index = expression.indexIn(text)
            while index >= 0:
                length = expression.matchedLength()
                self.setFormat(index, length, format)
                index = expression.indexIn(text, index + length)

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
        painter = QPainter(self)
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
    def __init__(self):
        super().__init__(parent=ParentWindow)

        self.setWindowTitle("Rig Builder")
        self.setGeometry(0, 0, 1300, 700)

        self.setWindowFlags(self.windowFlags() | Qt.Window)

        layout = QVBoxLayout()
        self.setLayout(layout)

        self.logWidget = LogWidget()
        self.logWidget.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Ignored)

        self.attributesTabWidget = AttributesTabWidget(None, mainWindow=self)
        self.attributesTabWidget.hide()

        self.treeWidget = TreeWidget(mainWindow=self)
        self.treeWidget.itemSelectionChanged.connect(self.treeItemSelectionChanged)

        self.codeEditorWidget = CodeEditorWidget(mainWindow=self)
        self.codeEditorWidget.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Ignored)
        self.codeEditorWidget.editorWidget.setPlaceholderText("Your module code...")

        self.runBtn = QPushButton("Run!")
        self.runBtn.setStyleSheet("background-color: #3e4f89")
        self.runBtn.clicked.connect(self.runModuleClicked)
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
        self.vsplitter.addWidget(self.codeEditorWidget)
        self.vsplitter.addWidget(self.logWidget)
        self.vsplitter.setSizes([500, 0, 0])

        self.vsplitter.splitterMoved.connect(self.codeSplitterMoved)
        self.codeEditorWidget.setEnabled(False)

        self.progressBarWidget = MyProgressBar()
        self.progressBarWidget.hide()

        self.menu = self.getMenu()
        self.treeWidget.addActions(getActions(self.menu))
        setActionsLocalShortcut(self.treeWidget)

        layout.addWidget(self.vsplitter)
        layout.addWidget(self.progressBarWidget)

        centerWindow(self)

    def getMenu(self):
        menu = QMenu(self)

        fileMenu = menu.addMenu("File")
        fileMenu.addAction("New", self.treeWidget.insertModule, "Insert")
        fileMenu.addAction("Import", self.treeWidget.importModule, "Ctrl+I")
        fileMenu.addSeparator()
        fileMenu.addAction("Save", self.treeWidget.saveModule, "Ctrl+S")
        fileMenu.addAction("Save as", self.treeWidget.saveAsModule)
        fileMenu.addSeparator()
        fileMenu.addAction("Locate file", self.locateModuleFile)
        fileMenu.addAction("Copy tool code", self.copyToolCode)

        editMenu = menu.addMenu("Edit")
        editMenu.addAction("Duplicate", self.treeWidget.duplicateModule, "Ctrl+D")
        editMenu.addSeparator()
        editMenu.addAction("Update", self.treeWidget.updateModule, "Ctrl+U")
        editMenu.addAction("Send to server", self.treeWidget.sendModuleToServer)
        editMenu.addAction("Embed", self.treeWidget.embedModule)
        editMenu.addSeparator()
        editMenu.addAction("Mute", self.treeWidget.muteModule, "M")
        editMenu.addAction("Remove", self.treeWidget.removeModule, "Delete")
        editMenu.addAction("Clear all", self.clearAllModules)

        helpMenu = menu.addMenu("Help")
        helpMenu.addAction("Documentation", self.showDocumenation)

        return menu

    def copyToolCode(self):
        selectedItems = self.treeWidget.selectedItems()
        if selectedItems:
            item = selectedItems[0]
            if item.module.isLoadedFromLocal() or item.module.isLoadedFromServer():
                code = '''import rigBuilder;rigBuilder.RigBuilderTool(r"{}").show()'''.format(item.module.getRelativePath())
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
            if item and os.path.exists(item.module.loadedFrom):
                subprocess.call("explorer /select,\"{}\"".format(os.path.normpath(item.module.loadedFrom)))

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
            prefix = "local" if m.isLoadedFromLocal() else "server"
            relPath = m.getRelativePath().replace(".xml","").replace("\\", "/")
            template.append("<p><a style='color: #55aaee' href='{0}:{1}'>{1}</a> {0}</p>".format(prefix, relPath))

        # recent updates
        template.append("<center><h2 style='background-color: #666666'>Recent updates</h2></center>")

        # local modules
        def displayFiles(files, *, local):
            prefix = "local" if local else "server"
            for k, v in files.items():
                if k == "Others":
                    continue

                if v:
                    template.append("<h3 style='background-color: #393939'>{}</h3>".format(escape(k)))
                    root = RigBuilderLocalPath+"/modules" if local else RigBuilderPath+"/modules"
                    for file in v:
                        relPath = calculateRelativePath(file, root).replace(".xml", "").replace("\\", "/")
                        template.append("<p><a style='color: #55aaee' href='{0}:{1}'>{1}</a></p>".format(prefix, escape(relPath)))

        files, count = categorizeFilesByModTime(Module.LocalUids.values())
        if count > 0:
            template.append("<h2 style='background-color: #444444'>Local modules</h2>")
            displayFiles(files, local=True)

        files, count = categorizeFilesByModTime(Module.ServerUids.values())
        if count > 0:
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

    def getEnvUI(self):
        return {"beginProgress": self.progressBarWidget.beginProgress,
                "stepProgress": self.progressBarWidget.stepProgress,
                "endProgress": self.progressBarWidget.endProgress,
                "currentTabIndex": self.attributesTabWidget.currentIndex()}    

    def runModuleClicked(self):
        if DCC == "maya":
            cmds.undoInfo(ock=True) # run in undo chunk
            self.runModule()
            cmds.undoInfo(cck=True)
        else:
            self.runModule()

    def runModule(self):
        def uiCallback(mod):
            self.progressBarWidget.stepProgress(self.progressCounter, mod.getPath())
            self.progressCounter += 1

        def getChildrenCount(item):
            count = 0
            for i in range(item.childCount()):
                count += 1
                count += getChildrenCount(item.child(i))
            return count

        selectedItems = self.treeWidget.selectedItems()

        if not selectedItems:
            return

        currentItem = selectedItems[0]

        self.setFocus()

        self.logWidget.clear()
        self.showLog()

        with captureOutput(self.logWidget):
            startTime = time.time()
            timeStr = time.strftime("%H:%M", time.localtime(startTime))
            print("Start running at " + timeStr)

            self.progressBarWidget.initialize()
            self.progressCounter = 0

            count = getChildrenCount(currentItem)
            self.progressBarWidget.beginProgress(currentItem.module.name, count+1)

            muted = currentItem.module.muted
            currentItem.module.muted = False

            RuntimeModule.env = self.getEnvUI() # for runtime module

            try:
                currentItem.module.run(env=self.getEnvUI(), uiCallback=uiCallback)
            except Exception:
                printErrorStack()
            finally:
                currentItem.module.muted = muted
                print("Done in %.2fs"%(time.time() - startTime))

        self.progressBarWidget.endProgress()
        self.attributesTabWidget.updateTabs()

def RigBuilderTool(spec, child=None, *, size=None): # spec can be full path, relative path, uid
    module = Module.loadModule(spec)
    if not module:
        print("Cannot load '{}' module".format(spec))
        return

    if child is not None:
        if type(child) == str:
            module = module.findChild(child)

        elif type(child) == int:
            module = module.getChildren()[child]

        if not module:
            print("Cannot find '{}' child".format(child))
            return

    w = RigBuilderWindow()
    w.setWindowTitle("Rig Builder Tool - {}".format(module.getPath()))
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

ModulesAPI.update(widgets.WidgetsAPI)

if not os.path.exists(RigBuilderLocalPath):
    os.makedirs(RigBuilderLocalPath+"/modules")

mainWindow = RigBuilderWindow()
