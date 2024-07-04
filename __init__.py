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

def sendToServer(module):
    module.sendToServer()

def widgetOnChange(widget, module, attr):
    data = widget.getJsonData()
    attr.data = data

    if attr.connect:
        srcAttr = module.findConnectionSourceForAttribute(attr)
        if srcAttr:
            srcAttr.updateFromAttribute(attr)

class TabAttributesWidget(QWidget):
    needUpdateUI = Signal()

    def __init__(self, module, attributes, *, mainWindow=None, **kwargs):
        super(TabAttributesWidget, self).__init__(**kwargs)

        self.mainWindow = mainWindow
        self.module = module

        layout = QGridLayout()
        layout.setDefaultPositioning(2, Qt.Horizontal)
        layout.setColumnStretch(1, 1)
        self.setLayout(layout)

        if self.module:
            with captureOutput(self.mainWindow.logWidget):
                try:
                    for attr in self.module.getAttributes():
                        self.module.resolveConnection(attr)
                except Exception as err:
                    print("Error: " + str(err))
                    self.mainWindow.showLog()
                    self.mainWindow.logWidget.ensureCursorVisible()

        globEnv = self.mainWindow.getModuleGlobalEnv()
        globEnv.update({"module": ModuleWrapper(self.module), "ch": self.module.ch, "chset": self.module.chset})

        for a in attributes:
            templateWidget = widgets.TemplateWidgets[a.template](env=globEnv)
            with captureOutput(self.mainWindow.logWidget):
                try:
                    templateWidget.setJsonData(a.data)
                except:
                    print("Error: invalid json data for attribute '%s'"%a.name)
                    a.data = templateWidget.getDefaultData()
                    self.mainWindow.showLog()
                    self.mainWindow.logWidget.ensureCursorVisible()                    

            templateWidget.somethingChanged.connect(lambda w=templateWidget, e=module, a=a: widgetOnChange(w, e, a))
            templateWidget.needUpdateUI.connect(self.needUpdateUI.emit)
            self.setWidgetStyle(templateWidget, a)

            nameWidget = QLabel(a.name)
            nameWidget.setAlignment(Qt.AlignRight)
            nameWidget.setStyleSheet("QLabel:hover:!pressed{ background-color: #666666; }")

            nameWidget.contextMenuEvent = lambda event, a=a, w=templateWidget: self.nameContextMenuEvent(event, a, w)
            nameWidget.attribute = a

            layout.addWidget(nameWidget)
            layout.addWidget(templateWidget)

        layout.addWidget(QLabel())
        layout.setRowStretch(layout.rowCount(), 1)

    def connectionMenu(self, menu, module, attr, widget, path="/"):
        subMenu = QMenu(module.name)

        for a in module.getAttributes():
            if a.template == attr.template:
                subMenu.addAction(a.name, Callback(self.connectAttr, path+module.name+"/"+a.name, attr, widget))

        for ch in module.getChildren():
            self.connectionMenu(subMenu, ch, attr, widget, path+module.name+"/")

        if subMenu.actions():
            menu.addMenu(subMenu)

    def nameContextMenuEvent(self, event, attr, widget):
        menu = QMenu(self)

        if self.module and self.module.parent:
            makeConnectionMenu = QMenu("Make connection")
            for a in self.module.parent.getAttributes():
                if a.template == attr.template:
                    makeConnectionMenu.addAction(a.name, Callback(self.connectAttr, "/"+a.name, attr, widget))

            for ch in self.module.parent.getChildren():
                if ch is self.module:
                    continue

                self.connectionMenu(makeConnectionMenu, ch, attr, widget)

            menu.addMenu(makeConnectionMenu)

        if attr.connect:
            menu.addAction("Break connection", Callback(self.disconnectAttr, attr, widget))

        menu.addAction("Set data", Callback(self.setData, attr, widget))
        menu.addAction("Reset", Callback(self.resetAttr, attr, widget))
        menu.addSeparator()
        menu.addAction("Expose", Callback(self.exposeAttr, attr, widget))

        menu.popup(event.globalPos())

    def setWidgetStyle(self, widget, attr):
        tooltip = ""
        background = ""
        if attr.connect:
            tooltip = "Connect: "+attr.connect
            background = "#6e6e39"

        widget.setToolTip(tooltip)
        widget.setStyleSheet("background-color:"+background)

    def exposeAttr(self, attr, widget):
        if not self.module.parent:
            QMessageBox.warning(self, "Rig Builder", "Can't expose attribute to parent: no parent module")
            return

        if self.module.parent.findAttribute(attr.name):
            QMessageBox.warning(self, "Rig Builder", "Can't expose attribute to parent: attribute already exists")
            return

        doUsePrefix = QMessageBox.question(self, "Rig Builder", "Use prefix for the exposed attribute name?", QMessageBox.Yes and QMessageBox.No, QMessageBox.Yes) == QMessageBox.Yes
        prefix = self.module.name + "_" if doUsePrefix else ""
        expAttr = attr.copy()
        expAttr.name = prefix + expAttr.name
        self.module.parent.addAttribute(expAttr)
        self.connectAttr("/"+expAttr.name, attr, widget)

    def setData(self, attr, widget):
        text = json.dumps(attr.data, indent=4).replace("'", "\"")
        editText = widgets.EditTextDialog(text, title="Set data", parent=mainWindow)
        editText.exec_()
        if editText.result():
            with captureOutput(self.mainWindow.logWidget):
                try:
                    data = json.loads(editText.outputText)
                    tmp = widgets.TemplateWidgets[attr.template]() # also we need check for widget compatibility
                    tmp.setJsonData(data)

                except:
                    print("Error: invalid or incompatible json data")
                    self.mainWindow.showLog()
                    self.mainWindow.logWidget.ensureCursorVisible()

                else:
                    attr.data = data
                    widget.setJsonData(data)

    def resetAttr(self, attr, widget):
        tmp = widgets.TemplateWidgets[attr.template]()
        attr.data = tmp.getDefaultData()
        attr.connect = ""
        widget.setJsonData(attr.data)
        self.setWidgetStyle(widget, attr)

    def disconnectAttr(self, attr, widget):
        attr.connect = ""
        self.setWidgetStyle(widget, attr)

    def connectAttr(self, connect, destAttr, widget):
        destAttr.connect = connect
        self.module.resolveConnection(destAttr)
        widget.setJsonData(destAttr.data)
        self.setWidgetStyle(widget, destAttr)

class SearchReplaceDialog(QDialog):
    onReplace = Signal(str, str, dict) # old, new, options

    def __init__(self, options=[], **kwargs):
        super(SearchReplaceDialog, self).__init__(**kwargs)

        self.optionsWidgets = {}

        self.setWindowTitle("Search/Replace")
        layout = QVBoxLayout()
        self.setLayout(layout)

        self.searchWidget = QLineEdit("L_")
        self.replaceWidget = QLineEdit("R_")

        btn = QPushButton("Replace")
        btn.clicked.connect(self.replaceClicked)

        gridLayout = QGridLayout()
        gridLayout.addWidget(QLabel("Search"),0,0)
        gridLayout.addWidget(self.searchWidget,0,1)
        gridLayout.addWidget(QLabel("Replace"),1,0)
        gridLayout.addWidget(self.replaceWidget,1,1)
        layout.addLayout(gridLayout)

        for opt in options:
            w = QCheckBox(opt)
            self.optionsWidgets[opt] = w
            layout.addWidget(w)

        layout.addWidget(btn)

    def replaceClicked(self):
        opts = {l:w.isChecked() for l,w in self.optionsWidgets.items()}
        self.onReplace.emit(self.searchWidget.text(), self.replaceWidget.text(), opts)
        self.accept()

class AttributesTabWidget(QTabWidget):
    def __init__(self, module=None, *, mainWindow=None, **kwargs):
        super(AttributesTabWidget, self).__init__(**kwargs)

        self.mainWindow = mainWindow
        self.module = module
        self.tabsAttributes = {}

        self.searchAndReplaceDialog = SearchReplaceDialog(["In all tabs"])
        self.searchAndReplaceDialog.onReplace.connect(self.onReplace)

        self.currentChanged.connect(self.tabChanged)
        self.updateTabs()

    def contextMenuEvent(self, event):
        menu = QMenu(self)

        if self.module:
            menu.addAction("Edit attributes", self.editAttributes)
            menu.addSeparator()
            menu.addAction("Replace in values", self.searchAndReplaceDialog.exec_)

        menu.popup(event.globalPos())

    def editAttributes(self):
        dialog = EditAttributesDialog(self.module, self.currentIndex(), parent=mainWindow)
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
        w = TabAttributesWidget(self.module, self.tabsAttributes[title], mainWindow=self.mainWindow)
        w.needUpdateUI.connect(self.updateTabs)
        scrollArea.setWidget(w)
        self.setCurrentIndex(idx)

    def updateTabs(self):
        oldIndex = self.currentIndex()
        oldCount = self.count()

        self.tabsAttributes.clear()

        if not self.module:
            return

        self.blockSignals(True)

        tabTitlesInOrder = []
        for a in self.module.getAttributes():
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

class ModuleListDialog(QDialog):
    def __init__(self, **kwargs):
        super(ModuleListDialog, self).__init__(**kwargs)

        self.setWindowTitle("Module Selector")

        self.selectedFileName = ""

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

        layout.addLayout(gridLayout)
        layout.addWidget(self.treeWidget)

        self.maskWidget.setFocus()

    def showEvent(self, event):
        pos = self.mapToParent(self.mapFromGlobal(QCursor.pos()))
        self.setGeometry(pos.x(), pos.y(), 600, 400)

        self.selectedFileName = ""
        Module.updateUidsCache()
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
            self.selectedFileName = item.filePath
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

class TreeWidget(QTreeWidget):
    def __init__(self, *, mainWindow=None, **kwargs):
        super(TreeWidget, self).__init__(**kwargs)

        self.mainWindow = mainWindow
        self.dragItems = [] # using in drag & drop

        self.moduleListDialog = ModuleListDialog()

        self.setHeaderLabels(["Name", "Path", "Source", "UID"])
        self.setSelectionMode(QAbstractItemView.ExtendedSelection) # ExtendedSelection

        self.header().setSectionResizeMode(QHeaderView.ResizeToContents)

        self.setDragEnabled(True)
        self.setDragDropMode(QAbstractItemView.InternalMove)
        self.setDropIndicatorShown(True)
        self.setAcceptDrops(True)

        self.setIndentation(30)

        self.setMouseTracking(True)
        self.itemDoubleClicked.connect(self.treeItemDoubleClicked)

    def drawRow(self, painter, options, modelIdx):
        painter.save()

        rect = self.visualRect(modelIdx)
        item = self.itemFromIndex(modelIdx)

        indent = self.indentation()

        if rect.width() < 0:
            return

        isParentMuted = False
        isParentReferenced = False

        parent = item.parent()
        while parent:
            isParentMuted = isParentMuted or parent.module.muted
            isParentReferenced = isParentReferenced or parent.module.uid
            parent = parent.parent()

        painter.setPen(QPen(QColor(60, 60, 60), 1, Qt.SolidLine))
        numberBranch = int(rect.x() / indent)
        if numberBranch > 1:
            for i in range(1, numberBranch):
                plusInt = i * indent + 10
                x = rect.x() - plusInt
                painter.drawLine(x, rect.y(), x, rect.y() + rect.height())

        if item.childCount() and rect.x() + rect.width() > rect.x():
            painter.setPen(QPen(QColor(100, 100, 100), 1, Qt.SolidLine))
            painter.fillRect(QRect(rect.x() - 16, rect.y() + 2, 12, 12), QColor(45, 45, 45))
            painter.drawRect(rect.x() - 16, rect.y() + 2, 12, 12)
            painter.setPen(QPen(QColor(120, 120, 120), 1, Qt.SolidLine))
            if item.isExpanded():
                painter.drawLine(rect.x() - 7, rect.y() + 8, rect.x() - 13, rect.y() + 8)
            else:
                painter.drawLine(rect.x() - 10, rect.y() + 5, rect.x() - 10, rect.y() + 12)
                painter.drawLine(rect.x() - 7, rect.y() + 8, rect.x() - 13, rect.y() + 8)

        nameRect = self.visualRect(modelIdx.sibling(modelIdx.row(), 0))
        pathRect = self.visualRect(modelIdx.sibling(modelIdx.row(), 1))
        sourceRect = self.visualRect(modelIdx.sibling(modelIdx.row(), 2))
        uidRect = self.visualRect(modelIdx.sibling(modelIdx.row(), 3))

        if not re.match("\\w*", item.module.name):
            painter.fillRect(nameRect, QBrush(QColor(170, 50, 50)))

        itemParent = item.parent()
        if itemParent and len([ch for ch in itemParent.module.getChildren() if ch.name == item.module.name]) > 1:
            painter.fillRect(nameRect, QBrush(QColor(170, 50, 50)))

        # set selected style
        if modelIdx in self.selectedIndexes():
            width = nameRect.width() + pathRect.width() + sourceRect.width() + uidRect.width()
            painter.fillRect(rect.x()-1, rect.y(), width, rect.height(), QColor(80, 96, 154, 60))
            painter.setPen(QColor(73, 146, 158, 200))
            painter.drawRect(rect.x()-1, rect.y()+1, width, rect.height()-3)

        painter.setPen(QColor(200, 200, 200))

        if isParentReferenced:
            painter.setPen(QColor(140, 140, 180))

        if item.module.muted or isParentMuted:
            painter.setPen(QColor(90, 90, 90))

        modifiedSuffix = "*" if item.module.modified else ""
        painter.drawText(nameRect, Qt.AlignLeft | Qt.AlignVCenter, item.module.name+modifiedSuffix)

        painter.setPen(QColor(120, 120, 120))
        painter.drawText(pathRect, Qt.AlignLeft | Qt.AlignVCenter, item.text(1))

        if item.module.isLoadedFromLocal():
            painter.setPen(QColor(120, 220, 120))
            painter.drawText(sourceRect, "local")

        elif item.module.isLoadedFromServer():
            painter.setPen(QColor(120, 120, 120))
            painter.drawText(sourceRect, "server")

        painter.setPen(QColor(120, 120, 120))
        painter.drawText(uidRect, item.module.uid[:8])
        painter.restore()

    def paintEvent(self, event):
        super(TreeWidget, self).paintEvent(event)
        label = "Press TAB to load modules"

        fontMetrics = QFontMetrics(self.font())
        viewport = self.viewport()

        painter = QPainter(viewport)
        painter.setPen(QColor(90,90,90))
        painter.drawText(viewport.width() - fontMetrics.width(label)-10, viewport.height()-10, label)

    def dragEnterEvent(self, event):
        QTreeWidget.dragEnterEvent(self, event)

        if event.mimeData().hasUrls():
            event.accept()

        if event.mouseButtons() == Qt.MiddleButton:
            self.dragItems = self.selectedItems()
            self.dragParents = [item.parent() for item in self.dragItems]
        else:
            event.ignore()

    def dragMoveEvent(self, event):
        QTreeWidget.dragMoveEvent(self, event)

        if event.mimeData().hasUrls():
            event.setDropAction(Qt.CopyAction)

    def dropEvent(self, event):
        QTreeWidget.dropEvent(self, event)

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
                        print("Error '%s': invalid module"%path)
                        self.mainWindow.showLog()
                        self.mainWindow.logWidget.ensureCursorVisible()

        if self.dragItems:
            for oldParent, item in zip(self.dragParents, self.dragItems):
                if oldParent:
                    oldParent.module.removeChild(item.module)

                newParent = item.parent()
                if newParent:
                    if item.module in newParent.module.getChildren():
                        newParent.module.removeChild(item.module)

                    idx = newParent.indexOfChild(item)
                    newParent.module.insertChild(idx, item.module)

            self.dragItems = []
            self.dragParents = []

    def treeItemDoubleClicked(self, item, column):
        def _keepConnections(currentModule):
            connections = []
            for a in currentModule.getAttributes():
                connections.append({"attr":a, "module": currentModule, "connections":currentModule.listConnections(a)})

            for ch in currentModule.getChildren():
                connections += _keepConnections(ch)
            return connections

        if column == 0: # name
            newName, ok = QInputDialog.getText(self, "Rig Builder", "New name", QLineEdit.Normal, item.module.name)
            if ok and newName:
                newName = replaceSpecialChars(newName).strip()

                # rename in connections
                connections = _keepConnections(item.module)

                item.module.name = newName
                item.setText(0, item.module.name + " ")

                # update connections
                for data in connections:
                    srcAttr = data["attr"]
                    module = data["module"]
                    for m, a in data["connections"]:
                        a.connect = module.getPath().replace(m.getPath(inclusive=False), "") + "/" + srcAttr.name # update connection path

            item.setExpanded(not item.isExpanded()) # revert expand on double click

    def makeItemFromModule(self, module):
        item = QTreeWidgetItem([module.name+" ", module.getRelativeLoadedPathString()+" ", " ", module.uid])
        item.setFlags(Qt.ItemIsSelectable | Qt.ItemIsEnabled | Qt.ItemIsDragEnabled | Qt.ItemIsDropEnabled)
        item.module = module
        item.module.modified = False

        for ch in module.getChildren():
            item.addChild(self.makeItemFromModule(ch))

        return item

    def contextMenuEvent(self, event):
        menu = QMenu(self)
        for m in self.mainWindow.menuBar.findChildren(QMenu):
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
                sendToServer(item.module)

            else:
                QMessageBox.warning(self, "Rig Builder", "Can't send '%s' to server.\nIt works for local modules only!"%item.module.name)

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

        path, _ = QFileDialog.getOpenFileName(mainWindow, "Import", sceneDir, "*.xml")

        if not path:
            return

        Module.updateUidsCache()

        try:
            m = Module.loadFromFile(path)
            m.update()

            item = self.makeItemFromModule(m)
            self.addTopLevelItem(item)

        except ET.ParseError:
            print("Error '%s': invalid module"%path)
            self.mainWindow.showLog()
            self.mainWindow.logWidget.ensureCursorVisible()

    def saveModule(self):
        def clearModifiedFlag(module): # clear modified flag on embeded modules
            module.modified = False
            for ch in module.getChildren():
                if not ch.uid:
                    clearModifiedFlag(ch)

        selectedItems = self.selectedItems()
        if not selectedItems:
            return

        msg = "\n".join(["%s -> %s"%(item.module.name, item.module.getSavePath() or "N/A") for item in selectedItems])

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
                clearModifiedFlag(item.module)

            item.setText(1, item.module.getRelativeLoadedPathString()+" ") # update path string

    def saveAsModule(self):
        for item in self.selectedItems():
            outputDir = os.path.dirname(item.module.loadedFrom) or RigBuilderLocalPath+"/modules"
            outputPath, _ = QFileDialog.getSaveFileName(mainWindow, "Save as "+item.module.name, outputDir + "/" +item.module.name, "*.xml")

            if outputPath:
                item.module.uid = generateUid()
                item.module.saveToFile(outputPath)
                item.setText(1, item.module.getRelativeLoadedPathString()+" ") # update path string

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

            for i in range(1,4): # clear path, source and uid
                item.setText(i, "") # update path string

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

        self.repaint()

    def duplicateModule(self):
        newItems = []
        for item in self.selectedItems():
            parent = item.parent()

            newItem = self.makeItemFromModule(item.module.copy())

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
            else:
                self.invisibleRootItem().removeChild(item)

    def browseModuleSelector(self, *, mask=None, updateSource=None, modulesFrom=None):
        if mask:
            self.moduleListDialog.maskWidget.setText(mask)

        if updateSource:
            self.moduleListDialog.updateSourceWidget.setCurrentIndex({"all":0, "server": 1, "local": 2, "": 3}[updateSource])

        if modulesFrom:
            self.moduleListDialog.modulesFromWidget.setCurrentIndex({"server": 0, "local": 1}[modulesFrom])

        self.moduleListDialog.exec_()

        if self.moduleListDialog.selectedFileName:
            m = Module.loadFromFile(self.moduleListDialog.selectedFileName)
            m.update()
            self.addTopLevelItem(self.makeItemFromModule(m))

            # add to recent modules
            if m not in self.mainWindow.infoWidget.recentModules:
                self.mainWindow.infoWidget.recentModules.insert(0, m)
                if len(self.mainWindow.infoWidget.recentModules) > 10:
                    self.mainWindow.infoWidget.recentModules.pop()

            return m

    def event(self, event):
        if event.type() == QEvent.KeyPress:
            if event.key() == Qt.Key_Tab:
                self.browseModuleSelector()
                self.mainWindow.updateInfo()
                event.accept()
                return True

        return QTreeWidget.event(self, event)

class TemplateSelectorDialog(QDialog):
    def __init__(self, **kwargs):
        super(TemplateSelectorDialog, self).__init__(**kwargs)

        self.selectedTemplate = None

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
        self.selectedTemplate = t
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
        super(EditTemplateWidget, self).__init__(**kwargs)

        self.template = template
        self.connectedTo = ""

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
        if QMessageBox.question(self, "Rig Builder", "Remove '%s' attribute?"%self.nameWidget.text(), QMessageBox.Yes and QMessageBox.No, QMessageBox.Yes) == QMessageBox.Yes:
            self.copyTemplate()
            self.deleteLater()

    def downBtnClicked(self):
        editAttrsWidget = self.parent()
        idx = editAttrsWidget.attributesLayout.indexOf(self)
        if idx < editAttrsWidget.attributesLayout.count()-1:
            w = editAttrsWidget.insertCustomWidget(self.template, idx+2)
            w.templateWidget.setJsonData(self.templateWidget.getJsonData())
            w.nameWidget.setText(self.nameWidget.text())
            w.connectedTo = self.connectedTo
            self.deleteLater()

    def upBtnClicked(self):
        editAttrsWidget = self.parent()
        idx = editAttrsWidget.attributesLayout.indexOf(self)
        if idx > 0:
            w = editAttrsWidget.insertCustomWidget(self.template, idx-1)
            w.templateWidget.setJsonData(self.templateWidget.getJsonData())
            w.nameWidget.setText(self.nameWidget.text())
            w.connectedTo = self.connectedTo
            self.deleteLater()

class EditAttributesWidget(QWidget):
    nameChanged = Signal(str, str)

    def __init__(self, module, category, **kwargs):
        super(EditAttributesWidget, self).__init__(**kwargs)

        self.module = module
        self.category = category

        layout = QVBoxLayout()
        self.setLayout(layout)

        self.attributesLayout = QVBoxLayout()

        for a in self.module.getAttributes():
            if a.category == self.category:
                w = self.insertCustomWidget(a.template)
                w.nameWidget.setText(a.name)
                w.templateWidget.setJsonData(a.data)
                w.connectedTo = a.connect

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
        selector.exec_()
        if selector.selectedTemplate:
            self.insertCustomWidget(selector.selectedTemplate)

    def insertCustomWidget(self, template, row=None):
        if not widgets.TemplateWidgets.get(template):
            return

        row = self.attributesLayout.count() if row is None else row
        w = EditTemplateWidget("attr%d"%(row+1), template)
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
    def __init__(self, module, currentIndex=0, **kwargs):
        super(EditAttributesTabWidget, self).__init__(**kwargs)

        self.module = module
        self.tempRunCode = module.runCode

        self.setTabBar(QTabBar())
        self.setMovable(True)
        self.setTabsClosable(True)
        self.tabBar().mouseDoubleClickEvent = self.tabBarMouseDoubleClickEvent
        self.tabCloseRequested.connect(self.tabCloseRequest)

        tabTitlesInOrder = []
        for a in self.module.getAttributes():
            if a.category not in tabTitlesInOrder:
                tabTitlesInOrder.append(a.category)

        for t in tabTitlesInOrder:
            self.addTabCategory(t)

        if self.count() == 0:
            self.addTabCategory("General")

        self.setCurrentIndex(currentIndex)

    def addTabCategory(self, category):
        w = EditAttributesWidget(self.module, category)
        w.nameChanged.connect(self.nameChangedCallback)

        scrollArea = QScrollArea()
        scrollArea.setWidget(w)
        scrollArea.setWidgetResizable(True)
        self.addTab(scrollArea, category)
        self.setCurrentIndex(self.count()-1)

    def nameChangedCallback(self, oldName, newName):
        if oldName.strip():
            pairs = [("@\\b%s\\b"%oldName, "@"+newName),
                     ("@\\bset_%s\\b"%oldName, "@set_"+newName),
                     ("@\\b%s_data\\b"%oldName, "@"+newName+"_data")]

            self.tempRunCode = replacePairs(pairs, self.tempRunCode)

            # rename in connections
            for m, a in self.module.listConnections(self.module.findAttribute(oldName)):
                a.connect = self.module.getPath().replace(m.getPath(inclusive=False), "") + "/" + newName # update connection path

    def tabBarMouseDoubleClickEvent(self, event):
        super(EditAttributesTabWidget, self).mouseDoubleClickEvent(event)

        idx = self.currentIndex()
        newName, ok = QInputDialog.getText(self, "Rig Builder", "New name", QLineEdit.Normal, self.tabText(idx))
        if ok:
            self.setTabText(idx, newName)

    def tabCloseRequest(self, i):
        if QMessageBox.question(self, "Rig Builder", "Remove '%s' tab?"%self.tabText(i), QMessageBox.Yes and QMessageBox.No, QMessageBox.Yes) == QMessageBox.Yes:
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
    def __init__(self, module, currentIndex=0, **kwargs):
        super(EditAttributesDialog, self).__init__(**kwargs)

        self.module = module

        self.setWindowTitle("Edit Attributes - " + self.module.name)
        self.setGeometry(0, 0, 800, 600)

        layout = QVBoxLayout()
        self.setLayout(layout)

        self.tabWidget = EditAttributesTabWidget(self.module, currentIndex)

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
        self.module.clearAttributes()

        for i in range(self.tabWidget.count()):
            attrsLayout = self.tabWidget.widget(i).widget().attributesLayout # tab/scrollArea/EditAttributesWidget

            for k in range(attrsLayout.count()):
                w = attrsLayout.itemAt(k).widget()

                a = Attribute(w.nameWidget.text())
                a.data = w.templateWidget.getJsonData()
                a.template = w.template
                a.category = self.tabWidget.tabText(i)
                a.connect = w.connectedTo
                self.module.addAttribute(a)

        self.module.runCode = self.tabWidget.tempRunCode
        self.module.modified = True
        self.accept()

class CodeEditorWidget(CodeEditorWithNumbersWidget):
    def __init__(self, module=None, *, mainWindow=None, **kwargs):
        super(CodeEditorWidget, self).__init__(**kwargs)

        self.mainWindow = mainWindow
        self.module = module
        self._skipSaving = False

        self.editorWidget.syntax = PythonHighlighter(self.editorWidget.document())
        self.editorWidget.textChanged.connect(self.codeChanged)

        self.updateState()

    def codeChanged(self):
        if not self.module or self._skipSaving:
            return

        self.module.runCode = self.editorWidget.toPlainText()
        self.module.modified = True

    def updateState(self):
        if not self.module:
            return

        self.editorWidget.ignoreStates = True
        self._skipSaving = True
        self.editorWidget.setText(self.module.runCode)
        self._skipSaving = False
        self.editorWidget.ignoreStates = False

        self.editorWidget.document().clearUndoRedoStacks()
        self.generateCompletionWords()

        self.editorWidget.preset = id(self.module)
        self.editorWidget.loadState()

    def generateCompletionWords(self):
        if not self.module:
            return

        words = list(self.mainWindow.getModuleGlobalEnv().keys())
        words.extend(list(widgets.WidgetsAPI.keys()))

        for a in self.module.getAttributes():
            words.append("@" + a.name)
            words.append("@set_" + a.name)

        self.editorWidget.words = set(words)

class LogHighligher(QSyntaxHighlighter):
    def __init__(self, parent):
        super(LogHighligher, self).__init__(parent)

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
        super(LogWidget, self).__init__(**kwargs)

        self.syntax = LogHighligher(self.document())
        self.setPlaceholderText("Output and errors or warnings...")

    def write(self, txt):
        self.insertPlainText(txt)
        self.ensureCursorVisible()
        QApplication.processEvents()

class WideSplitterHandle(QSplitterHandle):
    def __init__(self, orientation, parent, **kwargs):
        super(WideSplitterHandle, self).__init__(orientation, parent, **kwargs)

    def paintEvent(self, event):
        painter = QPainter(self)
        brush = QBrush()
        brush.setStyle(Qt.Dense6Pattern)
        brush.setColor(QColor(150, 150, 150))
        painter.fillRect(event.rect(), QBrush(brush))

class WideSplitter(QSplitter):
    def __init__(self, orientation, **kwargs):
        super(WideSplitter, self).__init__(orientation, **kwargs)
        self.setHandleWidth(16)

    def createHandle(self):
        return WideSplitterHandle(self.orientation(), self)

class MyProgressBar(QWidget):    
    def __init__(self, **kwargs):
        super(MyProgressBar, self).__init__(**kwargs)

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
        super(RigBuilderWindow, self).__init__(parent=ParentWindow)

        self.setWindowTitle("Rig Builder")
        self.setGeometry(0, 0, 1300, 700)

        self.setWindowFlags(self.windowFlags() | Qt.Window)

        layout = QVBoxLayout()
        self.setLayout(layout)

        self.logWidget = LogWidget()
        self.logWidget.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Ignored)

        self.attributesTabWidget = AttributesTabWidget(mainWindow=self)
        self.attributesTabWidget.hide()

        self.treeWidget = TreeWidget(mainWindow=self)
        self.treeWidget.itemSelectionChanged.connect(self.treeItemSelectionChanged)

        self.codeEditorWidget = CodeEditorWidget(mainWindow=self)
        self.codeEditorWidget.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Ignored)
        self.codeEditorWidget.editorWidget.setPlaceholderText("Your module code...")

        self.runBtn = QPushButton("Run!")
        self.runBtn.setStyleSheet("background-color: #3e4f89")
        self.runBtn.clicked.connect(self.runModulesBtnClicked)
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

        self.menuBar = self.createMenu()
        layout.setMenuBar(self.menuBar)

        layout.addWidget(self.vsplitter)
        layout.addWidget(self.progressBarWidget)

        centerWindow(self)

    def createMenu(self):
        menuBar = QMenuBar(self)

        fileMenu = menuBar.addMenu("File")
        fileMenu.addAction("New", self.treeWidget.insertModule, "Insert")
        fileMenu.addAction("Import", self.treeWidget.importModule, "Ctrl+I")
        fileMenu.addSeparator()
        fileMenu.addAction("Save", self.treeWidget.saveModule, "Ctrl+S")
        fileMenu.addAction("Save as", self.treeWidget.saveAsModule)
        fileMenu.addSeparator()
        fileMenu.addAction("Locate file", self.locateModuleFile)        

        editMenu = menuBar.addMenu("Edit")
        editMenu.addAction("Duplicate", self.treeWidget.duplicateModule, "Ctrl+D")
        editMenu.addSeparator()
        editMenu.addAction("Update", self.treeWidget.updateModule, "Ctrl+U")
        editMenu.addAction("Send to server", self.treeWidget.sendModuleToServer)
        editMenu.addAction("Embed", self.treeWidget.embedModule)
        editMenu.addSeparator()
        editMenu.addAction("Mute", self.treeWidget.muteModule, "M")
        editMenu.addAction("Remove", self.treeWidget.removeModule, "Delete")
        editMenu.addAction("Clear all", self.clearAllModules)

        helpMenu = menuBar.addMenu("Help")
        helpMenu.addAction("Documentation", self.showDocumenation)

        return menuBar

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
        selected = self.treeWidget.selectedItems()
        en = True if selected else False
        self.attributesTabWidget.setVisible(en)
        self.runBtn.setVisible(en)
        self.infoWidget.setVisible(not en)
        self.codeEditorWidget.setEnabled(en and not self.isCodeEditorHidden())

        if selected:
            item = selected[0]

            self.attributesTabWidget.module = item.module
            self.attributesTabWidget.updateTabs()

            if self.codeEditorWidget.isEnabled():
                self.codeEditorWidget.module = item.module
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
                    template.append("<h3 style='background-color: #393939'>%s</h3>"%escape(k))
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

    def getCurrentModule(self):
        selected = self.treeWidget.selectedItems()
        if not selected:
            return
        return selected[0].module

    def isCodeEditorHidden(self):
        return self.vsplitter.sizes()[1] == 0 # code section size

    def codeSplitterMoved(self, sz, n):
        currentModule = self.getCurrentModule()

        if self.isCodeEditorHidden():
            self.codeEditorWidget.setEnabled(False)

        elif not self.codeEditorWidget.isEnabled() and currentModule:
            self.codeEditorWidget.module = currentModule
            self.codeEditorWidget.updateState()
            self.codeEditorWidget.setEnabled(True)

    def showLog(self):
        sizes = self.vsplitter.sizes()
        if sizes[-1] < 10:
            sizes[-1] = 200
            self.vsplitter.setSizes(sizes)

    def getModuleGlobalEnv(self):
        env = {"beginProgress": self.progressBarWidget.beginProgress,
               "stepProgress": self.progressBarWidget.stepProgress,
               "endProgress": self.progressBarWidget.endProgress,
               "currentTabIndex": self.attributesTabWidget.currentIndex()}

        for k,v in getModuleDefaultEnv().items():
            env[k] = v

        for k, f in widgets.WidgetsAPI.items():
            env[k] = f

        return env

    def runModulesBtnClicked(self):
        if DCC == "maya":
            cmds.undoInfo(ock=True) # run in undo chunk
            self.runModules()
            cmds.undoInfo(cck=True)
        else:
            self.runModules()

    def runModules(self):
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

            try:
                currentItem.module.run(self.getModuleGlobalEnv(), uiCallback=uiCallback)
            except Exception:
                printErrorStack()
            finally:
                currentItem.module.muted = muted
                print("Done in %.2fs"%(time.time() - startTime))

        self.progressBarWidget.endProgress()
        self.attributesTabWidget.updateTabs()

def RigBuilderTool(spec, child=None): # spec can be full path, relative path, uid
    module = Module.loadModule(spec)
    if not module:
        print("Cannot load '{}' module".format(spec))
        return

    if child:
        module = module.findChild(child)
        if not module:
            print("Cannot find '{}' child".format(child))
            return

    w = RigBuilderWindow()
    w.menuBar.hide()
    w.treeWidget.addTopLevelItem(w.treeWidget.makeItemFromModule(module))
    w.treeWidget.setCurrentItem(w.treeWidget.topLevelItem(0))
    w.setWindowTitle("Rig Builder Tool - {}".format(module.getPath()))
    w.attributesTabWidget.adjustSize()
    w.resize(w.attributesTabWidget.size() + QSize(50, 100))
    w.codeEditorWidget.hide()
    w.treeWidget.hide()
    centerWindow(w)
    return w

if not os.path.exists(RigBuilderLocalPath):
    os.makedirs(RigBuilderLocalPath+"/modules")

mainWindow = RigBuilderWindow()
