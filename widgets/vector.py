from .base import *

class VectorTemplateWidget(TemplateWidget):
    def __init__(self, **kwargs):
        super(VectorTemplateWidget, self).__init__(**kwargs)

        layout = QHBoxLayout()
        self.setLayout(layout)
        layout.setContentsMargins(0, 0, 0, 0) 

        self.xWidget = QLineEdit("0")
        self.xWidget.setValidator(QDoubleValidator())
        self.xWidget.editingFinished.connect(self.somethingChanged) 

        self.yWidget = QLineEdit("0")
        self.yWidget.setValidator(QDoubleValidator())
        self.yWidget.editingFinished.connect(self.somethingChanged) 

        self.zWidget = QLineEdit("0")
        self.zWidget.setValidator(QDoubleValidator())
        self.zWidget.editingFinished.connect(self.somethingChanged) 

        layout.addWidget(self.xWidget)
        layout.addWidget(self.yWidget)
        layout.addWidget(self.zWidget)

    def getJsonData(self):
        return {"value": [float(self.xWidget.text()), float(self.yWidget.text()), float(self.zWidget.text())],
                "default": "value"}

    def setJsonData(self, value):
        self.xWidget.setText(str(value["value"][0]))
        self.yWidget.setText(str(value["value"][1]))
        self.zWidget.setText(str(value["value"][2]))
