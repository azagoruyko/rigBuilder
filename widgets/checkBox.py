from .base import *

class CheckBoxTemplateWidget(TemplateWidget):
    def __init__(self, **kwargs):
        super(CheckBoxTemplateWidget, self).__init__(**kwargs)

        layout = QVBoxLayout()
        self.setLayout(layout)
        layout.setContentsMargins(0, 0, 0, 0) 

        self.checkBox = QCheckBox()
        self.checkBox.stateChanged.connect(self.somethingChanged)
        layout.addWidget(self.checkBox)

    def getJsonData(self):
        return {"checked": self.checkBox.isChecked(), "default": "checked"}

    def setJsonData(self, value):
        self.checkBox.setChecked(True if value["checked"] else False)
