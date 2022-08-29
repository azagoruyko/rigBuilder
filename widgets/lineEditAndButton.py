from .base import *

class LineEditAndButtonTemplateWidget(TemplateWidget):
    def __init__(self, **kwargs):
        super(LineEditAndButtonTemplateWidget, self).__init__(**kwargs)

        self.buttonCommand = "import maya.cmds as cmds\nls = cmds.ls(sl=True)\nif ls: value = ls[0]"

        layout = QHBoxLayout()
        self.setLayout(layout)
        layout.setContentsMargins(0, 0, 0, 0) 

        self.textWidget = QLineEdit()
        self.textWidget.editingFinished.connect(self.somethingChanged) 

        self.buttonWidget = QPushButton("<")
        self.buttonWidget.clicked.connect(self.buttonClicked)
        self.buttonWidget.setContextMenuPolicy(Qt.DefaultContextMenu)
        self.buttonWidget.contextMenuEvent = self.buttonContextMenuEvent

        layout.addWidget(self.textWidget)
        layout.addWidget(self.buttonWidget)

    def buttonContextMenuEvent(self, event):
        menu = QMenu(self)

        editLabelAction = QAction("Edit label", self)
        editLabelAction.triggered.connect(self.editLabelActionClicked)
        menu.addAction(editLabelAction)

        editAction = QAction("Edit command", self)
        editAction.triggered.connect(self.editActionClicked)
        menu.addAction(editAction)

        menu.popup(event.globalPos())

    def editLabelActionClicked(self):
        newName, ok = QInputDialog.getText(self, "Rename", "New label", QLineEdit.Normal, self.buttonWidget.text())
        if ok:
            self.buttonWidget.setText(newName)
            self.somethingChanged.emit()

    def editActionClicked(self):
        editText = EditTextDialog(self.buttonCommand, parent=QApplication.activeWindow())
        editText.exec_()
        self.buttonCommand = editText.outputText
        self.somethingChanged.emit()

    def buttonClicked(self):
        if self.buttonCommand:
            import Qt
            env = {"value": self.textWidget.text(), "Qt": Qt}
            exec(self.buttonCommand) in env
            self.setCustomText(env["value"])
            
            self.somethingChanged.emit()
        
    def getJsonData(self):
        return {"value": smartConversion(self.textWidget.text().strip()),
                "buttonCommand": self.buttonCommand,
                "buttonLabel": unicode(self.buttonWidget.text()),
                "default": "value"}

    def setCustomText(self, value):
        self.textWidget.setText(fromSmartConversion(value))

    def setJsonData(self, data):
        self.setCustomText(data["value"])
        self.buttonCommand = data["buttonCommand"]
        self.buttonWidget.setText(data["buttonLabel"])
