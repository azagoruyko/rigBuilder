from .base import *

class ButtonTemplateWidget(TemplateWidget):
    def __init__(self, **kwargs):
        super(ButtonTemplateWidget, self).__init__(**kwargs)

        self.buttonCommand = "print('Hello world')"

        layout = QHBoxLayout()
        self.setLayout(layout)
        layout.setContentsMargins(0, 0, 0, 0) 

        self.buttonWidget = QPushButton("Press me")
        self.buttonWidget.clicked.connect(self.buttonClicked)
        self.buttonWidget.setContextMenuPolicy(Qt.DefaultContextMenu)
        self.buttonWidget.contextMenuEvent = self.buttonContextMenuEvent

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
            localEnv = {}

            mainWindow = None
            if self.env:
                mainWindow = self.env.get("mainWindow")

                for k in self.env: # copy default env
                    localEnv[k] = self.env[k]

                if mainWindow:
                    for k, v in mainWindow.getModuleGlobalEnv().items():
                        localEnv[k] = v

            exec(self.buttonCommand, localEnv)

            if mainWindow: # update UI
                mainWindow.attributesWidget.update()
    
    def getDefaultData(self):
        return {"command": "a = module.findAttributes('attr')[0]\nprint(a.data)",
                "label": "Press me",
                "default": "label"}

    def getJsonData(self):
        return {"command": self.buttonCommand,
                "label": unicode(self.buttonWidget.text()),
                "default": "label"}

    def setJsonData(self, data):
        self.buttonCommand = data["command"]
        self.buttonWidget.setText(data["label"])
