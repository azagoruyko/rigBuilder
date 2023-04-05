from .base import *

class RadioButtonTemplateWidget(TemplateWidget):
    NumberColumns = 3

    def __init__(self, **kwargs):
        super(RadioButtonTemplateWidget, self).__init__(**kwargs)

        self.setContextMenuPolicy(Qt.DefaultContextMenu)

        layout = QGridLayout()
        layout.setDefaultPositioning(RadioButtonTemplateWidget.NumberColumns, Qt.Horizontal)
        self.setLayout(layout)
        layout.setContentsMargins(0, 0, 0, 0) 

        self.buttonsGroupWidget = QButtonGroup()
        self.buttonsGroupWidget.buttonClicked.connect(self.buttonClicked)
        
    def contextMenuEvent(self, event):
        menu = QMenu(self)

        editAction = QAction("Edit", self)
        editAction.triggered.connect(self.editClicked)
        menu.addAction(editAction)

        menu.popup(event.globalPos())

    def colorizeButtons(self):
        for b in self.buttonsGroupWidget.buttons():
            b.setStyleSheet("background-color: #2a6931" if b.isChecked() else "")

    def buttonClicked(self, b):
        self.colorizeButtons()
        self.somethingChanged.emit()

    def clearButtons(self):
        gridLayout = self.layout()
        clearLayout(gridLayout)

        for b in self.buttonsGroupWidget.buttons():
            self.buttonsGroupWidget.removeButton(b)

    def editClicked(self):
        items = ";".join([unicode(b.text()) for b in self.buttonsGroupWidget.buttons()])
        newItems, ok = QInputDialog.getText(self, "Rig Builder", "Items separated with ';'", QLineEdit.Normal, items)
        if ok and newItems:
            self.clearButtons()
            data = self.getJsonData()
            data["items"] = [x.strip() for x in newItems.split(";")]
            self.setJsonData(data)
            self.somethingChanged.emit()

    def getDefaultData(self):
        return {"items": ["Helpers", "Run"], "current": 0, "default": "current"}
        
    def getJsonData(self):
        return {"items": [unicode(b.text()) for b in self.buttonsGroupWidget.buttons()],
                "current": self.buttonsGroupWidget.checkedId(),
                "default": "current"}

    def setJsonData(self, value):
        self.clearButtons()
        gridLayout = self.layout()

        row = 0
        column = 0
        for i, item in enumerate(value["items"]):
            if i % RadioButtonTemplateWidget.NumberColumns == 0 and i > 0:
                row += 1
                column = 0

            button = QRadioButton(item)
            gridLayout.addWidget(button, row, column)

            self.buttonsGroupWidget.addButton(button)
            self.buttonsGroupWidget.setId(button, i)
            column += 1

        self.buttonsGroupWidget.buttons()[value["current"]].setChecked(True)
        self.colorizeButtons()
