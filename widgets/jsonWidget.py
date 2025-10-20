from PySide6.QtCore import *
from PySide6.QtGui import *
from PySide6.QtWidgets import *
import json
import re
import os

from ..utils import clamp, findUniqueName, SimpleUndo
from ..ui_utils import getActions, centerWindow, setActionsLocalShortcut, SearchReplaceDialog, JsonColors

RootDirectory = os.path.dirname(__file__)

FloatType = 6 # QMetaType.Double

class EditJsonTextWindow(QDialog):
    saved = Signal(object)

    def __init__(self, data, *, readOnly=False, **kwargs):
        super().__init__(**kwargs)

        self.setWindowTitle("Edit JSON")
        self.setGeometry(100, 100, 600, 500)

        layout = QVBoxLayout()
        layout.setMargin(0)
        self.setLayout(layout)

        self.prettyPrintWidget = QCheckBox("Pretty print")        
        self.prettyPrintWidget.toggled.connect(self.prettyPrintToggled)

        self.textWidget = QTextEdit()
        self.textWidget.setPlainText(json.dumps(data))
        self.textWidget.setReadOnly(readOnly)
        self.textWidget.setTabStopDistance(16)
        self.textWidget.setAcceptRichText(False)
        self.textWidget.setWordWrapMode(QTextOption.NoWrap)

        btn = QPushButton("Save" if not readOnly else "Close")
        btn.clicked.connect(self.saveAndClose if not readOnly else self.accept)

        layout.addWidget(self.prettyPrintWidget)
        layout.addWidget(self.textWidget)
        layout.addWidget(btn)

        centerWindow(self)
        
        self.prettyPrintWidget.setChecked(True)

    def prettyPrintToggled(self, value):
        try:
            data = json.loads(self.textWidget.toPlainText())
            self.textWidget.setPlainText(json.dumps(data, indent=4 if value else None))
        except:
            pass

    def saveAndClose(self):
        try:
            data = json.loads(self.textWidget.toPlainText())
            self.saved.emit(data)
            self.accept()
        except:
            QMessageBox.critical(self, "DemBones Tool", "Invalid JSON")

class JsonItem(QTreeWidgetItem):
    NoneType = 0
    BoolType = 1
    IntType = 2
    FloatType = 3
    StringType = 4
    ListType = 5
    DictType = 6

    KeyRole = Qt.UserRole + 1

    def __init__(self, jsonType, data=None):
        super().__init__()

        self._editValue = data

        self.jsonType = jsonType

        self.setFlags(Qt.ItemIsEnabled | Qt.ItemIsSelectable)

        if jsonType == self.ListType:
            self.setFlags(self.flags() | Qt.ItemIsDropEnabled)

        elif jsonType in [self.BoolType, self.IntType, self.FloatType, self.StringType]:
            self.setFlags(self.flags() | Qt.ItemIsEditable)

    def clone(self):
        item = JsonItem(self.jsonType)
        item._editValue = self._editValue
        item.setText(0, self.text(0))
        item.setData(0, self.KeyRole, self.data(0, self.KeyRole))        
        for i in range(self.childCount()):
            item.addChild(self.child(i).clone())
        return item

    def setData(self, _, role, value):
        if role == Qt.EditRole:
            self._editValue = value

        super().setData(0, role, value)

    def data(self, _, role):
        if role == Qt.ForegroundRole:
            if self.jsonType == self.BoolType:
                return JsonColors["true"] if self._editValue else JsonColors["false"]
            else:
                colors = {self.NoneType: JsonColors["none"],
                          self.IntType:  JsonColors["int"],
                          self.FloatType: JsonColors["float"],
                          self.StringType: JsonColors["string"],
                          self.ListType: JsonColors["list"],
                          self.DictType: JsonColors["dict"]}

                return colors.get(self.jsonType, Qt.gray)
        
        if role == Qt.ToolTipRole:
            return str(self._editValue or "")
        
        elif role == Qt.EditRole:
            return self._editValue
            
        elif role == Qt.DisplayRole:
            key = self.data(0, self.KeyRole)

            if self.jsonType == self.ListType:
                key = key or ""
                return key + "[%d]"%self.childCount()
            
            elif self.jsonType == self.DictType:
                key = key or ""

                childCount = self.childCount()
                maxChildKeys = 10
                children = []
                for i in range(childCount):
                    if i >= maxChildKeys:
                        break
                    k = self.child(i).data(0, self.KeyRole)
                    children.append(k)
                    
                items = ",".join(children)
                suffix = "..." if childCount > maxChildKeys else ""
                return key + "{%s%s}"%(items, suffix)
            
            else:
                value = self._editValue
                if self.jsonType == self.StringType:
                    if len(value) > 25:
                        value = value[:25] + "..."
                    value = "\"{}\"".format(value)
                
                if key:
                    return key + ":" + str(value)
                else:
                    return str(value)
        else:
            return super().data(0, role)
        
    def getPath(self, path=""):
        parent = self.parent()
        if not parent:
            idx = self.treeWidget().invisibleRootItem().indexOfChild(self)
            return path + "[%d]"%idx
        
        if parent.jsonType == parent.ListType:
            idx = parent.indexOfChild(self)
            return parent.getPath(path) + "[%d]"%idx
        
        elif parent.jsonType == parent.DictType:
            key = self.data(0, self.KeyRole)
            return parent.getPath(path) + "[\"%s\"]"%key
        
        return path
    
class FloatEditor(QDoubleSpinBox):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setDecimals(6)

class FloatEditorCreator(QItemEditorCreatorBase):
    def __init__(self):
        super().__init__()

    def createWidget(self, parent):
        return FloatEditor(parent)

class JsonItemFactor(QItemEditorFactory):
    def __init__(self):
        super().__init__()
        self.registerEditor(FloatType, FloatEditorCreator())

class JsonWidget(QTreeWidget):
    itemMoved = Signal(QTreeWidgetItem)
    itemAdded = Signal(QTreeWidgetItem)
    itemRemoved = Signal(QTreeWidgetItem)
    dataLoaded = Signal()
    cleared = Signal()
    readOnlyChanged = Signal(bool)
    rootChanged = Signal(QTreeWidgetItem)

    def __init__(self, data=None, **kwargs):
        super().__init__(**kwargs)

        self._clipboard = []
        self._readOnly = False
        self._undoSystem = SimpleUndo()

        self._searchReplaceDialog = SearchReplaceDialog(["Keys"])
        self._searchReplaceDialog.onReplace.connect(self.onSearchReplace)

        self.header().hide()
        self.setDragDropMode(QAbstractItemView.InternalMove)
        self.setDragEnabled(True)
        self.setDropIndicatorShown(True)
        self.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.setIndentation(32)

        self.itemDelegate().setItemEditorFactory(JsonItemFactor())

        self.setReadOnly(self._readOnly)

        if data:
            self.loadFromJsonList(data if type(data) == list else [data])

    def getMenu(self):
        menu = QMenu(self)

        fileMenu = menu.addMenu("File")
        fileMenu.addAction("Save all", self.saveToFile)
        fileMenu.addAction("Export selected", lambda: self.saveToFile(item=self.selectedItem()))

        if not self._readOnly:
            fileMenu.addAction("Load", self.loadFromFile)
            fileMenu.addAction("Import", self.importFile)

            menu.addSeparator()
            menu.addAction("Edit JSON", self.editItemData, "Return")
            menu.addAction("Edit key", self.editKey, "Ctrl+Return")

            undoLabel = "Undo"
            if not self._undoSystem.isEmpty():
                undoLabel += " '{}'".format(self._undoSystem.getLastOperationName())
            undoAction = menu.addAction(undoLabel, self._undoSystem.undo)
            undoAction.setEnabled(not self._undoSystem.isEmpty())
            menu.addSeparator()

            addMenu = menu.addMenu("Add")
            addGroup = QActionGroup(self)
            addGroup.setExclusive(True)
            for l, d, key in [("none", None, ""), ("bool", True, "1"), ("int", 0, "2"), ("float", 0.0, "3"), ("string", "", "4"), ("list", [], "5"), ("dict", {}, "6")]:
                action = addGroup.addAction(l)
                action.setData(d)
                action.setShortcut(key)

            addGroup.triggered.connect(lambda action :self.addItem(action.data(), self.selectedItem()))
            addMenu.addActions(addGroup.actions())

            menu.addAction("Remove", self.removeItem, "Delete")

            def f():
                if QMessageBox.question(self, "Rig Builder", "Remove all items?", QMessageBox.Yes | QMessageBox.No, QMessageBox.No) == QMessageBox.Yes:
                    self.clear()
                    self.cleared.emit()
                    self._undoSystem.flush()
            menu.addAction("Clear", f)

            menu.addSeparator()            

            moveMenu = menu.addMenu("Move")
            moveMenu.addAction("Top", lambda:self.moveItem(-9999999), "Ctrl+Shift+Up")
            moveMenu.addAction("Up", lambda:self.moveItem(-1), "Shift+Up")
            moveMenu.addAction("Down", lambda:self.moveItem(1), "Shift+Down")
            moveMenu.addAction("Bottom", lambda:self.moveItem(9999999), "Ctrl+Shift+Down")

            menu.addAction("Sort", self.sortItemsChildren)
            menu.addSeparator()

            menu.addAction("Duplicate", self.duplicateItem, "Ctrl+D")

            menu.addAction("Copy", self.copyItem, "Ctrl+C")
            menu.addAction("Cut", self.cutItem, "Ctrl+X")
            menu.addAction("Paste", self.pasteItem, "Ctrl+V")
            
            menu.addAction("Replace text", self._searchReplaceDialog.exec_, "Ctrl+R")
        
        else:
            menu.addAction("View JSON", self.editItemData, "Return")

        menu.addSeparator()
        expandMenu = menu.addMenu("Expand")
        expandMenu.addAction("Toggle", lambda:self.expandItem(self.selectedItem(), recursive=False), "Space")
        expandMenu.addAction("All", lambda:self.expandItem(self.selectedItem(), True))
        expandMenu.addAction("Collapse all", lambda:self.expandItem(self.selectedItem(), False))
        expandMenu.addAction("Toggle all", lambda:self.expandItem(self.selectedItem()), "Shift+Space")

        menu.addAction("Reveal", self.revealSelected, "F")
        menu.addAction("Set as root", lambda: self.setRootItem(self.selectedItem()), "Ctrl+Space")
        menu.addAction("Reset root", self.setRootItem, "Escape")
        menu.addAction("Copy path", self.copyPath)

        menu.addSeparator()

        readOnlyItem = menu.addAction("Read only", lambda: self.setReadOnly(not self._readOnly))
        readOnlyItem.setCheckable(True)
        readOnlyItem.setChecked(self._readOnly)
        menu.addSeparator()

        return menu

    def contextMenuEvent(self, event):
        menu = self.getMenu()
        menu.popup(event.globalPos())

    def findItemsByType(self, jsonTypes, parent=None, *, recursive=True):
        items = []
        parent = parent or self.invisibleRootItem()
        for i in range(parent.childCount()):
            item = parent.child(i)
            if not jsonTypes or item.jsonType in jsonTypes:
                items.append(item)
            if recursive:
                items.extend(self.findItemsByType(jsonTypes, item, recursive=True))
        return items
    
    def copyPath(self):
        item = self.selectedItem()
        if item:
            QApplication.clipboard().setText(item.getPath())

    def onSearchReplace(self, old, new, opts):
        doReplaceKeys = opts.get("Keys")

        items = self.findItemsByType([], self.selectedItem())
        changedItems = []
        for item in items:
            if item.jsonType == item.StringType:
                value = item.data(0, Qt.EditRole)
                if old in value:
                    item.setData(0, Qt.EditRole, value.replace(old, new))
                    changedItems.append(item)

            if doReplaceKeys:
                key = item.data(0, item.KeyRole)
                if key and old in key:
                    item.setData(0, item.KeyRole, key.replace(old, new))
                    changedItems.append(item)

        # undo
        def f():
            for item in changedItems:
                if item.jsonType == item.StringType:
                    value = item.data(0, Qt.EditRole)
                    item.setData(0, Qt.EditRole, value.replace(new, old))

                if doReplaceKeys:
                    key = item.data(0, item.KeyRole)
                    item.setData(0, item.KeyRole, key.replace(new, old))

        self._undoSystem.push("ReplaceText", f)
    
    def editKey(self):
        item = self.selectedItem()
        if item:
            key = item.data(0, item.KeyRole)
            if key is not None:
                newKey, ok = QInputDialog.getText(self, "Edit key", "Key:", text=key)
                if ok:
                    existingKeys = set([item.parent().child(i).data(0, item.KeyRole) for i in range(item.parent().childCount())])
                    newKey = findUniqueName(newKey, existingKeys)
                    item.setData(0, item.KeyRole, newKey)

                    # undo
                    def f():
                        item.setData(0, item.KeyRole, key)
                    self._undoSystem.push("EditKey", f)

    def isReadOnly(self):
        return self._readOnly

    def setReadOnly(self, value):
        for a in list(self.actions()):
            self.removeAction(a)

        self._readOnly = value

        self.addActions(getActions(self.getMenu()))
        setActionsLocalShortcut(self)

        self.readOnlyChanged.emit(value)

    def selectedItem(self):
        selectedItems = self.selectedItems()
        return selectedItems[-1] if selectedItems else None

    def saveToFile(self, *, path=None, item=None):
        if not path:
            path, _ = QFileDialog.getSaveFileName(self, "Save JSON", "", "JSON (*.json)")

        if path:
            if item:
                data = self.itemToJson(item)
            else:
                data = self.toJsonList()

            with open(path, "w") as f:
                json.dump(data, f)

    def loadFromFile(self):
        path, _ = QFileDialog.getOpenFileName(self, "Load JSON", "", "JSON (*.json)")
        if path:
            self.clear()
            with open(path, "r") as f:
                d = json.load(f)
                self.loadFromJsonList([d])

    def importFile(self):
        path, _ = QFileDialog.getOpenFileName(self, "Import JSON", "", "JSON (*.json)")
        if path:
            with open(path, "r") as f:
                d = json.load(f)
                self.loadFromJsonList([d])

    def setRootItem(self, item=None):
        if item and item.jsonType in [item.ListType, item.DictType]:
            self.setRootIndex(self.indexFromItem(item))
        elif item is None:
            self.setRootIndex(QModelIndex())
        else:
            return

        self.rootChanged.emit(item)

    def setItemJson(self, item, data):
        parentItem = item.parent()

        newItem = self.itemFromJson(data)
        newItem.setData(0, newItem.KeyRole, item.data(0, item.KeyRole))
        if parentItem:
            if parentItem.jsonType == parentItem.DictType:
                newItem.setData(0, Qt.DisplayRole, item.text(0))
                newItem.setFlags(item.flags())
        else:
            parentItem = self.invisibleRootItem()

        idx = parentItem.indexOfChild(item)
        isSelected = item.isSelected()
        isExpanded = item.isExpanded()
        parentItem.insertChild(idx, newItem)
        parentItem.removeChild(item)
        newItem.setExpanded(isExpanded)
        newItem.setSelected(isSelected)
        return newItem

    def revealSelected(self):
        selectedItems = self.selectedItems()
        if selectedItems:
            self.scrollToItem(selectedItems[-1], QAbstractItemView.PositionAtCenter)

    def editItemData(self, item=None):
        def saveCallback(item, newData):
            if item:
                newItem = self.setItemJson(item, newData)
                self.itemChanged.emit(item, 0)

                # undo
                def f():
                    parent = newItem.parent() or self.invisibleRootItem()
                    idx = parent.indexOfChild(newItem)
                    parent.removeChild(newItem)
                    parent.insertChild(idx, item.clone())
                self._undoSystem.push("EditData", f)            

            else:
                if type(newData) != list:
                    newData = [newData]

                oldData = self.toJsonList()
                self.clear()
                for d in newData:
                    item = self.itemFromJson(d)
                    self.addTopLevelItem(item)
                    self.itemChanged.emit(item, 0)

                # undo
                def f():
                    self.clear()
                    for d in oldData:
                        self.addTopLevelItem(self.itemFromJson(d))
                self._undoSystem.push("EditData", f)

        item = item or self.selectedItem()
        data = self.itemToJson(item) if item else self.toJsonList()

        dlg = EditJsonTextWindow(data, readOnly=self._readOnly)
        dlg.saved.connect(lambda data: saveCallback(item, data))
        dlg.exec_()

    def moveItem(self, direction):
        selectedItems = self.selectedItems()
        sortedItems = sorted(selectedItems, key=lambda x: -direction*(x.parent() or self.invisibleRootItem()).indexOfChild(x)) # the lowest first

        # undo
        _items = [((item.parent() or self.invisibleRootItem()).indexOfChild(item), item) for item in sortedItems] # save indices
        def f():
            for idx, item in _items if direction > 0 else _items[::-1]:
                parentItem = item.parent() or self.invisibleRootItem()
                parentItem.takeChild(parentItem.indexOfChild(item)) # remove
                parentItem.insertChild(idx, item)
        self._undoSystem.push("Move", f)

        for item in sortedItems: 
            parentItem = item.parent() or self.invisibleRootItem()

            expand = item.isExpanded()
            idx = parentItem.indexOfChild(item)
            parentItem.takeChild(idx)
            parentItem.insertChild(clamp(idx+direction, 0, parentItem.childCount()), item)
            item.setSelected(True)
            item.setExpanded(expand)

            self.itemMoved.emit(item)

    def sortItemsChildren(self, items=None):
        undo_functions = []

        for item in items or self.selectedItems():
            children = [item.takeChild(0) for _ in range(item.childCount())]
            sortedChildren = sorted(children, key=lambda x: x.text(0))
            for i, child in enumerate(sortedChildren):
                item.insertChild(i, child)
            
            # undo
            def f():
                _ = [item.takeChild(0) for _ in range(item.childCount())]
                for i, child in enumerate(children):
                    item.insertChild(i, child)
            undo_functions.append(f)

        f = lambda: [f() for f in undo_functions]
        self._undoSystem.push("Sort", f)

    def duplicateItem(self):
        selectedItems = self.selectedItems()
        
        self._undoSystem.beginEditBlock("Duplicate")

        for item in selectedItems:
            data = self.itemToJson(item)
            parentItem = item.parent() or self.invisibleRootItem()
            idx = parentItem.indexOfChild(item)
            newItem = self.addItem(data, parentItem, insertIndex=idx+1 if len(selectedItems) == 1 else None)
            item.setSelected(False)

            self.itemAdded.emit(newItem)
        
        self._undoSystem.endEditBlock()        

    def copyItem(self):
        self._clipboard = []
        for item in self.selectedItems():
            self._clipboard.append(self.itemToJson(item))

    def cutItem(self):
        self.copyItem()
        self._undoSystem.beginEditBlock("Cut")
        self.removeItem()
        self._undoSystem.endEditBlock()

    def pasteItem(self):
        parentItem = self.selectedItem()
        self._undoSystem.beginEditBlock("Paste")
        for json in self._clipboard:
            self.addItem(json, parentItem)
        self._undoSystem.endEditBlock()

    def addItem(self, json, parentItem=None, *, insertIndex=None):
        if not parentItem:
            parentItem = self.itemFromIndex(self.rootIndex())

        item = self.itemFromJson(json)

        if parentItem and parentItem is not self.invisibleRootItem():
            if parentItem.jsonType == parentItem.DictType:
                existingKeys = set([parentItem.child(i).data(0, parentItem.KeyRole) for i in range(parentItem.childCount())])
                key = findUniqueName("key", existingKeys)
                item.setData(0, item.KeyRole, key)
            elif parentItem.jsonType != parentItem.ListType:
                return
        else:
            parentItem = self.invisibleRootItem()

        if insertIndex is None:
            parentItem.addChild(item)
        else:
            parentItem.insertChild(insertIndex, item)

        item.setSelected(True)
        self.itemAdded.emit(item)

        # undo
        def f():
            parentItem.removeChild(item)
        self._undoSystem.push("Add", f)

        return item
    
    def removeItem(self):
        selectedItems = self.selectedItems()

        # add undo
        parentItems = []
        for item in selectedItems:
            parent = item.parent()
            skip = False
            while parent:
                if parent in selectedItems:
                    skip = True
                    break
                parent = parent.parent()

            if not skip:
                parentItems.append(item)            

        _undoData = []        
        for item in parentItems:
            parent = item.parent() or self.invisibleRootItem()
            idx = parent.indexOfChild(item)
            _undoData.append([self.getPathIndex(parent), item.clone(), idx])

        def f():
            for parentIdx, item, idx in _undoData:
                parent = self.findItemByPathIndex(parentIdx)
                parent.insertChild(idx, item)
        self._undoSystem.push("Remove", f)

        for item in parentItems:
            (item.parent() or self.invisibleRootItem()).removeChild(item)
            self.itemRemoved.emit(item)

    def getPathIndex(self, item): # auxiliary function for undo system
        parent = item.parent()
        if not parent:
            return [self.invisibleRootItem().indexOfChild(item)]
        
        idx = parent.indexOfChild(item)
        return self.getPathIndex(parent) + [idx]
    
    def findItemByPathIndex(self, pathIndex, parent=None):
        parent = parent or self.invisibleRootItem()
        if not pathIndex:
            return parent
        
        idx = pathIndex[0]
        if idx < parent.childCount():
            return self.findItemByPathIndex(pathIndex[1:], parent.child(idx))
    
    def expandItem(self, item, value=None, *, recursive=True):
        v = not item.isExpanded() if value is None else value
        if item and item is not self.invisibleRootItem():
            if item.jsonType == item.DictType or (item.jsonType == item.ListType and item.childCount() < 10):
                item.setExpanded(v)

        if recursive:
            for i in range(item.childCount()):
                self.expandItem(item.child(i), v, recursive=True)

    def toJsonList(self):
        return [self.itemToJson(self.topLevelItem(i)) for i in range(self.topLevelItemCount())]

    def fromJsonList(self, dataList):
        items = []
        for d in dataList:
            item = self.itemFromJson(d)
            self.addTopLevelItem(item)
            items.append(item)
        return items

    def loadFromJsonList(self, dataList):
        newItems = self.fromJsonList(dataList)
        for item in newItems:
            self.expandItem(item, True)
        
        # undo
        def f():
            for item in newItems:
                self.invisibleRootItem().removeChild(item)
        self._undoSystem.push("Load", f)
        
        self.dataLoaded.emit()

    def itemToJson(self, item):
        if item.jsonType == item.ListType:
            json = []
            for i in range(item.childCount()):
                json.append(self.itemToJson(item.child(i)))
            return json

        elif item.jsonType == item.DictType:
            json = {}
            for i in range(item.childCount()):
                keyItem = item.child(i)
                key = keyItem.data(0, keyItem.KeyRole)
                json[key] = self.itemToJson(keyItem)
            return json
        
        else:
            return item.data(0, Qt.EditRole)

    def itemFromJson(self, data):
        if type(data) == list:
            item = JsonItem(JsonItem.ListType)
            for k in data:
                chItem = self.itemFromJson(k)
                chItem.setFlags(chItem.flags() | Qt.ItemIsDragEnabled)
                item.addChild(chItem)

        elif type(data) == dict:
            item = JsonItem(JsonItem.DictType)
            for k,v in data.items():
                keyItem = self.itemFromJson(v)
                keyItem.setData(0, keyItem.KeyRole, k)
                item.addChild(keyItem)
        else:
            types = {bool: JsonItem.BoolType, int: JsonItem.IntType, float: JsonItem.FloatType, str: JsonItem.StringType}            
            jsonType = types.get(type(data), JsonItem.NoneType)
            item = JsonItem(jsonType, data)

        return item
