from .base import *

from .checkBox import *
from .comboBox import *
from .lineEdit import *
from .lineEditAndButton import *
from .vector import *
from .compound import *

TemplateWidgets = {"compound": CompoundTemplateWidget, 
                   "lineEdit": LineEditTemplateWidget, 
                   "lineEditAndButton": LineEditAndButtonTemplateWidget, 
                   "checkBox": CheckBoxTemplateWidget,
                   "comboBox": ComboBoxTemplateWidget,
                   "vector": VectorTemplateWidget}

class MultiTemplateWidget(TemplateWidget):
    def __init__(self,  **kwargs):
        super(MultiTemplateWidget, self).__init__(**kwargs)

        self.template = ""

        layout = QVBoxLayout()
        self.setLayout(layout)
        layout.setContentsMargins(0, 0, 0, 0)

        toolsLayout = QHBoxLayout()
        resizeBtn = QPushButton("N")
        resizeBtn.clicked.connect(self.resizeItems)
        addBtn = QPushButton("+")
        addBtn.clicked.connect(self.addBtnClicked)
        removeBtn = QPushButton("-")
        removeBtn.clicked.connect(self.removeBtnClicked)        
        toolsLayout.addWidget(resizeBtn)
        toolsLayout.addWidget(addBtn)
        toolsLayout.addWidget(removeBtn)
        toolsLayout.addStretch()
        layout.addLayout(toolsLayout)

        itemsWidget = QWidget()
        self.itemsLayout = QGridLayout()
        self.itemsLayout.setDefaultPositioning(2, Qt.Horizontal)     
        self.itemsLayout.setColumnStretch(1, 1)
        self.itemsLayout.setContentsMargins(0, 0, 0, 0)
        itemsWidget.setLayout(self.itemsLayout)

        self.scrollArea = QScrollArea()
        self.scrollArea.setWidget(itemsWidget)
        self.scrollArea.setWidgetResizable(True)    
        layout.addWidget(self.scrollArea)
        layout.addStretch()

        self.setContextMenuPolicy(Qt.DefaultContextMenu)

    def addBtnClicked(self):
        data = self.getJsonData()

        itemData = self.itemsLayout.itemAt(1).widget().getJsonData() if self.itemsLayout.count() > 1 else TemplateWidgets[data["template"]]().getJsonData()

        data["items"].append(itemData)
        self.setJsonData(data)
        self.somethingChanged.emit()

    def removeBtnClicked(self):
        indexToRemove, ok = QInputDialog.getText(self, "Remove", "Indices to remove", QLineEdit.Normal, "0;1")
        if indexToRemove and ok:
            data = self.getJsonData()
            skipIndices = [int(index) for index in indexToRemove.split(";")]
            data["items"] = [item for i,item in enumerate(data["items"]) if i not in skipIndices]
            self.setJsonData(data)

            self.somethingChanged.emit()

    def contextMenuEvent(self, event):
        menu = QMenu(self)

        templateMenu = QMenu("Template")
        for t in sorted(TemplateWidgets):
            action = QAction(t, self)
            action.setCheckable(True)
            if t == self.template:
                action.setChecked(True)
            action.triggered.connect(lambda t=t:self.changeTemplate(t))
            templateMenu.addAction(action)

        menu.addMenu(templateMenu)

        resizeAction = QAction("Resize", self)
        resizeAction.triggered.connect(self.resizeItems)
        menu.addAction(resizeAction)
        menu.popup(event.globalPos())  

    def resizeItems(self):
        data = self.itemsLayout.itemAt(1).widget().getJsonData() if self.itemsLayout.count() > 1 else None

        newSize, ok = QInputDialog.getText(self, "Resize", "New size", QLineEdit.Normal, str(self.itemsLayout.count()/2))
        if newSize and ok:
            self.setJsonData({"items": [data]*int(newSize), "template":self.template, "default":"values"})
            self.somethingChanged.emit()

    def changeTemplate(self, t):
        self.setJsonData({"items": [TemplateWidgets[t]().getJsonData()]*(self.itemsLayout.count()/2), "template":t, "default":"values"})
        self.somethingChanged.emit()

    def getDefaultData(self):
        return {"items": [TemplateWidgets["checkBox"]().getJsonData()]*2, "values":[], "template":"checkBox", "default":"values"}

    def getJsonData(self):
        items = []
        values = []

        for i in range(self.itemsLayout.count()):
            w = self.itemsLayout.itemAt(i).widget()
            if isinstance(w, TemplateWidget):
                data = self.itemsLayout.itemAt(i).widget().getJsonData()
                items.append(data)
                values.append(data[data["default"]])

        return {"items": items, 
                "values": values,
                "template":self.template,
                "default": "values"}

    def setJsonData(self, data):
        self.template = data["template"]

        clearLayout(self.itemsLayout)

        for i, itemData in enumerate(data["items"]):
            w = TemplateWidgets[self.template]()
            w.setJsonData(itemData)
            w.somethingChanged.connect(self.somethingChanged)
            self.itemsLayout.addWidget(QLabel(str("[%d]"%i)), i, 0)
            self.itemsLayout.addWidget(w, i, 1)

'''
def somethingChanged():print w.getJsonData()
app = QApplication([])
w = MultiTemplateWidget()
w.setJsonData({"items": [LineEditTemplateWidget().getJsonData()]*10, "values":[], "template":"lineEdit", "default":"values"})
w.somethingChanged.connect(somethingChanged)
w.show()
app.exec_()      
'''