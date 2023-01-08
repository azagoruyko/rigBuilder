from .base import *

class ComboBoxTemplateWidget(TemplateWidget):
    def __init__(self, **kwargs):
        super(ComboBoxTemplateWidget, self).__init__(**kwargs)

        layout = QVBoxLayout()
        self.setLayout(layout)
        layout.setContentsMargins(0, 0, 0, 0) 

        self.comboBox = QComboBox()
        self.comboBox.setContextMenuPolicy(Qt.DefaultContextMenu)
        self.comboBox.currentIndexChanged.connect(self.somethingChanged) 
        self.comboBox.contextMenuEvent = self.comboBoxContextMenuEvent
        layout.addWidget(self.comboBox)

    def comboBoxContextMenuEvent(self, event):
        menu = QMenu(self)

        appendAction = QAction("Append", self)
        appendAction.triggered.connect(self.appendItem)
        menu.addAction(appendAction)

        removeAction = QAction("Remove", self)
        removeAction.triggered.connect(self.removeItem)
        menu.addAction(removeAction)

        editAction = QAction("Edit", self)
        editAction.triggered.connect(self.editItems)
        menu.addAction(editAction)

        menu.addSeparator()

        clearAction = QAction("Clear", self)
        clearAction.triggered.connect(self.clearItems)
        menu.addAction(clearAction)

        menu.popup(event.globalPos())

    def editItems(self):
        items = ";".join([str(self.comboBox.itemText(i)) for i in range(self.comboBox.count())])
        newItems, ok = QInputDialog.getText(self, "Rig Builder", "Items separated with ';'", QLineEdit.Normal, items)
        if ok and newItems:
            self.comboBox.clear()
            self.comboBox.addItems([x.strip() for x in newItems.split(";")])
            self.somethingChanged.emit()

    def clearItems(self):
        ok = QMessageBox.question(self, "Rig Builder", "Really clear all items?", QMessageBox.Yes and QMessageBox.No, QMessageBox.Yes) == QMessageBox.Yes
        if ok:
            self.comboBox.clear()
            self.somethingChanged.emit()

    def appendItem(self):
        name, ok = QInputDialog.getText(self, "Rig Builder", "Name", QLineEdit.Normal, "")
        if ok and name:
            self.comboBox.addItem(name)
            self.somethingChanged.emit()

    def removeItem(self):
        self.comboBox.removeItem(self.comboBox.currentIndex())
        self.somethingChanged.emit()

    def getDefaultData(self):
        return {"items": ["a", "b"], "current": "a", "default": "current"}

    def getJsonData(self):
        return {"items": [str(self.comboBox.itemText(i)) for i in range(self.comboBox.count())],                
                "current": str(self.comboBox.currentText()),
                "default": "current"}

    def setJsonData(self, value):
        self.comboBox.clear()
        self.comboBox.addItems(value["items"])

        if value["current"] in value["items"]:
            self.comboBox.setCurrentIndex(value["items"].index(value["current"]))
