# -*- coding: utf-8 -*-

from Qt.QtGui import *
from Qt.QtCore import *
from Qt.QtWidgets import *

import sys
import os
import json

RootPath = os.path.dirname(os.path.dirname(__file__.decode(sys.getfilesystemencoding()))) # Rig Builder root folder

class TemplateWidget(QWidget):
    somethingChanged = Signal()

    def __init__(self, env=None, **kwargs):
        super(TemplateWidget, self).__init__(**kwargs)
        self.env = env # has some data from UI for widgets
        
    def getDefaultData(self):
        return self.getJsonData()
        
    def getJsonData(self):
        raise Exception("getJsonData must be implemented")

    def setJsonData(self, data):
        raise Exception("setJsonData must be implemented")

class EditTextDialog(QDialog):
    def __init__(self, text="", title="Edit text", **kwargs):
        super(EditTextDialog, self).__init__(**kwargs)

        self.outputText = text

        self.setWindowTitle(title)

        layout = QVBoxLayout()
        self.setLayout(layout)

        self.textWidget = QTextEdit()
        self.textWidget.setPlainText(text)
        self.textWidget.setTabStopWidth(16)
        self.textWidget.setAcceptRichText(False)
        self.textWidget.setWordWrapMode(QTextOption.NoWrap)

        okBtn = QPushButton("OK")
        okBtn.clicked.connect(self.okBtnClicked)

        layout.addWidget(self.textWidget)
        layout.addWidget(okBtn)

    def okBtnClicked(self):
        self.outputText = unicode(self.textWidget.toPlainText())
        self.accept()

def clearLayout(layout):
     if layout is not None:
         while layout.count():
             item = layout.takeAt(0)
             widget = item.widget()
             if widget is not None:
                 widget.setParent(None)
             else:
                 clearLayout(item.layout())

def clamp(mn, mx, val):
    if val < mn:
        return mn
    elif val > mx:
        return mx
    else:
        return val

def smartConversion(x):
    try:
        return json.loads(x)
    except ValueError:
        return unicode(x)

def smartConversionToText(x):
    v = json.dumps(x)
    return v[1:-1] if v.startswith("\"") else v
