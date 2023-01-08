from .base import *

from .checkBox import *
from .comboBox import *
from .curve import *
from .label import *
from .lineEdit import *
from .lineEditAndButton import *
from .button import *
from .listBox import *
from .radioButton import *
from .text import *
from .vector import *

TemplateWidgets = {"lineEdit": LineEditTemplateWidget, 
                   "lineEditAndButton": LineEditAndButtonTemplateWidget, 
                   "label": LabelTemplateWidget, 
                   "button": ButtonTemplateWidget, 
                   "checkBox": CheckBoxTemplateWidget,
                   "comboBox": ComboBoxTemplateWidget,
                   "curve": CurveTemplateWidget,
                   "listBox": ListBoxTemplateWidget,
                   "radioButton": RadioButtonTemplateWidget,
                   "text": TextTemplateWidget,
                   "vector": VectorTemplateWidget}

class CompoundTemplateWidget(TemplateWidget):
    def __init__(self, **kwargs):
        super(CompoundTemplateWidget, self).__init__(**kwargs)

        self.numColumns = 0

        layout = QVBoxLayout()
        self.setLayout(layout)
        layout.setContentsMargins(0, 0, 0, 0)

        self.gridLayout = QGridLayout()
        self.gridLayout.setContentsMargins(0, 0, 0, 0)

        layout.addLayout(self.gridLayout)

        self.setContextMenuPolicy(Qt.DefaultContextMenu)
        
    def contextMenuEvent(self, event):
        menu = QMenu(self)
        editLayout = QAction("Edit layout", self)
        editLayout.triggered.connect(self.editLayout)
        menu.addAction(editLayout)
        menu.popup(event.globalPos())

    def getLayout(self):
        layout = [str(self.numColumns)]
        for i in range(self.gridLayout.count()):
            w = self.gridLayout.itemAt(i).widget()
            if w:
                if isinstance(w, TemplateWidget):
                    layout.append(w.template)
                else:
                    layout.append(w.text())
        return ";".join(layout)

    def editLayout(self):
        layout, ok = QInputDialog.getText(self, "Layout", "New layout: N,template,text,...", QLineEdit.Normal, self.getLayout())
        if layout and ok:
            items = []
            layoutItems = layout.split(";")
            numColumns = int(layoutItems[0])
            for item in layoutItems[1:]:
                if TemplateWidgets.get(item):
                    items.append({"template": item, "data":TemplateWidgets[item]().getDefaultData()})
                else:
                    items.append(item.strip())

            self.setJsonData({"layout":{"items": items , "columns":numColumns}})
            self.somethingChanged.emit()

    def getDefaultData(self):
        return {"layout":{"items": [{"template": "lineEdit", "data":TemplateWidgets["lineEdit"]().getDefaultData()}, 
                                     "Are you sure?", {"template":"checkBox", "data":TemplateWidgets["checkBox"]().getDefaultData()}], 
                                     "columns":3}}

    def getJsonData(self):        
        layout = {"items":[], "columns": self.numColumns}
        values = []
        for i in range(self.gridLayout.count()):
            w = self.gridLayout.itemAt(i).widget()
            if isinstance(w, TemplateWidget):
                data = w.getJsonData()
                layout["items"].append({"template":w.template, "data":data})
                values.append(data[data["default"]])
            else:
                layout["items"].append(w.text())

        return {"layout": layout,                 
                "values":values,
                "default": "values"}

    def setJsonData(self, data):
        clearLayout(self.gridLayout)

        layout = data["layout"]
        self.numColumns = layout["columns"]

        self.gridLayout.setDefaultPositioning(self.numColumns, Qt.Horizontal)     

        for i, item in enumerate(layout["items"]):
            c = i % self.numColumns
            r = i / self.numColumns
            if type(item) in [str]:
                self.gridLayout.addWidget(QLabel(item), r, c)
            else:
                w = TemplateWidgets[item["template"]](env=self.env)
                w.setJsonData(item["data"])
                w.template = item["template"]
                w.somethingChanged.connect(self.somethingChanged)
                self.gridLayout.addWidget(w, r, c)

'''    
def somethingChanged(): print w.getJsonData()
app = QApplication([])
w = CompoundTemplateWidget()
#w.setJsonData({"layout":{"items": ["Edit text", {"template":"lineEdit", "data":LineEditTemplateWidget().getJsonData()}, {"template":"checkBox", "data":CheckBoxTemplateWidget().getJsonData()}, "Are you sure?", "bla","listBox"], "columns":4}})
w.somethingChanged.connect(somethingChanged)
w.show()
app.exec_()        
'''