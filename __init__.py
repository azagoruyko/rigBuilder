# -*- coding: utf-8 -*-

import time
import json
import re
import traceback
import subprocess
import os
import sys
from contextlib import contextmanager

from Qt.QtGui import *
from Qt.QtCore import *
from Qt.QtWidgets import *

from .classes import *
from .editor import *
import widgets
from .templateWidgets import * # TemplateWidgets variable

try:
    import maya.cmds as cmds
    import pymel.api as api

    from shiboken2 import wrapInstance
    mayaMainWindow = wrapInstance(long(api.MQtUtil.mainWindow()), QMainWindow)

    IsMayaAvailable = True
except ImportError:
    IsMayaAvailable = False

ScriptGlobals = {}

def clamp(mn, mx, val):
    if val < mn:
        return mn
    elif val > mx:
        return mx
    else:
        return val

def formatPython(text):
    startupinfo = subprocess.STARTUPINFO()
    startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW

    cwd = os.getcwd()
    os.chdir(RigBuilderPath) # set root directory

    process = subprocess.Popen([RigBuilderPath+"/utils/yapf.exe", "--style", RigBuilderPath+"/utils/.style.yapf"],
                               stdin=subprocess.PIPE,
                               stdout=subprocess.PIPE,
                               stderr=subprocess.STDOUT,
                               startupinfo=startupinfo)

    data, err = process.communicate(text.encode("utf-8"))
    os.chdir(cwd)
    return data.decode("utf-8") if not err else text

def trimText(text, size):
    return "..." + text[-size+3:]  if len(text) > size else " "*(size-len(text)) + text

def replaceSpecialChars(text):
    return re.sub("[^a-zA-Z0-9_]", "_", text)

def replacePairs(pairs, text):
    for k, v in pairs:
        text = re.sub(k, v, text)
    return text

@contextmanager
def captureOutput(stream):
    default_stdout = sys.stdout
    default_stderr = sys.stderr

    sys.stdout = stream
    sys.stderr = stream
    yield
    sys.stdout = default_stdout
    sys.stderr = default_stderr

def widgetOnChange(widget, module, attr):
    data = widget.getJsonData()

    if attr.connect:
        srcAttr = module.findConnectionSourceForAttribute(attr)
        srcAttr.data = data

    else:
        attr.data = data

    #print attr.name, "=", attr.data

class TabAttributesWidget(QWidget):
    def __init__(self, module, attributes, mainWindow, **kwargs):
        super(TabAttributesWidget, self).__init__(**kwargs)

        self.module = module
        self.mainWindow = mainWindow

        layout = QGridLayout()
        layout.setDefaultPositioning(2, Qt.Horizontal)     
        layout.setColumnStretch(1, 1)
        self.setLayout(layout)

        if self.module:
            with captureOutput(self.mainWindow.logWidget):
                try:
                    self.module.resolveConnections()
                except AttributeResolverError as err:
                    print("Error: " + str(err))
                    self.mainWindow.showLog()
                    self.mainWindow.logWidget.ensureCursorVisible()

        for i, a in enumerate(attributes):
            templateWidget = TemplateWidgets[a.template](env={"mainWindow":self.mainWindow, "module": self.module, "GLOBALS":ScriptGlobals})
            templateWidget.setJsonData(a.data)
            templateWidget.somethingChanged.connect(lambda w=templateWidget, e=module, a=a: widgetOnChange(w, e, a))

            nameWidget = QLabel(a.name)
            nameWidget.setAlignment(Qt.AlignRight)
            nameWidget.setContextMenuPolicy(Qt.DefaultContextMenu)
            nameWidget.setStyleSheet("QLabel:hover:!pressed{ background-color: #444444; }")

            if a.connect:
                templateWidget.setToolTip("Connect: %s"%a.connect)
                templateWidget.setStyleSheet("background-color: #606027")

            nameWidget.contextMenuEvent = lambda event, a=a: self.nameContextMenuEvent(event, a)
            nameWidget.attribute = a

            layout.addWidget(nameWidget)
            layout.addWidget(templateWidget)

        layout.addWidget(QLabel())
        layout.setRowStretch(layout.rowCount(), 1)

    def connectionMenuAction(self, label, attr, connect):
        action = QAction(label, self)
        action.triggered.connect(lambda connect=connect, attr=attr: self.connectAttr(connect, attr))
        return action

    def connectionMenu(self, menu, module, attr, path="/"):
        subMenu = QMenu(module.name)

        for a in module.getAttributes():
            if a.template == attr.template:
                subMenu.addAction(self.connectionMenuAction(a.name, attr, path+module.name+"/"+a.name))

        for ch in module.getChildren():
            self.connectionMenu(subMenu, ch, attr, path+module.name+"/")

        if subMenu.actions():
            menu.addMenu(subMenu)

    def nameContextMenuEvent(self, event, attr):
        menu = QMenu(self)

        if self.module and self.module.parent:
            makeConnectionMenu = QMenu("Make connection")
            for a in self.module.parent.getAttributes():
                if a.template == attr.template:
                    makeConnectionMenu.addAction(self.connectionMenuAction(a.name, attr, "/"+a.name))

            for ch in self.module.parent.getChildren():
                if ch is self.module:
                    continue

                self.connectionMenu(makeConnectionMenu, ch, attr)

            menu.addMenu(makeConnectionMenu)

        breakAction = QAction("Break connection", self)
        breakAction.triggered.connect(lambda attr=attr: self.disconnectAttr(attr))
        menu.addAction(breakAction)

        setDataAction = QAction("Set data", self)
        setDataAction.triggered.connect(lambda attr=attr: self.setData(attr))
        menu.addAction(setDataAction)

        resetAction = QAction("Reset", self)
        resetAction.triggered.connect(lambda attr=attr: self.resetAttr(attr))
        menu.addAction(resetAction)

        menu.popup(event.globalPos())

    def setData(self, attr):
        text = json.dumps(attr.data, indent=4).replace("'", "\"")
        editText = widgets.EditTextDialog(text, "Set '%s' data"%attr.name, parent=QApplication.activeWindow())
        editText.exec_()
        if editText.result():
            with captureOutput(self.mainWindow.logWidget):
                try:
                    data = json.loads(editText.outputText) 
                    tmp = TemplateWidgets[attr.template]() # also we need check for widget compatibility
                    tmp.setJsonData(data)

                except:
                    print("Error: invalid or incompatible json data")
                    self.mainWindow.showLog()
                    self.mainWindow.logWidget.ensureCursorVisible()

                else:
                    attr.data = data
                    self.mainWindow.attributesWidget.update()

    def resetAttr(self, attr):
        tmp = TemplateWidgets[attr.template]()
        attr.data = tmp.getDefaultData()
        attr.connect = ""
        self.mainWindow.attributesWidget.update()

    def disconnectAttr(self, attr):
        attr.connect = ""        
        self.mainWindow.attributesWidget.update()

    def connectAttr(self, connect, destAttr):
        destAttr.connect = connect   
        self.mainWindow.attributesWidget.update()

class AttributesWidget(QWidget):
    def __init__(self, module=None, mainWindow=None, **kwargs):
        super(AttributesWidget, self).__init__(**kwargs)

        self.mainWindow = mainWindow
        self.module = module
        self.tabsData = {}

        self.setContextMenuPolicy(Qt.DefaultContextMenu)

        layout = QVBoxLayout()
        self.setLayout(layout)
        layout.setContentsMargins(0, 0, 0, 0) 

        self.tabWidget = QTabWidget()
        self.tabWidget.currentChanged.connect(self.tabChanged)
        layout.addWidget(self.tabWidget)

        self.update()

    def contextMenuEvent(self, event):
        menu = QMenu(self)

        if self.module:
            editAttrsAction = QAction("Edit attributes", self)
            editAttrsAction.triggered.connect(self.editAttributesClicked)
            menu.addAction(editAttrsAction)

        menu.popup(event.globalPos())

    def editAttributesClicked(self):
        dialog = EditAttributesDialog(self.module, self.tabWidget.currentIndex(), parent=QApplication.activeWindow())
        dialog.exec_()
        
        self.mainWindow.codeEditorWidget.update()
        self.mainWindow.attributesWidget.update()

    def tabChanged(self, idx):
        if self.tabWidget.count() == 0:
            return

        idx = clamp(0, self.tabWidget.count()-1, idx)

        title = self.tabWidget.tabText(idx)
        scrollArea = self.tabWidget.widget(idx)
        scrollArea.setWidget(TabAttributesWidget(self.module, self.tabsData[title]["attributes"], mainWindow=self.mainWindow))

        self.tabWidget.setCurrentIndex(idx)

    def update(self):
        tabw = self.tabWidget

        oldIndex = tabw.currentIndex()
        prevCount = tabw.count()

        self.tabsData.clear()

        if not self.module:
            return

        tabw.blockSignals(True)

        order = 0
        for a in self.module.getAttributes():
            k = a.category

            if k not in self.tabsData:
                self.tabsData[k] = {"order":order, "attributes":[]}
                order += 1

            self.tabsData[k]["attributes"].append(a)

        for t in sorted(self.tabsData, key=lambda item: self.tabsData[item]["order"]):
            scrollArea = QScrollArea()
            scrollArea.setWidgetResizable(True)
            tabw.addTab(scrollArea, t)

        for i in range(prevCount):
            w = tabw.widget(0)
            if w:
                w.deleteLater()
            tabw.removeTab(0)

        self.tabChanged(oldIndex)
        tabw.blockSignals(False)

        if tabw.count() == 1:
            tabw.tabBar().hide()
        else:
            tabw.tabBar().show()

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
        self.updateSourceWidget.currentIndexChanged.connect(lambda _=None: self.updateModules())

        self.modulesFromWidget = QComboBox()
        self.modulesFromWidget.addItems(["Server", "Local"])
        self.modulesFromWidget.currentIndexChanged.connect(lambda _=None: self.updateModules())

        self.maskWidget = QLineEdit()
        self.maskWidget.textChanged.connect(self.updateModules)

        gridLayout.addWidget(QLabel("Update source"))
        gridLayout.addWidget(self.updateSourceWidget)

        gridLayout.addWidget(QLabel("Modules from"))
        gridLayout.addWidget(self.modulesFromWidget)

        gridLayout.addWidget(QLabel("Filter"))
        gridLayout.addWidget(self.maskWidget)
        
        self.treeWidget = QTreeWidget()
        self.treeWidget.setHeaderLabels(["Module", "Modification time"])
        self.treeWidget.itemActivated.connect(self.treeItemActivated)
        if "setSectionResizeMode" in dir(self.treeWidget.header()):
            self.treeWidget.header().setSectionResizeMode(QHeaderView.ResizeToContents) # Qt5
        else:
            self.treeWidget.header().setResizeMode(QHeaderView.ResizeToContents) # Qt4

        self.treeWidget.setSortingEnabled(True)
        self.treeWidget.sortItems(1, Qt.AscendingOrder)
        self.treeWidget.setContextMenuPolicy(Qt.DefaultContextMenu)
        self.treeWidget.contextMenuEvent = self.treeContextMenuEvent
        
        layout.addLayout(gridLayout)
        layout.addWidget(self.treeWidget)

        self.maskWidget.setFocus()

        setStylesheet(self)

    def showEvent(self, event):
        pos = self.mapToParent(self.mapFromGlobal(QCursor.pos()))
        self.setGeometry(pos.x(), pos.y(), 600, 400)

        Module.updateUidsCache()

        self.selectedFileName = ""
        self.updateModules()
        self.maskWidget.setFocus()

    def treeContextMenuEvent(self, event):
        menu = QMenu(self)

        locateAction = QAction("Open explorer", self)
        locateAction.triggered.connect(self.browseModuleDirectory)
        menu.addAction(locateAction)

        menu.popup(event.globalPos())

    def browseModuleDirectory(self):
        os.system("explorer /select,%s"%os.path.realpath(self.getRootDirectory() + "/modules"))

    def treeItemActivated(self, item, _):
        if item.childCount() == 0:
            fileName = unicode(item.text(0))
            self.selectedFileName = item.filePath
            self.done(0)

    def findChildByText(self, text, parent, column=0):
        for i in range(parent.childCount()):
            ch = parent.child(i)
            if text == ch.text(column):
                return ch

    def makeRecursiveItems(self, elements, expanded=True): # ["folder", "child", ...] -> QTreeWidgetItem
        currentParentItem = self.treeWidget.invisibleRootItem()

        for i, elem in enumerate(elements):
            item = self.findChildByText(elem, currentParentItem)
            if not item:
                item = QTreeWidgetItem([elem, ""])
                item.setForeground(0, QColor(130, 130, 230))
                currentParentItem.addChild(item)
                item.setExpanded(expanded)

            currentParentItem = item

        return currentParentItem

    def updateModules(self):
        updateSource = self.updateSourceWidget.currentIndex()
        modulesFrom = self.modulesFromWidget.currentIndex()

        modulesDirectory = RigBuilderPath+"/modules" if modulesFrom == 0 else RigBuilderLocalPath+"/modules"
        
        UpdateSourceFromInt = {0: "all", 1: "server", 2: "local", 3: ""}
        Module.updateUidsCache(UpdateSourceFromInt[updateSource])

        mask = re.escape(unicode(self.maskWidget.text()))

        tw = self.treeWidget
        tw.clear()        

        modules = Module.listModules(modulesDirectory)
        for f in modules:
            name, _ = os.path.splitext(os.path.basename(f))

            relativePath = os.path.relpath(f, modulesDirectory)

            if re.search(mask, name, re.IGNORECASE):
                dirname = os.path.dirname(relativePath)

                if dirname:
                    parentItem = self.makeRecursiveItems(re.split("[\\/]", dirname), True if mask else False)
                else:
                    parentItem = self.treeWidget.invisibleRootItem()

                modtime = time.strftime("%Y/%m/%d %H:%M", time.localtime(os.path.getmtime(f)))

                item = QTreeWidgetItem([name, modtime])
                item.filePath = f
                parentItem.addChild(item)

class TreeWidget(QTreeWidget):
    def __init__(self, mainWindow, **kwargs):
        super(TreeWidget, self).__init__(**kwargs)

        self.mainWindow = mainWindow
        self.dragItems = [] # using in drag & drop

        self.moduleListDialog = ModuleListDialog()

        self.setHeaderLabels(["Name", "Type", "Source", "UID"])
        self.setSelectionMode(QAbstractItemView.ExtendedSelection) # ExtendedSelection

        if "setSectionResizeMode" in dir(self.header()):
            self.header().setSectionResizeMode(QHeaderView.ResizeToContents) # Qt5
        else:
            self.header().setResizeMode(QHeaderView.ResizeToContents) # Qt4

        self.setDragEnabled(True)
        self.setDragDropMode(QAbstractItemView.InternalMove)
        self.setDropIndicatorShown(True)
        self.setAcceptDrops(True)

        self.setContextMenuPolicy(Qt.DefaultContextMenu)

        self.setIndentation(30)

        self.setMouseTracking(True)
        self.itemChanged.connect(self.treeItemChanged)
        self.itemSelectionChanged.connect(self.treeItemSelectionChanged)

    def drawRow(self, painter, options, modelIdx):
        painter.save()

        rect = self.visualRect(modelIdx)
        item = self.itemFromIndex(modelIdx)
 
        indent = self.indentation()

        if rect.width() < 0:
            return

        isParentMuted = False
        isParentReference = False

        parent = item.parent()
        while parent:
            isParentMuted = isParentMuted or parent.module.muted
            isParentReference = isParentReference or parent.module.uid
            parent = parent.parent()

        painter.setPen(QPen(QBrush(QColor(60, 60, 60)), 1, Qt.SolidLine))
        numberBranch = rect.x() / indent
        if numberBranch > 1:
            for i in range(1, numberBranch):
                plusInt = i * indent + 10
                x = rect.x() - plusInt
                painter.drawLine(x, rect.y(), x, rect.y() + rect.height())

        if item.childCount() and rect.x() + rect.width() > rect.x():
            painter.setPen(QPen(QBrush(QColor(100, 100, 100)), 1, Qt.SolidLine))
            painter.fillRect(QRect(rect.x() - 16, rect.y() + 4, 12, 12), QColor(45, 45, 45))
            painter.drawRect(rect.x() - 16, rect.y() + 4, 12, 12)
            painter.setPen(QPen(QBrush(QColor(120, 120, 120)), 1, Qt.SolidLine))
            if item.isExpanded():
                painter.drawLine(rect.x() - 7, rect.y() + 10, rect.x() - 13, rect.y() + 10)
            else:
                painter.drawLine(rect.x() - 10, rect.y() + 7, rect.x() - 10, rect.y() + 14)
                painter.drawLine(rect.x() - 7, rect.y() + 10, rect.x() - 13, rect.y() + 10)

        nameIdx = modelIdx.sibling(modelIdx.row(), 0)
        nameRect = self.visualRect(nameIdx)

        typeIdx = modelIdx.sibling(modelIdx.row(), 1)
        typeRect = self.visualRect(typeIdx)

        if not re.match("\\w*", unicode(item.module.name)):
            painter.fillRect(nameRect, QBrush(QColor(170, 50, 50)))

        itemParent = item.parent()
        if itemParent and len([ch for ch in itemParent.module.getChildren() if ch.name == item.module.name]) > 1:
            painter.fillRect(nameRect, QBrush(QColor(170, 50, 50)))

        # set selected style
        if modelIdx in self.selectedIndexes():
            painter.fillRect(rect.x()-1, rect.y(), painter.viewport().width()-1, rect.height()-1, QColor(80, 96, 154, 60))
            painter.setPen(QColor(73, 146, 158))
            painter.drawRect(rect.x()-1, rect.y(), painter.viewport().width()-1, rect.height()-1)

        painter.setPen(QColor(210, 210, 210))
        if isParentReference:
            font = painter.font()
            font.setItalic(True)
            painter.setFont(font)
            painter.setPen(QColor(180, 180, 230))

        if item.module.muted or isParentMuted:
            painter.setPen(QColor(90, 90, 90))

        painter.drawText(nameRect, Qt.AlignLeft | Qt.AlignVCenter, item.module.name)

        if not re.match("^[\\w/ ]*$", unicode(item.module.type)):
            painter.setPen(QColor(200, 200, 200))
            painter.fillRect(typeRect, QBrush(QColor(170, 50, 50)))

        painter.drawText(typeRect, Qt.AlignLeft | Qt.AlignVCenter, item.module.type)

        sourceRect = self.visualRect(modelIdx.sibling(modelIdx.row(), 2))
        painter.setPen(QColor(110, 110, 150))

        if item.module.isLoadedFromLocal():
            painter.drawText(sourceRect, "local")

        elif item.module.isLoadedFromServer():
            painter.drawText(sourceRect, "server")

        uidRect = self.visualRect(modelIdx.sibling(modelIdx.row(), 3))
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
            links = []
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

    def treeItemSelectionChanged(self):
        selected = self.selectedItems()
        en = True if selected else False
        self.mainWindow.attributesWidget.setEnabled(en)
        self.mainWindow.codeEditorWidget.setEnabled(en and not self.mainWindow.isCodeEditorHidden())

        if selected:
            item = selected[0]

            self.mainWindow.attributesWidget.module = item.module
            self.mainWindow.attributesWidget.update()

            if self.mainWindow.codeEditorWidget.isEnabled():
                self.mainWindow.codeEditorWidget.module = item.module
                self.mainWindow.codeEditorWidget.update()

    def treeItemChanged(self, item):
        newName = unicode(item.text(0)).strip()
        newType = unicode(item.text(1)).strip()

        item.module.name = replaceSpecialChars(newName)
        item.setText(0, item.module.name)
        
        item.module.type = newType
        item.setText(1, item.module.type)

        self.updateItemToolTip(item)
        self.mainWindow.attributesWidget.update()

    def updateItemToolTip(self, item):        
        tooltip = []
        fname = item.module.loadedFrom
        if item.module.loadedFrom and os.path.exists(fname):
            tooltip.append("<b>uid</b>: %s"%item.module.uid)
            tooltip.append("<b>Loaded from</b>: %s"%fname)
            tooltip.append("<b>File modification time</b>: %s"%time.strftime("%Y/%m/%d %H:%M", time.localtime(os.path.getmtime(fname))))
        item.setToolTip(0, "<br>".join(tooltip))

        item.setToolTip(3, item.module.uid)

    def makeItemFromModule(self, module):
        item = QTreeWidgetItem([module.name+" ", module.type+" ", " ", module.uid])
        item.setFlags(Qt.ItemIsSelectable | Qt.ItemIsEditable | Qt.ItemIsEnabled | Qt.ItemIsDragEnabled | Qt.ItemIsDropEnabled)
        item.module = module

        self.updateItemToolTip(item)

        if module.type and os.path.exists(module.loadedFrom):
            item.setForeground(0, QColor(80,140,180))

        for ch in module.getChildren():
            item.addChild(self.makeItemFromModule(ch))        

        return item

    def keyPressEvent(self, event):
        shift = event.modifiers() & Qt.ShiftModifier
        ctrl = event.modifiers() & Qt.ControlModifier
        alt = event.modifiers() & Qt.AltModifier
        key = event.key()

        if key == Qt.Key_Insert:
            self.addTopLevelItem(self.makeItemFromModule(Module("module")))

        elif ctrl and key == Qt.Key_D:
            self.duplicateModule()

        elif key == Qt.Key_M:
            self.muteModule()

        elif ctrl and key == Qt.Key_S:
            self.saveModule()

        elif ctrl and key == Qt.Key_I:
            self.importModule()

        elif ctrl and key == Qt.Key_U:
            self.updateModule()

        elif ctrl and key == Qt.Key_R:
            self.updateModule(False)

        elif key == Qt.Key_Delete:
            self.removeModule()

    def contextMenuEvent(self, event):
        menu = QMenu(self)

        newAction = QAction("New\tINSERT", self)
        newAction.triggered.connect(lambda: self.addTopLevelItem(self.makeItemFromModule(Module("module"))))
        menu.addAction(newAction)

        importAction = QAction("Import\tCTRL-I", self)
        importAction.triggered.connect(self.importModule)
        menu.addAction(importAction)        

        if self.selectedItems():
            dupAction = QAction("Duplicate\tCTRL-D", self)
            dupAction.triggered.connect(self.duplicateModule)
            menu.addAction(dupAction)

            muteAction = QAction("Mute\tM", self)
            muteAction.triggered.connect(self.muteModule)
            menu.addAction(muteAction)

            menu.addSeparator()
            saveAction = QAction("Save\tCTRL-S", self)
            saveAction.triggered.connect(self.saveModule)
            menu.addAction(saveAction)        

            saveAsAction = QAction("Save as", self)
            saveAsAction.triggered.connect(self.saveAsModule)
            menu.addAction(saveAsAction)        

            updateAction = QAction("Update\tCTRL-U", self)
            updateAction.triggered.connect(self.updateModule)
            menu.addAction(updateAction)

            embedAction = QAction("Embed", self)
            embedAction.triggered.connect(self.embedModule)
            menu.addAction(embedAction)        

            menu.addSeparator()

            removeAction = QAction("Remove\tDELETE", self)
            removeAction.triggered.connect(self.removeModule)
            menu.addAction(removeAction)

        locateAction = QAction("Locate file", self)
        locateAction.triggered.connect(self.locateModuleFile)
        menu.addAction(locateAction)

        clearAction = QAction("Clear all", self)
        clearAction.triggered.connect(self.clearAll)
        menu.addAction(clearAction)

        menu.popup(event.globalPos())

    def importModule(self):
        defaultPath = RigBuilderLocalPath+"/modules/"

        if IsMayaAvailable:
            sceneDir = os.path.dirname(api.MFileIO.currentFile())
            if sceneDir:
                defaultPath = sceneDir + "/"

        path, _ = QFileDialog.getOpenFileName(self.mainWindow, "Import", defaultPath, "*.xml")

        if not path:
            return

        try:
            m = Module.loadFromFile(path)
            m.update()

            item = self.makeItemFromModule(m)
            self.addTopLevelItem(item)
            self.updateItemToolTip(item)

        except ET.ParseError:
            print("Error '%s': invalid module"%path)
            self.mainWindow.showLog()
            self.mainWindow.logWidget.ensureCursorVisible()

    def saveModule(self):
        msg = "\n".join(["%s -> %s"%(item.module.name, item.module.getSavePath() or "N/A") for item in self.selectedItems()])

        if QMessageBox.question(self, "Rig Builder", "Save modules?\n%s"%msg, QMessageBox.Yes and QMessageBox.No, QMessageBox.Yes) == QMessageBox.Yes:
            for item in self.selectedItems():
                outputPath = item.module.getSavePath()

                if not outputPath:
                    name = item.module.type or item.module.name
                    outputPath, _ = QFileDialog.getSaveFileName(self.mainWindow, "Save "+item.module.name, RigBuilderLocalPath+"/modules/"+name, "*.xml")

                if outputPath:
                    dirname = os.path.dirname(outputPath)
                    if not os.path.exists(dirname):
                        os.makedirs(dirname)

                    item.module.saveToFile(outputPath)

                    self.updateItemToolTip(item)

    def saveAsModule(self):
        for item in self.selectedItems():
            outputDir = os.path.dirname(api.MFileIO.currentFile())
            name = item.module.type or item.module.name
            outputPath, _ = QFileDialog.getSaveFileName(self.mainWindow, "Save as "+item.module.name, outputDir + "/" +name, "*.xml")

            if outputPath:                
                item.module.uid = generateUid()
                item.module.saveToFile(outputPath)

            self.updateItemToolTip(item)

    def embedModule(self):
        if QMessageBox.question(self, "Rig Builder", "Embed modules?", QMessageBox.Yes and QMessageBox.No, QMessageBox.Yes) == QMessageBox.Yes:
            for item in self.selectedItems():
                item.module.uid = ""
                item.module.loadedFrom = ""
            self.updateItemToolTip(item)

    def locateModuleFile(self):
        for item in self.selectedItems():
            if item and os.path.exists(item.module.loadedFrom):
                os.system("explorer /select,%s"%os.path.realpath(item.module.loadedFrom))

    def clearAll(self):
        ok = QMessageBox.question(self, "Rig Builder", "Remove all modules?",
                                  QMessageBox.Yes and QMessageBox.No, QMessageBox.Yes) == QMessageBox.Yes
        if ok:
            self.clear()

    def updateModule(self):
        Module.updateUidsCache()

        items = "\n".join([item.text(0) for item in self.selectedItems()])
        ok = QMessageBox.question(self, "Rig Builder", "Update selected modules?\n%s"%items,
                                  QMessageBox.Yes and QMessageBox.No, QMessageBox.Yes) == QMessageBox.Yes
        if ok:
            for item in self.selectedItems():
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
        items = "\n".join([item.text(0) for item in self.selectedItems()])

        ok = QMessageBox.question(self, "Rig Builder", "Remove modules?\n%s"%items,
                                  QMessageBox.Yes and QMessageBox.No, QMessageBox.Yes) == QMessageBox.Yes
        if not ok:
            return

        for item in self.selectedItems():
            parent = item.parent()
            if parent:
                parent.removeChild(item)
                parent.module.removeChild(item.module)
            else:
                self.invisibleRootItem().removeChild(item)

    def event(self, event):
        if event.type() == QEvent.KeyPress:
            if event.key() == Qt.Key_Tab:
                self.moduleListDialog.exec_()

                if self.moduleListDialog.selectedFileName:
                    m = Module.loadFromFile(self.moduleListDialog.selectedFileName)
                    m.update()

                    self.addTopLevelItem(self.makeItemFromModule(m))

                event.accept()
                return True

        return QTreeWidget.event(self, event)                

def clearLayout(layout):
     if layout is not None:
         while layout.count():
             item = layout.takeAt(0)
             widget = item.widget()
             if widget is not None:
                 widget.setParent(None)
             else:
                 clearLayout(item.layout())

class TemplateSelectorDialog(QDialog):
    def __init__(self, **kwargs):
        super(TemplateSelectorDialog, self).__init__(**kwargs)

        self.selectedTemplate = None

        self.setWindowTitle("Template Selector")
        self.setGeometry(600, 300, 400, 500)

        layout = QVBoxLayout()
        self.setLayout(layout)

        self.filterWidget = QLineEdit()
        self.filterWidget.textChanged.connect(self.update)

        scrollArea = QScrollArea()
        scrollWidget = QWidget()
        scrollArea.setWidget(scrollWidget)
        scrollArea.setWidgetResizable(True)

        scrollWidget.setLayout(QGridLayout())

        self.gridLayout = scrollWidget.layout()
        self.gridLayout.setDefaultPositioning(3, Qt.Horizontal)

        layout.addWidget(self.filterWidget)
        layout.addWidget(scrollArea)
        self.filterWidget.setFocus()

        self.update()

    def selectTemplate(self, t):
        self.selectedTemplate = t
        self.done(0)

    def update(self):
        clearLayout(self.gridLayout)

        filterText = unicode(self.filterWidget.text())

        for t in sorted(TemplateWidgets.keys()):
            if not filterText or re.search(filterText, t, re.IGNORECASE):
                self.gridLayout.addWidget(QLabel(t))
                w  = TemplateWidgets[t]()
                w.setJsonData(w.getDefaultData())
                self.gridLayout.addWidget(w)

                selectBtn = QPushButton("Select")
                selectBtn.clicked.connect(lambda t=t: self.selectTemplate(t))
                self.gridLayout.addWidget(selectBtn)

class EditTemplateWidget(QWidget):
    Clipboard = []

    def __init__(self, name, template, **kwargs):
        super(EditTemplateWidget, self).__init__(**kwargs)

        self.template = template
        self.connectedTo = ""
        self.nameChangedCallback = None

        layout = QHBoxLayout()
        layout.setContentsMargins(0,0,0,0)
        self.setLayout(layout)

        self.nameWidget = QLabel(name)
        self.nameWidget.setFixedWidth(150)
        self.nameWidget.setAlignment(Qt.AlignRight)
        self.nameWidget.mouseDoubleClickEvent = self.nameMouseDoubleClickEvent
        self.nameWidget.setContextMenuPolicy(Qt.DefaultContextMenu)
        self.nameWidget.contextMenuEvent = self.nameContextMenuEvent
        self.nameWidget.setStyleSheet("QLabel:hover:!pressed{ background-color: #444444; }")

        self.templateWidget = TemplateWidgets[template]()

        buttonsLayout = QHBoxLayout()
        buttonsLayout.setContentsMargins(0,0,0,0)
        upBtn = QPushButton(u"▲")
        upBtn.setFixedSize(25, 25)
        upBtn.clicked.connect(self.upBtnClicked)

        downBtn = QPushButton(u"▼")
        downBtn.setFixedSize(25, 25)
        downBtn.clicked.connect(self.downBtnClicked)

        removeBtn = QPushButton(u"▬")
        removeBtn.setFixedSize(25, 25)
        removeBtn.clicked.connect(self.removeBtnClicked)

        buttonsLayout.addWidget(upBtn)
        buttonsLayout.addWidget(downBtn)
        buttonsLayout.addWidget(removeBtn)

        layout.addWidget(self.nameWidget)#, alignment=Qt.AlignRight | Qt.AlignTop)
        layout.addWidget(self.templateWidget)
        layout.addLayout(buttonsLayout)

    def nameContextMenuEvent(self, event):
        menu = QMenu(self)

        copyAction = QAction("Copy", self)
        copyAction.triggered.connect(self.copyTemplate)
        menu.addAction(copyAction)

        if EditTemplateWidget.Clipboard and EditTemplateWidget.Clipboard[0]["template"] == self.template:
            pasteAction = QAction("Paste", self)
            pasteAction.triggered.connect(lambda data=EditTemplateWidget.Clipboard[0]["data"]: self.templateWidget.setJsonData(data))
            menu.addAction(pasteAction)

        menu.popup(event.globalPos())

    def copyTemplate(self):
        module = {"data": self.templateWidget.getJsonData(), 
                  "template": self.template, 
                  "name": self.nameWidget.text()}

        EditTemplateWidget.Clipboard = [module]

    def nameMouseDoubleClickEvent(self, event):
        oldName = self.nameWidget.text()
        newName, ok = QInputDialog.getText(self, "Rename", "New name", QLineEdit.Normal, oldName)
        if ok:
            newName = replaceSpecialChars(newName)
            self.nameWidget.setText(newName)

            if callable(self.nameChangedCallback):
                self.nameChangedCallback(oldName, newName)

    def removeBtnClicked(self):
        ok = QMessageBox.question(self, "Rig Builder", "Remove '%s' attribute?"%self.nameWidget.text(), 
                                  QMessageBox.Yes and QMessageBox.No, QMessageBox.Yes) == QMessageBox.Yes
        if ok:
            self.copyTemplate()
            self.deleteLater()

    def downBtnClicked(self):
        editAttrsWidget = self.parent()
        idx = editAttrsWidget.attributesLayout.indexOf(self)
        if idx < editAttrsWidget.attributesLayout.count()-1:
            w = editAttrsWidget.insertCustomWidget(self.template, idx+2)
            w.templateWidget.setJsonData(self.templateWidget.getJsonData())
            w.nameWidget.setText(self.nameWidget.text())
            self.deleteLater()

    def upBtnClicked(self):
        editAttrsWidget = self.parent()
        idx = editAttrsWidget.attributesLayout.indexOf(self)
        if idx > 0:
            w = editAttrsWidget.insertCustomWidget(self.template, idx-1)
            w.templateWidget.setJsonData(self.templateWidget.getJsonData())
            w.nameWidget.setText(self.nameWidget.text())
            self.deleteLater()

class EditAttributesWidget(QWidget):
    def __init__(self, module, category, nameChangedCallback, **kwargs):
        super(EditAttributesWidget, self).__init__(**kwargs)

        self.module = module
        self.category = category
        self.nameChangedCallback = nameChangedCallback

        self.setContextMenuPolicy(Qt.DefaultContextMenu)

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

        addAction = QAction("Add", self)
        addAction.triggered.connect(self.addTemplateAttribute)
        menu.addAction(addAction)

        addAction = QAction("Copy visible", self)
        addAction.triggered.connect(self.copyVisibleAttributes)
        menu.addAction(addAction)

        if EditTemplateWidget.Clipboard:
            addAction = QAction("Paste", self)
            addAction.triggered.connect(self.pasteAttribute)
            menu.addAction(addAction)

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
        selector = TemplateSelectorDialog(parent=QApplication.activeWindow())
        selector.exec_()
        if selector.selectedTemplate:
            self.insertCustomWidget(selector.selectedTemplate)

    def insertCustomWidget(self, template, row=None):
        if not TemplateWidgets.get(template):
            return

        row = self.attributesLayout.count() if row is None else row
        w = EditTemplateWidget("attr%d"%(row+1), template)
        w.templateWidget.setJsonData(w.templateWidget.getDefaultData())
        w.nameChangedCallback = self.nameChangedCallback
        self.attributesLayout.insertWidget(row, w)
        return w

class EditAttributesTabWidget(QTabWidget):
    def __init__(self, module, currentIndex=0, **kwargs):
        super(EditAttributesTabWidget, self).__init__(**kwargs)

        self.module = module
        self.tempRunCode = module.runCode

        self.setContextMenuPolicy(Qt.DefaultContextMenu)

        self.setTabBar(QTabBar())
        self.setMovable(True)
        self.setTabsClosable(True)        
        self.tabBar().mouseDoubleClickEvent = self.tabBarMouseDoubleClickEvent
        self.tabCloseRequested.connect(self._tabCloseRequested)        

        tabs = {}
        order = 0
        for a in self.module.getAttributes():
            if a.category not in tabs:
                tabs[a.category] = {"order":order, "attributes":[]}
                order += 1

            tabs[a.category]["attributes"].append(a)

        for t in sorted(tabs, key=lambda item: tabs[item]["order"]):
            self.addTabCategory(t)

        if self.count() == 0:
            self.addTabCategory("General")

        self.setCurrentIndex(currentIndex)     

    def addTabCategory(self, category):
        scrollArea = QScrollArea()
        scrollArea.setWidget(EditAttributesWidget(self.module, category, self.nameChangedCallback))
        scrollArea.setWidgetResizable(True)
        self.addTab(scrollArea, category)
        self.setCurrentIndex(self.count()-1)

    def nameChangedCallback(self, oldName, newName):
        if oldName.strip():
            pairs = [("@\\b%s\\b"%oldName, "@"+newName),
                     ("@\\bset_%s\\b"%oldName, "@set_"+newName),
                     ("@\\b%s_data\\b"%oldName, "@"+newName+"_data")]

            self.tempRunCode = replacePairs(pairs, self.tempRunCode)

    def tabBarMouseDoubleClickEvent(self, event):
        QTabBar.mouseDoubleClickEvent(self, event)        

        idx = self.currentIndex()
        newName, ok = QInputDialog.getText(self, "Rename", "New name", QLineEdit.Normal, self.tabText(idx))
        if ok:
            self.setTabText(idx, newName)

    def _tabCloseRequested(self, i):
        ok = QMessageBox.question(self, "Rig Builder", "Remove '%s' tab?"%self.tabText(i), 
                                  QMessageBox.Yes and QMessageBox.No, QMessageBox.Yes) == QMessageBox.Yes
        if ok:
            self.setCurrentIndex(i-1)
            self.clearTab(i)

    def contextMenuEvent(self, event):
        menu = QMenu(self)

        addAction = QAction("New tab", self)
        addAction.triggered.connect(lambda: self.addTabCategory("Untitled"))
        menu.addAction(addAction)

        menu.popup(event.globalPos())

    def clearTab(self, i):
        self.widget(i).deleteLater()
        self.removeTab(i)

    def clearTabs(self):
        for i in range(self.count()):
            self.clearTab(0)

        self.clear()

class EditAttributesDialog(QDialog):
    def __init__(self, module, currentIndex=0, **kwargs):
        super(EditAttributesDialog, self).__init__(**kwargs)

        self.module = module

        self.setWindowTitle("Edit Attributes - " + self.module.name)
        self.setGeometry(600, 300, 600, 600)

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

    def saveAttributes(self):
        tabw = self.tabWidget

        self.module.clearAttributes()

        for i in range(tabw.count()):
            attrsLayout = tabw.widget(i).widget().attributesLayout # tab/scrollArea/EditAttributesWidget

            for k in range(attrsLayout.count()):
                a = Attribute("")
                w = attrsLayout.itemAt(k).widget()
                a.name = w.nameWidget.text()
                a.data = w.templateWidget.getJsonData()
                a.template = w.template
                a.category = tabw.tabText(i)
                a.connect = w.connectedTo
                self.module.addAttribute(a)

        self.module.runCode = self.tabWidget.tempRunCode
        self.accept()

class CodeEditorWidget(CodeEditorWithNumbersWidget):
    def __init__(self, module=None, **kwargs):
        super(CodeEditorWidget, self).__init__(**kwargs)

        self.module = module

        self.editorWidget.formatFunction = lambda text: formatPython(text.replace("@", "__ATTR__")).replace("__ATTR__", "@")

        self.editorWidget.syntax = PythonHighlighter(self.editorWidget.document())
        self.editorWidget.textChanged.connect(self.codeChanged)

        self.update()

    def codeChanged(self):
        if not self.module:
            return

        self.module.runCode = self.editorWidget.toPlainText()

    def update(self):
        if not self.module:
            return

        self.editorWidget.setTextSafe(self.module.runCode)
        self.editorWidget.document().clearUndoRedoStacks()
        self.generateCompletionWords()

        self.editorWidget.preset = self.module
        self.editorWidget.loadState()

    def generateCompletionWords(self):
        if not self.module:
            return

        words = ["SHOULD_RUN_CHILDREN", "MODULE_NAME", "MODULE_TYPE", "SELF", "Channel", "copyJson", "error", "warning", "evaluateBezierCurve", "evaluateBezierCurveFromX",
                 "beginProgress", "stepProgress", "endProgress", "currentTabIndex", "getMultiData", "getCompoundData"]

        prefix = "@"
        for a in self.module.getAttributes():
            words.append(prefix + a.name)
            words.append(prefix + a.name + "_data")
            words.append(prefix + "set_"+a.name)

        self.editorWidget.words = set(words)

class LogHighligher(QSyntaxHighlighter):
    def __init__(self, parent=None):
        super(LogHighligher, self).__init__(parent)

        self.highlightingRules = []

        warningFormat = QTextCharFormat()
        warningFormat.setForeground(QColor(250, 150, 90))
        warningRegexp = QRegExp("\\bwarning\\b")
        warningRegexp.setCaseSensitivity(Qt.CaseInsensitive)
        self.highlightingRules.append((warningRegexp, warningFormat))

        errorFormat = QTextCharFormat()
        errorFormat.setForeground(QColor(250, 90, 90))
        errorRegexp = QRegExp("\\berror\\b")
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
        self.setHandleWidth(7)        

    def createHandle(self):
        return WideSplitterHandle(self.orientation(), self)

class MyProgressBar(QWidget):
    LabelSize = 25
    def __init__(self, **kwargs):
        super(MyProgressBar, self).__init__(**kwargs)

        self.queue = []

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
        self.labelWidget.setText(trimText(state["text"], MyProgressBar.LabelSize))
        self.progressBarWidget.setValue(state["value"])
        self.progressBarWidget.setMaximum(state["max"])

    def beginProgress(self, text, count, updatePercent=0):
        q = {"text": text, "max": count, "value": 0, "updatePercent":updatePercent}
        self.queue.append(q)
        self.updateWithState(q)
        self.show()

    def stepProgress(self, value, text=None):
        q = self.queue[-1]
        q["value"] = value

        updateValue = int(clamp(1, q["max"], q["max"] * q["updatePercent"]))

        if not q["updatePercent"] or value % updateValue == 0:
            if text:
                q["text"] = text
                self.labelWidget.setText(trimText(text, MyProgressBar.LabelSize))

            self.progressBarWidget.setMaximum(q["max"])
            self.progressBarWidget.setValue(value)
            QApplication.processEvents()

    def endProgress(self):
        self.queue.pop()
        if not self.queue:
            self.hide()
        else:
            q = self.queue[-1] # get latest state
            self.updateWithState(q)

def getChildrenCount(item):
    count = 0
    for i in range(item.childCount()):
        count += 1
        count += getChildrenCount(item.child(i))

    return count

class RigBuilderMainWindow(QFrame):
    def __init__(self, **kwargs):
        super(RigBuilderMainWindow, self).__init__(**kwargs)

        self.setWindowTitle("Rig Builder")
        self.setGeometry(400, 200, 1300, 700)

        self.setWindowFlags(self.windowFlags() | Qt.Window)

        layout = QVBoxLayout()
        self.setLayout(layout)

        self.logWidget = LogWidget()
        self.attributesWidget = AttributesWidget(mainWindow=self)
        self.treeWidget = TreeWidget(mainWindow=self)
        self.codeEditorWidget = CodeEditorWidget()

        runBtn = QPushButton(u"  Run!  ")
        runBtn.setStyleSheet("background-color: #224267")
        runBtn.clicked.connect(self.runBtnClicked)

        toolsLayout = QHBoxLayout()
        toolsLayout.addWidget(runBtn)

        attrsToolsWidget = QWidget()
        attrsToolsWidget.setLayout(QVBoxLayout())
        attrsToolsWidget.layout().addWidget(self.attributesWidget)
        attrsToolsWidget.layout().addLayout(toolsLayout)

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

        layout.addWidget(self.vsplitter)
        layout.addWidget(self.progressBarWidget)

        setStylesheet(self)

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
            self.codeEditorWidget.update()
            self.codeEditorWidget.setEnabled(True)

    def showLog(self):
        sizes = self.vsplitter.sizes()
        if sizes[-1] < 10:
            sizes[-1] = 200
            self.vsplitter.setSizes(sizes)

    def getModuleGlobalEnv(self):
        return {"evaluateBezierCurveFromX": widgets.evaluateBezierCurveFromX, 
                "evaluateBezierCurve": widgets.evaluateBezierCurve,
                "getMultiData": lambda data, idx: data["items"][idx],
                "getCompoundData": lambda data, idx: data["layout"]["items"][idx],
                "beginProgress": self.progressBarWidget.beginProgress,
                "stepProgress": self.progressBarWidget.stepProgress,
                "endProgress": self.progressBarWidget.endProgress,
                "currentTabIndex": self.attributesWidget.tabWidget.currentIndex(),
                "GLOBALS":ScriptGlobals}        

    def runBtnClicked(self):
        def uiCallback(mod):
            self.progressBarWidget.stepProgress(self.progressCounter, mod.getPath())
            self.progressCounter += 1

        if not self.treeWidget.selectedItems():
            return

        self.setFocus()

        self.logWidget.clear()
        self.showLog()

        if IsMayaAvailable:
            cmds.undoInfo(ock=True) # open undo block

        with captureOutput(self.logWidget):
            startTime = time.time()
            timeStr = time.strftime("%H:%M", time.localtime(startTime))
            print("Start running at " + timeStr)

            self.progressBarWidget.initialize()
            self.progressCounter = 0

            try:            
                for item in self.treeWidget.selectedItems():
                    count = getChildrenCount(item)
                    self.progressBarWidget.beginProgress(item.module.name, count+1)

                    muted = item.module.muted

                    item.module.muted = False
                    item.module.run(self.getModuleGlobalEnv(), uiCallback)
                    item.module.muted = muted

            except Exception as ex:            
                traceback.print_exc(file=sys.stdout)
            finally:
                print("Done in %.2fs"%(time.time() - startTime))

                if IsMayaAvailable:
                    cmds.undoInfo(cck=True) # close undo block

        self.progressBarWidget.endProgress()
        self.attributesWidget.update()

class RigBuilderToolWindow(QFrame):
    def __init__(self, modulePath, **kwargs):
        super(RigBuilderToolWindow, self).__init__(**kwargs)

        self.module = Module.loadFromFile(modulePath)
        self.module.update()

        self.setWindowTitle("Rig Builder Tool - "+os.path.basename(modulePath))
        self.setGeometry(kwargs.get("x",600), kwargs.get("y",200), kwargs.get("width",700), kwargs.get("height",500))

        self.setWindowFlags(self.windowFlags() | Qt.Window | Qt.Tool)

        layout = QVBoxLayout()
        self.setLayout(layout)

        self.vsplitter = WideSplitter(Qt.Vertical)

        self.logWidget = LogWidget()
        self.attributesWidget = AttributesWidget(self.module, mainWindow=self)        
        self.codeEditorWidget = CodeEditorWidget(None)
        self.codeEditorWidget.hide()

        runBtn = QPushButton(u"  Run!  ")
        runBtn.setStyleSheet("background-color: #224267")
        runBtn.clicked.connect(self.runBtnClicked)

        self.progressBarWidget = MyProgressBar()
        self.progressBarWidget.hide()

        self.vsplitter.addWidget(self.attributesWidget)
        self.vsplitter.addWidget(self.logWidget)

        self.vsplitter.setSizes([500, 0])

        layout.addWidget(self.vsplitter)
        layout.addWidget(runBtn)
        layout.addWidget(self.progressBarWidget)

        setStylesheet(self)

    def setStayOnTop(self, v):
        if v:
            self.setWindowFlags(self.windowFlags() | Qt.WindowStaysOnTopHint)        
        else:
            self.setWindowFlags(self.windowFlags() & ~Qt.WindowStaysOnTopHint)
        self.show()

    def showLog(self):
        sizes = self.vsplitter.sizes()
        if sizes[-1] < 10:
            sizes[-1] = 200
            self.vsplitter.setSizes(sizes)        

    def getModuleGlobalEnv(self):
        return {"evaluateBezierCurveFromX": widgets.evaluateBezierCurveFromX, 
                "evaluateBezierCurve": widgets.evaluateBezierCurve,
                "getMultiData": lambda data, idx: data["items"][idx],
                "getCompoundData": lambda data, idx: data["layout"]["items"][idx],
                "beginProgress": self.progressBarWidget.beginProgress,
                "stepProgress": self.progressBarWidget.stepProgress,
                "endProgress": self.progressBarWidget.endProgress,
                "currentTabIndex": self.attributesWidget.tabWidget.currentIndex(),
                "GLOBALS":ScriptGlobals}  

    def runBtnClicked(self):
        def uiCallback(mod):
            pass

        self.setFocus()

        self.logWidget.clear()
        self.showLog()

        if IsMayaAvailable:
            cmds.undoInfo(ock=True) # open undo block

        with captureOutput(self.logWidget):
            startTime = time.time()
            timeStr = time.strftime("%H:%M", time.localtime(startTime))
            print("Start running at " + timeStr)

            self.progressBarWidget.initialize()

            try:            
                self.module.run(self.getModuleGlobalEnv(), uiCallback)

            except Exception as ex:            
                traceback.print_exc(file=sys.stdout)
            finally:
                print("Done in %.2fs"%(time.time() - startTime))

                if IsMayaAvailable:
                    cmds.undoInfo(cck=True) # close undo block

        self.attributesWidget.update()

def RigBuilderTool(path, **kwargs):
    modulePath = os.path.dirname(__file__.decode(sys.getfilesystemencoding())) + "/modules"
    if os.path.exists(path):
        realPath = path
    elif os.path.exists(modulePath+"/"+path):
        realPath = modulePath+"/"+path
    else:
        print("Cannot find '%s'"%path)
        return

    return RigBuilderToolWindow(realPath, parent=mayaMainWindow if IsMayaAvailable else None, **kwargs)

def setStylesheet(w):
    folder = os.path.dirname(__file__.decode(sys.getfilesystemencoding()))
    with open(folder+"/qss/qstyle.qss", "r") as f:
        iconsDir = (folder+"/qss/icons/").replace("\\","/")
        style = f.read().replace("icons/", iconsDir)
        w.setStyleSheet(style)

if not os.path.exists(RigBuilderLocalPath):
    os.makedirs(RigBuilderLocalPath+"/modules")

if __name__ == '__main__':
    app = QApplication([]) 
    mainWindow = RigBuilderMainWindow()    
    mainWindow.show()
    #RigBuilderTool("Tools/ExportBindPose.xml").show()
    app.exec_()
else:
    mainWindow = RigBuilderMainWindow(parent=mayaMainWindow if IsMayaAvailable else None)
