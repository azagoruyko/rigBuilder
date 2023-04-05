from .base import *

class ListBoxTemplateWidget(TemplateWidget):
    def __init__(self, **kwargs):
        super(ListBoxTemplateWidget, self).__init__(**kwargs)

        layout = QVBoxLayout()
        self.setLayout(layout)
        layout.setContentsMargins(0, 0, 0, 0) 

        self.listWidget = QListWidget()
        self.listWidget.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.listWidget.itemDoubleClicked.connect(self.itemDoubleClicked)
        #self.listWidget.itemChanged.connect(self.changeCallback) 
        #self.listWidget.itemClicked.connect(self.changeCallback) 
        self.listWidget.setContextMenuPolicy(Qt.DefaultContextMenu)
        self.listWidget.contextMenuEvent = self.listContextMenuEvent

        layout.addWidget(self.listWidget, alignment=Qt.AlignLeft|Qt.AlignTop)
        self.resizeList()

    def listContextMenuEvent(self, event):
        menu = QMenu(self)

        appendAction = QAction("Append", self)
        appendAction.triggered.connect(self.appendClicked)
        menu.addAction(appendAction)

        removeAction = QAction("Remove", self)
        removeAction.triggered.connect(self.removeClicked)
        menu.addAction(removeAction)

        editAction = QAction("Edit", self)
        editAction.triggered.connect(self.editClicked)
        menu.addAction(editAction)

        sortAction = QAction("Sort", self)
        sortAction.triggered.connect(self.listWidget.sortItems)
        menu.addAction(sortAction)

        menu.addSeparator()

        getAction = QAction("Get selected from Maya", self)
        getAction.triggered.connect(lambda: self.getFromMayaClicked(False))
        menu.addAction(getAction)

        addSelectedAction = QAction("Add selected from Maya", self)
        addSelectedAction.triggered.connect(lambda: self.getFromMayaClicked(True))
        menu.addAction(addSelectedAction)

        selectAction = QAction("Select in Maya", self)
        selectAction.triggered.connect(self.selectInMayaClicked)
        menu.addAction(selectAction)

        clearAction = QAction("Clear", self)
        clearAction.triggered.connect(self.clearClicked)
        menu.addAction(clearAction)

        menu.popup(event.globalPos())

    def resizeList(self):
        h = self.listWidget.sizeHintForRow(0) * self.listWidget.count() + 2 * self.listWidget.frameWidth() + 25
        height = clamp(50, 250, h)
        self.listWidget.setMinimumHeight(height)
        self.listWidget.setMaximumHeight(height)

    def editClicked(self):
        items = ";".join([unicode(self.listWidget.item(i).text()) for i in range(self.listWidget.count())])
        newItems, ok = QInputDialog.getText(self, "Rig Builder", "Items separated with ';'", QLineEdit.Normal, items)
        if ok and newItems:
            self.listWidget.clear()
            self.listWidget.addItems([x.strip() for x in newItems.split(";")])
            self.somethingChanged.emit()

    def selectInMayaClicked(self):
        import pymel.core as pm
        
        items = [unicode(self.listWidget.item(i).text()) for i in range(self.listWidget.count())]
        pm.select(items)

    def getFromMayaClicked(self, add=False):
        import pymel.core as pm
        
        if not add:
            self.listWidget.clear()

        self.listWidget.addItems([n.name() for n in pm.ls(sl=True)])
        self.resizeList()
        self.somethingChanged.emit()

    def clearClicked(self):
        self.listWidget.clear()
        self.resizeList()
        self.somethingChanged.emit()

    def appendClicked(self):
        self.listWidget.addItem("newItem%d"%(self.listWidget.count()+1))
        self.resizeList()
        self.somethingChanged.emit()

    def removeClicked(self):
        self.listWidget.takeItem(self.listWidget.currentRow())
        self.resizeList()
        self.somethingChanged.emit()

    def itemDoubleClicked(self, item):
        newText, ok = QInputDialog.getText(self, "Rig Builder", "New text", QLineEdit.Normal, item.text())
        if ok:
            item.setText(newText)
            self.somethingChanged.emit()  

    def getDefaultData(self):
        return {"items": ["a", "b"], "default": "items"}#, "current": self.listWidget.currentRow()}

    def getJsonData(self):
        return {"items": [unicode(self.listWidget.item(i).text()) for i in range(self.listWidget.count())], 
                #"current": self.listWidget.currentRow(),
                "default": "items"}

    def setJsonData(self, value):
        self.listWidget.clear()
        self.listWidget.addItems([str(v) for v in value["items"]])
        #self.listWidget.setCurrentRow(value.get("current", 0))

        self.resizeList()
