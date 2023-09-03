import time
import json
import re
import os
import sys
from contextlib import contextmanager

from PySide2.QtGui import *
from PySide2.QtCore import *
from PySide2.QtWidgets import *

from .classes import *
from .editor import *
from . import widgets

import maya.cmds as cmds
import pymel.api as api

from shiboken2 import wrapInstance
mayaMainWindow = wrapInstance(int(api.MQtUtil.mainWindow()), QMainWindow)

def clamp(mn, mx, val):
    if val < mn:
        return mn
    elif val > mx:
        return mx
    else:
        return val

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

def printErrorStack():
    exc_type, exc_value, exc_traceback = sys.exc_info()
    
    tbs = []
    tb = exc_traceback
    while tb:            
        tbs.append(tb)
        tb = tb.tb_next

    skip = True
    indent = "  "
    for tb in tbs:
        if tb.tb_frame.f_code.co_filename == "<string>":
            skip = False

        if not skip: 
            print("{}{}, {}, in line {},".format(indent, tb.tb_frame.f_code.co_filename, tb.tb_frame.f_code.co_name, tb.tb_lineno))
            indent += "  "
    print("Error: {}".format(exc_value))

def centerWindow(window):
    screen = QDesktopWidget().screenGeometry()
    cp = screen.center()
    geom = window.frameGeometry()
    geom.moveCenter(cp)
    window.move(geom.topLeft())

def widgetOnChange(widget, module, attr):
    data = widget.getJsonData()

    if attr.connect:
        srcAttr = module.findConnectionSourceForAttribute(attr)
        srcAttr.data = data

    else:
        attr.data = data

    #print attr.name, "=", attr.data

class TabAttributesWidget(QWidget):
    needUpdateUI = Signal()

    def __init__(self, module, attributes, **kwargs):
        super(TabAttributesWidget, self).__init__(**kwargs)

        self.module = module

        layout = QGridLayout()
        layout.setDefaultPositioning(2, Qt.Horizontal)
        layout.setColumnStretch(1, 1)
        self.setLayout(layout)

        if self.module:
            with captureOutput(rigBuilderWindow.logWidget):
                try:
                    self.module.resolveConnections()
                except AttributeResolverError as err:
                    print("Error: " + str(err))
                    rigBuilderWindow.showLog()
                    rigBuilderWindow.logWidget.ensureCursorVisible()

        for i, a in enumerate(attributes):
            templateWidget = widgets.TemplateWidgets[a.template](env={"module": ModuleWrapper(self.module)})
            templateWidget.setJsonData(a.data)
            templateWidget.somethingChanged.connect(lambda w=templateWidget, e=module, a=a: widgetOnChange(w, e, a))
            templateWidget.needUpdateUI.connect(self.needUpdateUI.emit)

            nameWidget = QLabel(a.name)
            nameWidget.setAlignment(Qt.AlignRight)
            nameWidget.setStyleSheet("QLabel:hover:!pressed{ background-color: #666666; }")            

            if a.connect:
                templateWidget.setToolTip("Connect: %s"%a.connect)
                templateWidget.setStyleSheet("background-color: #6e6e39")

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
            with captureOutput(rigBuilderWindow.logWidget):
                try:
                    data = json.loads(editText.outputText)
                    tmp = widgets.TemplateWidgets[attr.template]() # also we need check for widget compatibility
                    tmp.setJsonData(data)

                except:
                    print("Error: invalid or incompatible json data")
                    rigBuilderWindow.showLog()
                    rigBuilderWindow.logWidget.ensureCursorVisible()

                else:
                    attr.data = data
                    rigBuilderWindow.attributesTabWidget.updateTabs()

    def resetAttr(self, attr):
        tmp = widgets.TemplateWidgets[attr.template]()
        attr.data = tmp.getDefaultData()
        attr.connect = ""
        rigBuilderWindow.attributesTabWidget.updateTabs()

    def disconnectAttr(self, attr):
        attr.connect = ""
        rigBuilderWindow.attributesTabWidget.updateTabs()

    def connectAttr(self, connect, destAttr):
        destAttr.connect = connect
        rigBuilderWindow.attributesTabWidget.updateTabs()

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
    def __init__(self, module=None, **kwargs):
        super(AttributesTabWidget, self).__init__(**kwargs)

        self.module = module
        self.tabsAttributes = {}

        self.searchAndReplaceDialog = SearchReplaceDialog(["In all tabs"])
        self.searchAndReplaceDialog.onReplace.connect(self.onReplace)

        self.currentChanged.connect(self.tabChanged)
        self.updateTabs()

    def contextMenuEvent(self, event):
        menu = QMenu(self)

        if self.module:
            editAttrsAction = QAction("Edit attributes", self)
            editAttrsAction.triggered.connect(lambda _=None: self.editAttributes())
            menu.addAction(editAttrsAction)

            menu.addSeparator()

            replaceInValuesAction = QAction("Replace in values", self)
            replaceInValuesAction.triggered.connect(self.searchAndReplaceDialog.exec_)
            menu.addAction(replaceInValuesAction)

        menu.popup(event.globalPos())

    def editAttributes(self):
        dialog = EditAttributesDialog(self.module, self.currentIndex(), parent=QApplication.activeWindow())
        dialog.exec_()

        rigBuilderWindow.codeEditorWidget.update()
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
            valueKey = attr.data.get("default")
            if valueKey:
                attr.data[valueKey] = replaceStringInData(attr.data[valueKey], old, new)

        self.updateTabs() 

    def tabChanged(self, idx):
        if self.count() == 0:
            return

        idx = clamp(0, self.count()-1, idx)

        title = self.tabText(idx)
        scrollArea = self.widget(idx)
        w = TabAttributesWidget(self.module, self.tabsAttributes[title])
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

        mask = re.escape(self.maskWidget.text())

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
    def __init__(self, **kwargs):
        super(TreeWidget, self).__init__(**kwargs)

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
            painter.fillRect(rect.x()-1, rect.y(), painter.viewport().width(), rect.height(), QColor(80, 96, 154, 60))
            painter.setPen(QColor(73, 146, 158, 200))
            painter.drawRect(rect.x()-1, rect.y()+1, painter.viewport().width(), rect.height()-3)

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
            links = []
            for url in event.mimeData().urls():
                path = url.toLocalFile()

                with captureOutput(rigBuilderWindow.logWidget):
                    try:
                        m = Module.loadFromFile(path)
                        m.update()
                        self.addTopLevelItem(self.makeItemFromModule(m))

                    except ET.ParseError as e:
                        print(e)
                        print("Error '%s': invalid module"%path)
                        rigBuilderWindow.showLog()
                        rigBuilderWindow.logWidget.ensureCursorVisible()

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
        if column == 0: # name
            newName, ok = QInputDialog.getText(self, "Rig Builder", "New name", QLineEdit.Normal, item.module.name)
            if ok and newName:
                newName = replaceSpecialChars(newName).strip()
                item.module.name = newName
                item.setText(0, item.module.name + " ")        
            item.setExpanded(not item.isExpanded()) # revert expand on double click

    def makeItemFromModule(self, module):
        item = QTreeWidgetItem([module.name+" ", module.getRelativeLoadedPathString()+" ", " ", module.uid])
        item.setFlags(Qt.ItemIsSelectable | Qt.ItemIsEnabled | Qt.ItemIsDragEnabled | Qt.ItemIsDropEnabled)
        item.module = module
        item.module.modified = False

        for ch in module.getChildren():
            item.addChild(self.makeItemFromModule(ch))

        return item

    def keyPressEvent(self, event):
        shift = event.modifiers() & Qt.ShiftModifier
        ctrl = event.modifiers() & Qt.ControlModifier
        alt = event.modifiers() & Qt.AltModifier
        key = event.key()

        if key == Qt.Key_Insert:
            self.insertModule()

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
        newAction.triggered.connect(self.insertModule)
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

    def insertModule(self):
        item = self.makeItemFromModule(Module("module"))

        sel = self.selectedItems()
        if sel:
            sel[0].addChild(item)
            sel[0].module.addChild(item.module)
        else:
            self.addTopLevelItem(item)

    def importModule(self):
        defaultPath = RigBuilderLocalPath+"/modules/"

        sceneDir = os.path.dirname(api.MFileIO.currentFile())
        if sceneDir:
            defaultPath = sceneDir + "/"

        path, _ = QFileDialog.getOpenFileName(rigBuilderWindow, "Import", defaultPath, "*.xml")

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
            rigBuilderWindow.showLog()
            rigBuilderWindow.logWidget.ensureCursorVisible()

    def saveModule(self):
        def clearModifiedFlag(module): # clear modified flag on embeded modules
            module.modified = False      
            for ch in module.getChildren():
                if not ch.uid:
                    clearModifiedFlag(ch)

        msg = "\n".join(["%s -> %s"%(item.module.name, item.module.getSavePath() or "N/A") for item in self.selectedItems()])

        if QMessageBox.question(self, "Rig Builder", "Save modules?\n%s"%msg, QMessageBox.Yes and QMessageBox.No, QMessageBox.Yes) == QMessageBox.Yes:
            for item in self.selectedItems():
                outputPath = item.module.getSavePath()

                if not outputPath:
                    outputPath, _ = QFileDialog.getSaveFileName(rigBuilderWindow, "Save "+item.module.name, RigBuilderLocalPath+"/modules/"+item.module.name, "*.xml")

                if outputPath:
                    dirname = os.path.dirname(outputPath)
                    if not os.path.exists(dirname):
                        os.makedirs(dirname)

                    item.module.saveToFile(outputPath)
                    clearModifiedFlag(item.module)

                item.setText(1, item.module.getRelativeLoadedPathString()+" ") # update path string

    def saveAsModule(self):
        for item in self.selectedItems():
            outputDir = os.path.dirname(api.MFileIO.currentFile())
            outputPath, _ = QFileDialog.getSaveFileName(rigBuilderWindow, "Save as "+item.module.name, outputDir + "/" +item.module.name, "*.xml")

            if outputPath:
                item.module.uid = generateUid()
                item.module.saveToFile(outputPath)
                item.setText(1, item.module.getRelativeLoadedPathString()+" ") # update path string

    def embedModule(self):
        if QMessageBox.question(self, "Rig Builder", "Embed modules?", QMessageBox.Yes and QMessageBox.No, QMessageBox.Yes) == QMessageBox.Yes:
            for item in self.selectedItems():
                item.module.uid = ""
                item.module.loadedFrom = ""
                
                for i in range(1,4): # clear path, source and uid
                    item.setText(i, "") # update path string

    def locateModuleFile(self):
        for item in self.selectedItems():
            if item and os.path.exists(item.module.loadedFrom):
                os.system("explorer /select,%s"%os.path.realpath(item.module.loadedFrom).encode(sys.getfilesystemencoding()))

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
        self.setGeometry(600, 300, 550, 500)

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
        self.nameWidget.setFixedWidth(150)
        self.nameWidget.setAlignment(Qt.AlignRight)
        self.nameWidget.mouseDoubleClickEvent = self.nameMouseDoubleClickEvent
        self.nameWidget.contextMenuEvent = self.nameContextMenuEvent
        self.nameWidget.setStyleSheet("QLabel:hover:!pressed{ background-color: #666666; }")

        self.templateWidget = widgets.TemplateWidgets[template]()

        buttonsLayout = QHBoxLayout()
        buttonsLayout.setContentsMargins(0,0,0,0)
        upBtn = QPushButton("up")
        upBtn.setFixedSize(35, 25)
        upBtn.clicked.connect(self.upBtnClicked)

        downBtn = QPushButton("down")
        downBtn.setFixedSize(35, 25)
        downBtn.clicked.connect(self.downBtnClicked)

        removeBtn = QPushButton("x")
        removeBtn.setFixedSize(35, 25)
        removeBtn.clicked.connect(self.removeBtnClicked)

        buttonsLayout.addWidget(upBtn)
        buttonsLayout.addWidget(downBtn)
        buttonsLayout.addWidget(removeBtn)

        layout.addWidget(self.nameWidget)
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
        newName, ok = QInputDialog.getText(self, "Rig Builder", "New name", QLineEdit.Normal, oldName)
        if ok:
            newName = replaceSpecialChars(newName)
            self.nameWidget.setText(newName)
            self.nameChanged.emit(oldName, newName)

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
        if not widgets.TemplateWidgets.get(template):
            return

        row = self.attributesLayout.count() if row is None else row
        w = EditTemplateWidget("attr%d"%(row+1), template)
        w.templateWidget.setJsonData(w.templateWidget.getDefaultData())
        w.nameChanged.connect(self.nameChanged.emit)
        self.attributesLayout.insertWidget(row, w)
        return w

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

    def tabBarMouseDoubleClickEvent(self, event):
        super(EditAttributesTabWidget, self).mouseDoubleClickEvent(event)

        idx = self.currentIndex()
        newName, ok = QInputDialog.getText(self, "Rig Builder", "New name", QLineEdit.Normal, self.tabText(idx))
        if ok:
            self.setTabText(idx, newName)

    def tabCloseRequest(self, i):
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
    def __init__(self, module=None, **kwargs):
        super(CodeEditorWidget, self).__init__(**kwargs)

        self.module = module

        self.editorWidget.syntax = PythonHighlighter(self.editorWidget.document())
        self.editorWidget.textChanged.connect(self.codeChanged)

        self.update()

    def codeChanged(self):
        if not self.module:
            return

        self.module.runCode = self.editorWidget.toPlainText()
        self.module.modified = True

    def update(self):
        if not self.module:
            return

        self.editorWidget.setTextSafe(self.module.runCode)
        self.editorWidget.document().clearUndoRedoStacks()
        self.generateCompletionWords()

        self.editorWidget.preset = id(self.module)
        self.editorWidget.loadState()

    def generateCompletionWords(self):
        if not self.module:
            return

        words = ["SHOULD_RUN_CHILDREN", "MODULE_NAME", "Module", "Channel", "copyJson", 
                 "error", "warning", "evaluateBezierCurve", "evaluateBezierCurveFromX",
                 "beginProgress", "stepProgress", "endProgress", "currentTabIndex"]

        prefix = "@"
        for a in self.module.getAttributes():
            words.append(prefix + a.name)
            words.append(prefix + "set_"+a.name)

        self.editorWidget.words = set(words)

class LogHighligher(QSyntaxHighlighter):
    def __init__(self, parent=None):
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

    def beginProgress(self, text, count, updatePercent=0.01):
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

class RigBuilderWindow(QFrame):
    def __init__(self):
        super(RigBuilderWindow, self).__init__(parent=mayaMainWindow)

        self.setWindowTitle("Rig Builder")
        self.setGeometry(400, 200, 1300, 700)

        self.setWindowFlags(self.windowFlags() | Qt.Window)

        layout = QVBoxLayout()
        self.setLayout(layout)

        self.logWidget = LogWidget()
        self.attributesTabWidget = AttributesTabWidget()
        self.treeWidget = TreeWidget()
        self.treeWidget.itemSelectionChanged.connect(self.treeItemSelectionChanged)

        self.codeEditorWidget = CodeEditorWidget()

        runBtn = QPushButton("Run!")
        runBtn.setStyleSheet("background-color: #3e4f89")
        runBtn.clicked.connect(self.runBtnClicked)

        attrsToolsWidget = QWidget()
        attrsToolsWidget.setLayout(QVBoxLayout())
        attrsToolsWidget.layout().addWidget(self.attributesTabWidget)
        attrsToolsWidget.layout().addWidget(runBtn)

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

    def treeItemSelectionChanged(self):
        selected = self.treeWidget.selectedItems()
        en = True if selected else False
        self.attributesTabWidget.setEnabled(en)
        self.codeEditorWidget.setEnabled(en and not self.isCodeEditorHidden())

        if selected:
            item = selected[0]

            self.attributesTabWidget.module = item.module
            self.attributesTabWidget.updateTabs()

            if self.codeEditorWidget.isEnabled():
                self.codeEditorWidget.module = item.module
                self.codeEditorWidget.update()

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
                "beginProgress": self.progressBarWidget.beginProgress,
                "stepProgress": self.progressBarWidget.stepProgress,
                "endProgress": self.progressBarWidget.endProgress,
                "currentTabIndex": self.attributesTabWidget.currentIndex()}

    def runBtnClicked(self):
        def uiCallback(mod):
            self.progressBarWidget.stepProgress(self.progressCounter, mod.getPath())
            self.progressCounter += 1

        if not self.treeWidget.selectedItems():
            return

        self.setFocus()

        self.logWidget.clear()
        self.showLog()

        with captureOutput(self.logWidget):
            startTime = time.time()
            timeStr = time.strftime("%H:%M", time.localtime(startTime))
            print("Start running at " + timeStr)

            self.progressBarWidget.initialize()
            self.progressCounter = 0

            cmds.undoInfo(ock=True) # open undo block
            try:
                for item in self.treeWidget.selectedItems():
                    count = getChildrenCount(item)
                    self.progressBarWidget.beginProgress(item.module.name, count+1)

                    muted = item.module.muted

                    item.module.muted = False
                    item.module.run(self.getModuleGlobalEnv(), uiCallback)
                    item.module.muted = muted

            except Exception:
                printErrorStack()

            finally:
                print("Done in %.2fs"%(time.time() - startTime))
                cmds.undoInfo(cck=True) # close undo block

        self.progressBarWidget.endProgress()
        self.attributesTabWidget.updateTabs()

class RigBuilderToolWindow(QFrame):
    def __init__(self, module):
        super(RigBuilderToolWindow, self).__init__(parent=mayaMainWindow)

        self.module = module

        self.setWindowFlags(self.windowFlags() | Qt.Window)
        self.setWindowFlags(self.windowFlags() & ~Qt.WindowMinimizeButtonHint & ~Qt.WindowMaximizeButtonHint)

        layout = QVBoxLayout()
        self.setLayout(layout)        

        self.logWidget = LogWidget()
        self.logWidget.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Ignored)
        self.logWidget.hide()

        self.attributesTabWidget = AttributesTabWidget(self.module)
        self.codeEditorWidget = CodeEditorWidget(None)
        self.codeEditorWidget.hide()

        runBtn = QPushButton("Run!")
        runBtn.setStyleSheet("background-color: #3e4f89")
        runBtn.clicked.connect(self.runBtnClicked)

        self.progressBarWidget = MyProgressBar()
        self.progressBarWidget.hide()

        self.vsplitter = WideSplitter(Qt.Vertical)
        self.vsplitter.addWidget(self.attributesTabWidget)
        self.vsplitter.addWidget(self.logWidget) # log is hidden by default

        layout.addWidget(self.vsplitter)
        layout.addWidget(runBtn)
        layout.addWidget(self.progressBarWidget)

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
                "beginProgress": self.progressBarWidget.beginProgress,
                "stepProgress": self.progressBarWidget.stepProgress,
                "endProgress": self.progressBarWidget.endProgress,
                "currentTabIndex": self.attributesTabWidget.currentIndex()}

    def runBtnClicked(self):
        def uiCallback(mod):
            pass

        self.setFocus()

        self.logWidget.show()
        self.logWidget.clear()
        self.showLog()

        with captureOutput(self.logWidget):
            startTime = time.time()
            timeStr = time.strftime("%H:%M", time.localtime(startTime))
            print("Start running at " + timeStr)

            self.progressBarWidget.initialize()

            cmds.undoInfo(ock=True) # open undo block
            try:
                self.module.run(self.getModuleGlobalEnv(), uiCallback)
            except Exception as ex:
                printErrorStack()
            finally:
                print("Done in %.2fs"%(time.time() - startTime))
                cmds.undoInfo(cck=True) # close undo block

        self.attributesTabWidget.updateTabs()

def RigBuilderTool(spec, child=None, **kwargs): # spec can be full path, relative path, uid
    module = Module.loadModule(spec)
    if not module:
        cmds.warning("Cannot load '{}' module".format(spec))
        return

    if child:
        module = module.findChild(child)
        if not module:
            cmds.warning("Cannot find '{}' child".format(child))
            return

    w = RigBuilderToolWindow(module)
    w.setWindowTitle("Rig Builder Tool - {}".format(module.getPath()))
    w.adjustSize()
    centerWindow(w)
    return w

if not os.path.exists(RigBuilderLocalPath):
    os.makedirs(RigBuilderLocalPath+"/modules")

rigBuilderWindow = RigBuilderWindow()
