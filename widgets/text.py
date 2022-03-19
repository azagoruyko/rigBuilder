from .base import *

class TextTemplateWidget(TemplateWidget):
    def __init__(self, **kwargs):
        super(TextTemplateWidget, self).__init__(**kwargs)

        layout = QVBoxLayout()
        self.setLayout(layout)
        layout.setContentsMargins(0, 0, 0, 0) 

        self.textWidget = QTextEdit()
        self.textWidget.textChanged.connect(self.somethingChanged) 

        layout.addWidget(self.textWidget)

    def getJsonData(self):
        return {"text": self.textWidget.toPlainText().strip(), 
                "default": "text"}

    def setJsonData(self, data):
        self.textWidget.setPlainText(data["text"])

