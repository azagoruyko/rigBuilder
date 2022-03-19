# -*- coding: utf-8 -*-
from .base import *

class LabelTemplateWidget(TemplateWidget):
    def __init__(self, **kwargs):
        super(LabelTemplateWidget, self).__init__(**kwargs)

        self.actualText = ""

        layout = QVBoxLayout()
        self.setLayout(layout)
        layout.setContentsMargins(0, 0, 0, 0) 

        self.label = QLabel()
        self.label.setWordWrap(True)
        self.label.mouseDoubleClickEvent = self.labelDoubleClickEvent

        layout.addWidget(self.label)

    def setText(self, text):
        self.actualText = text
        self.label.setText(self.actualText.replace("$ROOT", RootPath))

    def labelDoubleClickEvent(self, event):
        editTextDialog = EditTextDialog(self.actualText, parent=QApplication.activeWindow())
        editTextDialog.exec_()

        if editTextDialog.result():
            self.setText(editTextDialog.outputText)
            self.somethingChanged.emit()

    def getDefaultData(self):
        return {"text": "Description", "default": "text"}

    def getJsonData(self):
        return {"text": self.actualText, "default": "text"}

    def setJsonData(self, value):
        self.setText(value["text"])

'''
app = QApplication([])
l = LabelTemplateWidget()
l.show()
app.exec_()
'''
