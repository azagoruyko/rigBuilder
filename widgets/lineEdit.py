from .base import *

class LineEditOptionsDialog(QDialog):
    def __init__(self, **kwargs):
        super(LineEditOptionsDialog, self).__init__(**kwargs)

        self.setWindowTitle("Edit options")

        layout = QVBoxLayout()
        self.setLayout(layout)

        glayout = QGridLayout()
        glayout.setDefaultPositioning(2, Qt.Horizontal)     
        glayout.setColumnStretch(1, 1)

        self.validatorWidget = QComboBox()
        self.validatorWidget.addItems(["Default", "Int", "Double"])
        self.validatorWidget.currentIndexChanged.connect(self.validatorIndexChanged)

        self.minWidget = QLineEdit()
        self.minWidget.setEnabled(False)
        self.minWidget.setValidator(QIntValidator())
        self.maxWidget = QLineEdit()
        self.maxWidget.setEnabled(False)        
        self.maxWidget.setValidator(QIntValidator())

        okBtn = QPushButton("OK")
        okBtn.clicked.connect(self.accept)
        okBtn.setAutoDefault(False)

        glayout.addWidget(QLabel("Validator"))
        glayout.addWidget(self.validatorWidget)

        glayout.addWidget(QLabel("Min"))
        glayout.addWidget(self.minWidget)

        glayout.addWidget(QLabel("Max"))
        glayout.addWidget(self.maxWidget)

        layout.addLayout(glayout)
        layout.addWidget(okBtn)

    def validatorIndexChanged(self, idx):
        self.minWidget.setEnabled(idx!=0)
        self.maxWidget.setEnabled(idx!=0)     

class LineEditTemplateWidget(TemplateWidget):
    def __init__(self, **kwargs):
        super(LineEditTemplateWidget, self).__init__(**kwargs)

        self.optionsDialog = LineEditOptionsDialog(parent=self)
        self.minValue = ""
        self.maxValue = ""
        self.validator = 0

        layout = QHBoxLayout()
        self.setLayout(layout)
        layout.setContentsMargins(0, 0, 0, 0) 

        self.textWidget = QLineEdit()
        self.textWidget.editingFinished.connect(self.textChanged)
        self.textWidget.setContextMenuPolicy(Qt.DefaultContextMenu)
        self.textWidget.contextMenuEvent = self.textContextMenuEvent

        self.sliderWidget = QSlider(Qt.Horizontal)
        self.sliderWidget.setTracking(True)
        self.sliderWidget.valueChanged.connect(self.sliderValueChanged)
        self.sliderWidget.hide()

        layout.addWidget(self.textWidget)
        layout.addWidget(self.sliderWidget)

    def textChanged(self):
        if self.validator:
            self.sliderWidget.setValue(float(self.textWidget.text())*100)

        self.somethingChanged.emit()

    def sliderValueChanged(self, v):
        div = 100 if self.validator == 1 else 100.0
        self.textWidget.setText(str(v/div))
        self.somethingChanged.emit()

    def textContextMenuEvent(self, event):
        menu = self.textWidget.createStandardContextMenu()
        menu.addAction("Options...", self.optionsClicked)
        menu.popup(event.globalPos())

    def optionsClicked(self):
        self.optionsDialog.minWidget.setText(self.minValue)
        self.optionsDialog.maxWidget.setText(self.maxValue)
        self.optionsDialog.validatorWidget.setCurrentIndex(self.validator)
        self.optionsDialog.exec_()
        self.minValue = self.optionsDialog.minWidget.text()
        self.maxValue = self.optionsDialog.maxWidget.text()
        self.validator = self.optionsDialog.validatorWidget.currentIndex()
        self.setJsonData(self.getJsonData())

    def getJsonData(self):
        return {"value": smartConversion(self.textWidget.text().strip()), 
                "default": "value",
                "min": self.minValue,
                "max": self.maxValue,
                "validator": self.validator}

    def setJsonData(self, data):
        self.textWidget.setText(fromSmartConversion(data["value"]))
        self.validator = data.get("validator", 0)
        self.minValue = data.get("min", "")
        self.maxValue = data.get("max", "")

        if self.validator == 1:
            self.textWidget.setValidator(QIntValidator())
        elif self.validator == 2:
            self.textWidget.setValidator(QDoubleValidator())

        if self.minValue and self.maxValue:
            self.sliderWidget.show()

            self.sliderWidget.setMinimum(int(self.minValue)*100) # slider values are int, so mult by 100
            self.sliderWidget.setMaximum(int(self.maxValue)*100)

            if data["value"]:
                self.sliderWidget.setValue(float(data["value"])*100)
        else:
            self.sliderWidget.hide()
