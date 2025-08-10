from PySide6.QtCore import *
from PySide6.QtGui import *
from PySide6.QtWidgets import *

import sys
import os
import json
import math
from .utils import *
from .editor import *
from .jsonWidget import JsonWidget

DCC = os.getenv("RIG_BUILDER_DCC") or "maya"

RootPath = os.path.dirname(__file__) # Rig Builder root folder

if DCC == "maya":
    import maya.cmds as cmds

class TemplateWidget(QFrame):
    somethingChanged = Signal()

    def __init__(self, *, executor=None, **kwargs):
        super().__init__(**kwargs)
        self.executor = executor or self._defaultExecutor # used to execute commands

    def _defaultExecutor(self, cmd, env=None):
        localEnv = dict(WidgetsAPI)
        localEnv.update(env or {})
        exec(cmd, localEnv)
        return localEnv

    def getDefaultData(self):
        return self.getJsonData()

    def getJsonData(self):
        raise Exception("getJsonData must be implemented")

    def setJsonData(self, data):
        raise Exception("setJsonData must be implemented")
    
class EditTextDialog(QDialog):
    saved = Signal(str) # emitted when user clicks OK

    def __init__(self, text="", *, title="Edit", placeholder="", words=None, python=False):
        super().__init__(parent=QApplication.activeWindow())

        self.setWindowTitle(title)
        self.setGeometry(0, 0, 600, 400)

        layout = QVBoxLayout()
        self.setLayout(layout)

        if not python:
            self.textWidget = QTextEdit()            
            # Qt compatibility: setTabStopWidth (Qt5) vs setTabStopDistance (Qt6)
            if hasattr(self.textWidget, 'setTabStopDistance'):
                self.textWidget.setTabStopDistance(16)
            else:
                self.textWidget.setTabStopWidth(16)
            self.textWidget.setAcceptRichText(False)
            self.textWidget.setWordWrapMode(QTextOption.NoWrap)            
        else:
            self.textWidget = CodeEditorWidget()
            self.textWidget.words = words or []
        
        self.textWidget.setPlaceholderText(placeholder)
        self.textWidget.setPlainText(text)

        okBtn = QPushButton("OK")
        okBtn.clicked.connect(self.saveAndClose)

        layout.addWidget(self.textWidget)
        layout.addWidget(okBtn)

        centerWindow(self)

    def saveAndClose(self):
        self.saved.emit(self.textWidget.toPlainText())
        self.accept()

class EditJsonDialog(QDialog):
    saved = Signal(object)

    def __init__(self, data, *, title="Edit"):
        super().__init__(parent=QApplication.activeWindow())

        self.setWindowTitle(title)
        self.setGeometry(0, 0, 600, 400)

        layout = QVBoxLayout()
        self.setLayout(layout)

        self.jsonWidget = JsonWidget(data)

        okBtn = QPushButton("OK")
        okBtn.clicked.connect(self.saveAndClose)

        layout.addWidget(self.jsonWidget)
        layout.addWidget(okBtn)
        centerWindow(self)

    def saveAndClose(self):
        dataList = self.jsonWidget.toJsonList()
        self.saved.emit(dataList)
        self.accept()

class LabelTemplateWidget(TemplateWidget):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)

        self._actualText = ""

        layout = QVBoxLayout()
        self.setLayout(layout)
        layout.setContentsMargins(QMargins())

        self.label = QLabel()
        self.label.setCursor(Qt.PointingHandCursor)
        self.label.setWordWrap(True)
        self.label.mouseDoubleClickEvent = self.labelDoubleClickEvent

        layout.addWidget(self.label)

    def setLabelText(self, text):
        self._actualText = text
        self.label.setText(self._actualText.replace("$ROOT", RootPath))

    def labelDoubleClickEvent(self, event):
        def save(text):
            self.setLabelText(text)
            self.somethingChanged.emit()

        placeholder = '<img src="$ROOT/images/icons/info.png">Description'
        editTextDialog = EditTextDialog(self._actualText, title="Edit text", placeholder=placeholder)
        editTextDialog.saved.connect(save)
        editTextDialog.show()        

    def getDefaultData(self):
        return {"text": "Description", "default": "text"}

    def getJsonData(self):
        return {"text": self._actualText, "default": "text"}

    def setJsonData(self, value):
        self.setLabelText(value["text"])

class ButtonTemplateWidget(TemplateWidget):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)

        self.buttonCommand = ""

        layout = QHBoxLayout()
        self.setLayout(layout)
        layout.setContentsMargins(QMargins())

        self.buttonWidget = QPushButton("Press me")
        self.buttonWidget.clicked.connect(self.buttonClicked)
        self.buttonWidget.contextMenuEvent = self.buttonContextMenuEvent

        layout.addWidget(self.buttonWidget)

    def buttonContextMenuEvent(self, event):
        menu = QMenu(self)

        menu.addAction("Edit label", self.editLabel)
        menu.addAction("Edit command", self.editCommand)

        menu.popup(event.globalPos())

    def editLabel(self):
        newName, ok = QInputDialog.getText(self, "Rename", "New label", QLineEdit.Normal, self.buttonWidget.text())
        if ok:
            self.buttonWidget.setText(newName)
            self.somethingChanged.emit()

    def editCommand(self):
        def save(text):
            self.buttonCommand = text
            self.somethingChanged.emit()

        words = list(self.executor("").keys())
    
        editText = EditTextDialog(self.buttonCommand, title="Edit command", placeholder='chset("/someAttr", 1)', words=words, python=True)
        editText.saved.connect(save)
        editText.show()

    def buttonClicked(self):
        if self.buttonCommand:
            def f():
                self.executor(self.buttonCommand)

            f()

    def getDefaultData(self):
        return {"command": 'chset("/someAttr", 1)',
                "label": "Press me",
                "default": "label"}

    def getJsonData(self):
        return {"command": self.buttonCommand,
                "label": self.buttonWidget.text(),
                "default": "label"}

    def setJsonData(self, data):
        self.buttonCommand = data["command"]
        self.buttonWidget.setText(data["label"])

class CheckBoxTemplateWidget(TemplateWidget):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)

        layout = QVBoxLayout()
        self.setLayout(layout)
        layout.setContentsMargins(QMargins())

        self.checkBox = QCheckBox()
        self.checkBox.stateChanged.connect(lambda _=None: self.somethingChanged.emit())
        layout.addWidget(self.checkBox)

    def getJsonData(self):
        return {"checked": self.checkBox.isChecked(), "default": "checked"}

    def setJsonData(self, value):
        with blockedWidgetContext(self.checkBox) as w:
            w.setChecked(value["checked"])

class ComboBoxTemplateWidget(TemplateWidget):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)

        layout = QVBoxLayout()
        self.setLayout(layout)
        layout.setContentsMargins(QMargins())

        self.comboBox = QComboBox()
        self.comboBox.activated.connect(lambda _=None: self.somethingChanged.emit())
        self.comboBox.contextMenuEvent = self.comboBoxContextMenuEvent
        layout.addWidget(self.comboBox)

    def comboBoxContextMenuEvent(self, event):
        menu = QMenu(self)

        menu.addAction("Append", self.appendItem)
        menu.addAction("Remove", self.removeItem)
        menu.addAction("Edit", self.editItems)
        menu.addSeparator()
        menu.addAction("Clear", self.clearItems)

        menu.popup(event.globalPos())

    def editItems(self):
        def save(newData):
            self.setItems(newData)

        data = self.getItems()
        w = EditJsonDialog(data, title="Edit items")
        w.saved.connect(save)
        w.show()

    def clearItems(self):
        ok = QMessageBox.question(self, "Rig Builder", "Really clear all items?", QMessageBox.Yes and QMessageBox.No, QMessageBox.Yes) == QMessageBox.Yes
        if ok:
            with blockedWidgetContext(self.comboBox) as w:
                w.clear()
            self.somethingChanged.emit()

    def appendItem(self):
        value, ok = QInputDialog.getText(self, "Rig Builder", "Value", QLineEdit.Normal, "")
        if ok and value:
            self.comboBox.addItem(value)
            self.somethingChanged.emit()

    def removeItem(self):
        self.comboBox.removeItem(self.comboBox.currentIndex())
        self.somethingChanged.emit()

    def getItems(self):
        return [smartConversion(self.comboBox.itemText(i)) for i in range(self.comboBox.count())]
    
    def setItems(self, items):
        with blockedWidgetContext(self.comboBox) as w:
            w.clear()

            for i, item in enumerate(items):
                w.addItem(fromSmartConversion(item))
                w.setItemData(i, jsonColor(item), Qt.ForegroundRole)

        self.somethingChanged.emit()

    def getDefaultData(self):
        return {"items": ["a", "b"], "current": "a", "default": "current"}

    def getJsonData(self):
        return {"items": self.getItems(),
                "current": smartConversion(self.comboBox.currentText()),
                "default": "current"}

    def setJsonData(self, value):
        items = list(value["items"])
        
        if value["current"] not in items:
            items.append(value["current"]) # make sure current is in items

        self.setItems(items)

        with blockedWidgetContext(self.comboBox) as w:
            w.setCurrentIndex(items.index(value["current"]))

class LineEditOptionsDialog(QDialog):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)

        self.setWindowTitle("Edit options")

        layout = QVBoxLayout()
        self.setLayout(layout)

        formLayout = QFormLayout()
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

        formLayout.addRow("Validator", self.validatorWidget)
        formLayout.addRow("Min", self.minWidget)
        formLayout.addRow("Max", self.maxWidget)

        layout.addLayout(formLayout)
        layout.addWidget(okBtn)

    def validatorIndexChanged(self, idx):
        self.minWidget.setEnabled(idx!=0)
        self.maxWidget.setEnabled(idx!=0)

class LineEditTemplateWidget(TemplateWidget):
    defaultMin = 0
    defaultMax = 100

    def __init__(self, **kwargs):
        super().__init__(**kwargs)

        self.optionsDialog = LineEditOptionsDialog(parent=self)
        self.minValue = 0
        self.maxValue = 100
        self.validator = 0
        self.value = ""

        layout = QHBoxLayout()
        self.setLayout(layout)
        layout.setContentsMargins(QMargins())

        self.textWidget = QLineEdit()
        self.textWidget.editingFinished.connect(self.textChanged)
        self.textWidget.contextMenuEvent = self.textContextMenuEvent

        self.sliderWidget = QSlider(Qt.Horizontal)
        self.sliderWidget.setTracking(True)
        self.sliderWidget.valueChanged.connect(self.sliderValueChanged)
        self.sliderWidget.hide()

        layout.addWidget(self.textWidget)
        layout.addWidget(self.sliderWidget)

    def colorizeValue(self):
        color = jsonColor(self.value)
        self.textWidget.setStyleSheet("QLineEdit {{ color: {} }}".format(color.name()))

    def textChanged(self):
        text = self.textWidget.text().strip()
        if self.validator:
            self.sliderWidget.setValue(float(text)*100)

        self.value = smartConversion(text)
        self.colorizeValue()
        self.somethingChanged.emit()

    def sliderValueChanged(self, v):
        v /= 100.0
        if self.validator == 1: # int
            v = round(v)        
        self.value = v
        self.textWidget.setText(str(v))
        self.somethingChanged.emit()

    def textContextMenuEvent(self, event):
        menu = self.textWidget.createStandardContextMenu()
        menu.addSeparator()
        menu.addAction("Options...", self.optionsClicked)
        menu.popup(event.globalPos())

    def optionsClicked(self):
        self.optionsDialog.minWidget.setText(str(self.minValue))
        self.optionsDialog.maxWidget.setText(str(self.maxValue))
        self.optionsDialog.validatorWidget.setCurrentIndex(self.validator)
        self.optionsDialog.exec_()
        self.minValue = int(self.optionsDialog.minWidget.text() or LineEditTemplateWidget.defaultMin)
        self.maxValue = int(self.optionsDialog.maxWidget.text() or LineEditTemplateWidget.defaultMax)
        self.validator = self.optionsDialog.validatorWidget.currentIndex()
        self.setupSlider()
        self.somethingChanged.emit()

    def getJsonData(self):
        return {"value": self.value,
                "default": "value",
                "min": self.minValue,
                "max": self.maxValue,
                "validator": self.validator}
    
    def setupSlider(self):
        if self.validator:
            self.sliderWidget.show()
            with blockedWidgetContext(self.sliderWidget) as slider:
                if self.minValue:
                    slider.setMinimum(self.minValue*100) # slider values are int, so mult by 100
                if self.maxValue:
                    slider.setMaximum(self.maxValue*100)
                
                if self.value:                
                    slider.setValue(float(self.value)*100)
        else:
            self.sliderWidget.hide()

    def setJsonData(self, data):
        self.validator = data.get("validator", 0)
        self.minValue = int(data.get("min") or LineEditTemplateWidget.defaultMin)
        self.maxValue = int(data.get("max") or LineEditTemplateWidget.defaultMax)
        self.value = data.get("value", "")

        if self.validator == 1: # int
            validator = QIntValidator()
            validator.setRange(self.minValue, self.maxValue)
            self.textWidget.setValidator(validator)

        elif self.validator == 2: # double
            validator = QDoubleValidator()
            validator.setRange(self.minValue, self.maxValue)
            validator.setDecimals(2)
            self.textWidget.setValidator(validator)

        else:
            self.textWidget.setValidator(None)

        with blockedWidgetContext(self.textWidget) as w:
            w.setText(fromSmartConversion(self.value))

        self.setupSlider()
        self.colorizeValue()

class LineEditAndButtonTemplateWidget(TemplateWidget):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)

        defaultCmd = {"label": "<", "command": 'value = "Hello world!"'}

        self.templates = {}
        if DCC == "maya":
            self.templates["Get selected"] = {"label": "<", "command":"import maya.cmds as cmds\nls = cmds.ls(sl=True)\nif ls: value = ls[0]"}
            defaultCmd = self.templates["Get selected"]

        self.templates["Get open file"] = {"label": "...", "command":'''from PySide2.QtWidgets import QFileDialog;import os
path,_ = QFileDialog.getOpenFileName(None, "Open file", os.path.expandvars(value))
value = path or value'''}

        self.templates["Get save file"] = {"label": "...", "command":'''from PySide2.QtWidgets import QFileDialog;import os
path,_ = QFileDialog.getSaveFileName(None, "Save file", os.path.expandvars(value))
value = path or value'''}

        self.templates["Get existing directory"] = {"label": "...", "command":'''from PySide2.QtWidgets import QFileDialog;import os
path = QFileDialog.getExistingDirectory(None, "Select directory", os.path.expandvars(value))
value = path or value'''}

        self.buttonCommand = defaultCmd["command"]
        self.value = ""

        layout = QHBoxLayout()
        self.setLayout(layout)
        layout.setContentsMargins(QMargins())

        self.textWidget = QLineEdit()
        self.textWidget.editingFinished.connect(self.textChanged)

        self.buttonWidget = QPushButton(defaultCmd["label"])
        self.buttonWidget.clicked.connect(self.buttonClicked)
        self.buttonWidget.contextMenuEvent = self.buttonContextMenuEvent

        layout.addWidget(self.textWidget)
        layout.addWidget(self.buttonWidget)

    def colorizeValue(self):
        color = jsonColor(self.value)
        self.textWidget.setStyleSheet("QLineEdit {{ color: {} }}".format(color.name()))

    def textChanged(self):
        self.value = smartConversion(self.textWidget.text().strip())
        self.colorizeValue()
        self.somethingChanged.emit()

    def buttonContextMenuEvent(self, event):
        menu = QMenu(self)

        menu.addAction("Edit label", self.editLabel)
        menu.addAction("Edit command", self.editCommand)

        if self.templates:
            def setCommand(cmd):
                self.buttonWidget.setText(cmd["label"])
                self.buttonCommand = cmd["command"]
                self.somethingChanged.emit()

            templatesMenu = QMenu("Templates", self)
            for k, cmd in self.templates.items():
                templatesMenu.addAction(k, lambda cmd=cmd:setCommand(cmd))
            menu.addMenu(templatesMenu)

        menu.popup(event.globalPos())

    def editLabel(self):
        newName, ok = QInputDialog.getText(self, "Rename", "New label", QLineEdit.Normal, self.buttonWidget.text())
        if ok:
            self.buttonWidget.setText(newName)
            self.somethingChanged.emit()

    def editCommand(self):
        def save(text):
            self.buttonCommand = text
            self.somethingChanged.emit()
        
        words = list(self.executor("").keys())
        
        editText = EditTextDialog(self.buttonCommand, title="Edit command", placeholder="Your python command...", words=words, python=True)
        editText.saved.connect(save)
        editText.show()

    def buttonClicked(self):
        if self.buttonCommand:
            def f():
                env = {"value": smartConversion(self.textWidget.text().strip())}
                outEnv = self.executor(self.buttonCommand, env)
                self.value = outEnv["value"]
                self.textWidget.setText(fromSmartConversion(self.value))
                self.somethingChanged.emit()

            f()

    def getJsonData(self):
        return {"value": self.value,
                "buttonCommand": self.buttonCommand,
                "buttonLabel": self.buttonWidget.text(),
                "default": "value"}

    def setJsonData(self, data):
        self.value = data["value"]
        with blockedWidgetContext(self.textWidget) as w:
            w.setText(fromSmartConversion(self.value))

        self.buttonCommand = data["buttonCommand"]
        self.buttonWidget.setText(data["buttonLabel"])
        self.colorizeValue()

class ListBoxItem(QListWidgetItem):
    ValueRole = Qt.UserRole + 1

    def __init__(self, value):
        super().__init__()
        self._value = value
        self.setFlags(self.flags() | Qt.ItemIsEditable)

    def clone(self):
        return ListBoxItem(copyJson(self._value))
    
    def data(self, role):
        if role == Qt.ForegroundRole:
            return jsonColor(self._value)
        
        elif role == Qt.DisplayRole:
            return fromSmartConversion(self._value)
        
        elif role == Qt.EditRole:
            return fromSmartConversion(self._value) # always edit as string
        
        elif role == ListBoxItem.ValueRole:
            return self._value
        
        return super().data(role)

    def setData(self, role, value):
        if role == Qt.EditRole:
            self._value = smartConversion(value)

        elif role == ListBoxItem.ValueRole:
            self._value = value

        super().setData(role, value)

class ListBoxTemplateWidget(TemplateWidget):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)

        layout = QVBoxLayout()
        self.setLayout(layout)
        layout.setContentsMargins(QMargins())

        self.listWidget = QListWidget()
        self.listWidget.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.listWidget.itemSelectionChanged.connect(self.somethingChanged.emit)
        self.listWidget.itemChanged.connect(self.itemChanged)
        self.listWidget.contextMenuEvent = self.listContextMenuEvent

        layout.addWidget(self.listWidget, alignment=Qt.AlignLeft|Qt.AlignTop)

    def listContextMenuEvent(self, event):
        menu = QMenu(self)

        menu.addAction("Append", self.appendItem)
        menu.addAction("Remove", self.removeItem)
        menu.addAction("Edit", self.editItems)

        def f():
            self.listWidget.sortItems()
            self.somethingChanged.emit()
        menu.addAction("Sort", f)

        menu.addSeparator()
        
        if DCC in ["maya"]:
            dccLabel = DCC.capitalize()
            menu.addAction("Get selected from "+dccLabel, Callback(self.getFromDCC, False))
            menu.addAction("Add selected from "+dccLabel, Callback(self.getFromDCC, True))
            menu.addAction("Select in "+dccLabel, Callback(self.selectInDCC, False))
            menu.addAction("Select all in "+dccLabel, self.selectInDCC)

        menu.addSeparator()
        menu.addAction("Clear", self.clearItems)

        menu.popup(event.globalPos())

    def itemChanged(self, item):
        self.listWidget.closePersistentEditor(item)
        self.somethingChanged.emit()
        self.resizeWidget()

    def editItems(self):
        def save(newData):
            self.setItems(newData)
            self.resizeWidget()            

        data = self.getItems()
        w = EditJsonDialog(data, title="Edit items")
        w.saved.connect(save)
        w.show()        

    def resizeWidget(self):
        width = self.listWidget.sizeHintForColumn(0) + 50
        height = 0
        for i in range(self.listWidget.count()):
            height += self.listWidget.sizeHintForRow(i)
        height += 2*self.listWidget.frameWidth() + 50
        self.listWidget.setFixedSize(clamp(width, 100, 500), clamp(height, 100, 500))

    def selectInDCC(self, allItems=True):
        items = [self.listWidget.item(i).text() for i in range(self.listWidget.count()) if allItems or self.listWidget.item(i).isSelected()]

        if DCC == "maya":
            cmds.select(items)

    def getFromDCC(self, add=False):
        def updateUI(nodes):
            if not add:
                with blockedWidgetContext(self.listWidget) as w:
                    w.clear()

            for n in nodes:
                self.listWidget.addItem(ListBoxItem(n))

            self.resizeWidget()
            self.somethingChanged.emit()

        if DCC == "maya":
            nodes = [n for n in cmds.ls(sl=True)]
            updateUI(nodes)

    def clearItems(self):
        ok = QMessageBox.question(self, "Rig Builder", "Really clear all items?", QMessageBox.Yes and QMessageBox.No, QMessageBox.Yes) == QMessageBox.Yes
        if ok:
            with blockedWidgetContext(self.listWidget) as w:
                w.clear()
            self.somethingChanged.emit()
            self.resizeWidget()

    def appendItem(self):
        text = "item%d"%(self.listWidget.count()+1)
        self.listWidget.addItem(ListBoxItem(text))
        self.resizeWidget()
        self.somethingChanged.emit()

    def removeItem(self):
        for item in self.listWidget.selectedItems(): 
            self.listWidget.takeItem(self.listWidget.row(item))
            
        self.resizeWidget()
        self.somethingChanged.emit()

    def getItems(self):
        return [self.listWidget.item(i).data(ListBoxItem.ValueRole) for i in range(self.listWidget.count())]
    
    def setItems(self, items):
        with blockedWidgetContext(self.listWidget) as w:
            w.clear()
            for v in items:
                w.addItem(ListBoxItem(v))

        self.somethingChanged.emit()  

    def getDefaultData(self):
        return {"items": ["a", "b"], "current":0, "selected":[], "default": "items"}

    def getJsonData(self):
        return {"items": self.getItems(),
                "selected": [self.listWidget.row(item) for item in self.listWidget.selectedItems()],
                "default": "items"}

    def setJsonData(self, value):
        self.setItems(value["items"])

        with blockedWidgetContext(self.listWidget) as w:
            for i in value.get("selected", []):
                item = w.item(i)
                if item:
                    item.setSelected(True)

        self.resizeWidget()

class RadioButtonTemplateWidget(TemplateWidget):
    Columns = [2,3,4,5]

    def __init__(self, **kwargs):
        super().__init__(**kwargs)

        self.numColumns = 3

        layout = QGridLayout()
        self.setLayout(layout)
        layout.setContentsMargins(QMargins())

        self.buttonsGroupWidget = QButtonGroup()
        self.buttonsGroupWidget.buttonClicked.connect(self.buttonClicked)

    def contextMenuEvent(self, event):
        menu = QMenu(self)

        menu.addAction("Edit", self.editClicked)

        menu.addSeparator()

        columnsMenu = QMenu("Columns", self)
        for n in RadioButtonTemplateWidget.Columns:
            action = columnsMenu.addAction(str(n) + " columns", Callback(self.setColumns, n))
            if n == self.numColumns:
                action.setCheckable(True)
                action.setChecked(True)
        menu.addMenu(columnsMenu)

        menu.popup(event.globalPos())

    def setColumns(self, n):
        data = self.getJsonData()
        data["columns"] = n
        self.setJsonData(data)
        self.somethingChanged.emit()

    def colorizeButtons(self):
        for b in self.buttonsGroupWidget.buttons():
            b.setStyleSheet("QRadioButton {background-color: #2a6931}" if b.isChecked() else "")

    def buttonClicked(self, b):
        self.colorizeButtons()
        self.somethingChanged.emit()

    def clearButtons(self):
        clearLayout(self.layout())

        for b in self.buttonsGroupWidget.buttons():
            self.buttonsGroupWidget.removeButton(b)

    def editClicked(self):
        items = ";".join([b.text() for b in self.buttonsGroupWidget.buttons()])
        newItems, ok = QInputDialog.getText(self, "Rig Builder", "Items separated with ';'", QLineEdit.Normal, items)
        if ok and newItems:
            data = self.getJsonData()
            data["items"] = [x.strip() for x in newItems.split(";")]
            self.setJsonData(data)
            self.somethingChanged.emit()

    def getDefaultData(self):
        return {"items": ["Helpers", "Run"], "current": 0, "default": "current", "columns": self.numColumns}

    def getJsonData(self):
        return {"items": [b.text() for b in self.buttonsGroupWidget.buttons()],
                "current": self.buttonsGroupWidget.checkedId(),
                "columns": self.numColumns,
                "default": "current"}

    def setJsonData(self, value):
        gridLayout = self.layout()
        self.clearButtons()

        self.numColumns = value["columns"]
        gridLayout.setDefaultPositioning(self.numColumns, Qt.Horizontal)

        for i, item in enumerate(value["items"]):
            button = QRadioButton(item)
            gridLayout.addWidget(button, i//self.numColumns, i%self.numColumns)

            self.buttonsGroupWidget.addButton(button)
            self.buttonsGroupWidget.setId(button, i)

        if value["current"] not in range(len(value["items"])):
            value["current"] = 0

        with blockedWidgetContext(self.buttonsGroupWidget) as w:
            w.buttons()[value["current"]].setChecked(True)
        self.colorizeButtons()

class TableTemplateWidget(TemplateWidget):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)

        layout = QVBoxLayout()
        self.setLayout(layout)
        layout.setContentsMargins(QMargins())

        self.tableWidget = QTableWidget()
        self.tableWidget.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Minimum)

        self.tableWidget.verticalHeader().setSectionsMovable(True)
        self.tableWidget.verticalHeader().sectionMoved.connect(self.sectionMoved)
        self.tableWidget.horizontalHeader().setSectionsMovable(True)
        self.tableWidget.horizontalHeader().sectionMoved.connect(self.sectionMoved)

        self.tableWidget.contextMenuEvent = self.tableContextMenuEvent
        self.tableWidget.itemChanged.connect(self.tableItemChanged)

        header = self.tableWidget.horizontalHeader()
        if "setResizeMode" in dir(header):
            header.setResizeMode(QHeaderView.ResizeToContents)
        elif "setSectionResizeMode" in dir(header):
            header.setSectionResizeMode(QHeaderView.ResizeToContents)

        self.tableWidget.horizontalHeader().sectionDoubleClicked.connect(self.sectionDoubleClicked)

        layout.addWidget(self.tableWidget)

    def sectionMoved(self, idx, oldIndex, newIndex):
        self.somethingChanged.emit()

    def tableItemChanged(self, item):
        item.setForeground(jsonColor(smartConversion(item.text())))
        self.somethingChanged.emit()

    def sectionDoubleClicked(self, column):
        newName, ok = QInputDialog.getText(self, "Rename", "New name", QLineEdit.Normal, self.tableWidget.horizontalHeaderItem(column).text())
        if ok:
            self.tableWidget.horizontalHeaderItem(column).setText(newName)
            self.somethingChanged.emit()

    def tableContextMenuEvent(self, event):
        menu = QMenu(self)

        menu.addAction("Duplicate", self.duplicateRow)

        menu.addSeparator()

        rowMenu = QMenu("Row", self)
        rowMenu.addAction("Insert", Callback(self.insertRow, self.tableWidget.currentRow()))
        rowMenu.addAction("Append", Callback(self.insertRow, self.tableWidget.currentRow()+1))

        rowMenu.addSeparator()

        def f():
            for item in self.tableWidget.selectedItems():
                self.tableWidget.removeRow(self.tableWidget.row(item))
            self.resizeWidget()
            self.somethingChanged.emit()
        rowMenu.addAction("Remove", f)

        menu.addMenu(rowMenu)

        columnMenu = QMenu("Column", self)
        columnMenu.addAction("Insert", Callback(self.insertColumn, self.tableWidget.currentColumn()))
        columnMenu.addAction("Append", Callback(self.insertColumn, self.tableWidget.currentColumn()+1))

        columnMenu.addSeparator()

        def f():
            for item in self.tableWidget.selectedItems():
                self.tableWidget.removeColumn(self.tableWidget.column(item))
            self.resizeWidget()
            self.somethingChanged.emit()

        columnMenu.addAction("Remove", f)
        menu.addMenu(columnMenu)
        menu.addSeparator()
        menu.addAction("Clear", self.clearAll)

        menu.popup(event.globalPos())

    def resizeWidget(self):
        height = 0
        for i in range(self.tableWidget.rowCount()):
            height += self.tableWidget.rowHeight(i)

        headerHeight = self.tableWidget.verticalHeader().sizeHint().height()
        height += headerHeight*2
        self.tableWidget.setFixedHeight(clamp(height, headerHeight+100, 500))

    def clearAll(self):
        ok = QMessageBox.question(self, "Rig Builder", "Really remove all items?", QMessageBox.Yes and QMessageBox.No, QMessageBox.Yes) == QMessageBox.Yes
        if ok:
            self.tableWidget.clearContents()
            self.tableWidget.setRowCount(1)
            self.resizeWidget()
            self.somethingChanged.emit()

    def insertColumn(self, current):
        self.tableWidget.insertColumn(current)
        self.tableWidget.setHorizontalHeaderItem(current, QTableWidgetItem("Untitled"))
        for r in range(self.tableWidget.rowCount()):
            self.tableWidget.setItem(r, current, QTableWidgetItem())
        self.resizeWidget()

    def insertRow(self, current):
        self.tableWidget.insertRow(current)
        for c in range(self.tableWidget.columnCount()):
            self.tableWidget.setItem(current, c, QTableWidgetItem())
        self.resizeWidget()

    def duplicateRow(self):
        newRow = self.tableWidget.currentRow()+1
        prevRow = self.tableWidget.currentRow()
        self.tableWidget.insertRow(newRow)

        for c in range(self.tableWidget.columnCount()):
            prevItem = self.tableWidget.item(prevRow, c)
            self.tableWidget.setItem(newRow, c, prevItem.clone() if prevItem else QTableWidgetItem())

        self.resizeWidget()

    def getDefaultData(self):
        return {"items": [("a", "1")], "header": ["name", "value"], "default": "items"}

    def getJsonData(self):
        sortedColumns = sorted([c for c in range(self.tableWidget.columnCount())], key=lambda c: self.tableWidget.visualColumn(c))
        header = [self.tableWidget.horizontalHeaderItem(c).text() for c in sortedColumns]

        vheader = self.tableWidget.verticalHeader()
        hheader = self.tableWidget.horizontalHeader()

        items = []
        for r in range(self.tableWidget.rowCount()):
            row = []
            for c in range(self.tableWidget.columnCount()):
                item = self.tableWidget.item(vheader.logicalIndex(r), hheader.logicalIndex(c))
                row.append(smartConversion(item.text()) if item else "")

            items.append(row)

        return {"items": items, "header": header, "default": "items"}

    def setJsonData(self, value):
        self.tableWidget.setColumnCount(len(value["header"]))
        self.tableWidget.setHorizontalHeaderLabels(value["header"])

        items = value["items"]
        self.tableWidget.setRowCount(len(items))
        for r, row in enumerate(items):
            for c in range(len(value["header"])): # fill each column
                if c < len(row):
                    data = row[c]
                    item = QTableWidgetItem(fromSmartConversion(data))
                    item.setForeground(jsonColor(data))
                else:
                    item = QTableWidgetItem()
                self.tableWidget.setItem(r, c, item)

        self.tableWidget.resizeRowsToContents()
        self.resizeWidget()

class TextTemplateWidget(TemplateWidget):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)

        layout = QVBoxLayout()
        self.setLayout(layout)
        layout.setContentsMargins(QMargins())

        self.textWidget = QTextEdit()
        self.textWidget.textChanged.connect(lambda _=None: self.somethingChanged.emit())

        incSizeBtn = QPushButton("+")
        incSizeBtn.setFixedSize(25, 25)
        incSizeBtn.clicked.connect(self.incSize)
        decSizeBtn = QPushButton("-")
        decSizeBtn.setFixedSize(25, 25)
        decSizeBtn.clicked.connect(self.decSize)

        hlayout = QHBoxLayout()
        hlayout.addWidget(decSizeBtn)
        hlayout.addWidget(incSizeBtn)
        hlayout.addStretch()

        layout.addLayout(hlayout)
        layout.addWidget(self.textWidget)
        layout.addStretch()

    def incSize(self):
        self.textWidget.setFixedHeight(self.textWidget.height() + 50)
        self.somethingChanged.emit()

    def decSize(self):
        self.textWidget.setFixedHeight(self.textWidget.height() - 50)
        self.somethingChanged.emit()

    def getDefaultData(self):
        return {"text": "", "height": 200, "default": "text"}

    def getJsonData(self):
        return {"text": self.textWidget.toPlainText().strip(),
                "height": self.textWidget.height(),
                "default": "text"}

    def setJsonData(self, data):
        with blockedWidgetContext(self.textWidget) as w:
            w.setPlainText(data["text"])
            w.setFixedHeight(data.get("height", self.getDefaultData()["height"]))

class VectorTemplateWidget(TemplateWidget):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)

        self.vectorDim = 3
        self.numColumns = 3
        self.precision = 4
        self.widgets = []

        layout = QGridLayout()        
        self.setLayout(layout)
        layout.setContentsMargins(QMargins())

        self.setJsonData(self.getDefaultData())

    def createMenu(self):
        menu = QMenu(self)

        vectorDimMenu = menu.addMenu("Dimension")
        for size in range(2, 17):
            action = vectorDimMenu.addAction(str(size)+"D", Callback(self.setSizes, size, self.numColumns))
            if size == self.vectorDim:
                action.setCheckable(True)
                action.setChecked(True)

        numColumnsMenu = menu.addMenu("Columns")        
        for size in range(2, 8):
            action = numColumnsMenu.addAction(str(size), Callback(self.setSizes, self.vectorDim, size))
            if size == self.numColumns:
                action.setCheckable(True)
                action.setChecked(True)

        precisionMenu = menu.addMenu("Precision")        
        for n in range(0, 8):
            action = precisionMenu.addAction(str(n), Callback(self.setPrecision, n))
            if n == self.precision:
                action.setCheckable(True)
                action.setChecked(True)

        return menu

    def contextMenuEvent(self, event):
        menu = self.createMenu()
        menu.popup(event.globalPos())

    def setSizes(self, vectorDim, numColumns):
        self.vectorDim = vectorDim
        self.numColumns = numColumns
        self.setJsonData(self.getJsonData())
        self.somethingChanged.emit()

    def setPrecision(self, prec):
        self.precision = prec
        self.setJsonData(self.getJsonData())
        self.somethingChanged.emit()

    def getDefaultData(self):
        return {"value": [0.0, 0.0, 0.0], "default": "value", "dimension": self.vectorDim, "columns": self.numColumns, "precision": self.precision}

    def getJsonData(self):
        return {"value": [float(w.text() or 0.0) for w in self.widgets], 
                "default": "value", 
                "dimension": self.vectorDim,
                "precision": self.precision,
                "columns": self.numColumns}

    def setJsonData(self, value):
        def widgetContextMenu(event, w):            
            stdMenu = w.createStandardContextMenu()
            stdMenu.addSeparator()

            menu = self.createMenu()            
            for a in menu.actions():
                stdMenu.addAction(a)
            stdMenu.popup(event.globalPos())

        for w in self.widgets:
            w.hide()

        self.widgets = []

        layout = self.layout()
        clearLayout(layout)

        self.numColumns = value.get("columns", self.numColumns)
        layout.setDefaultPositioning(self.numColumns, Qt.Horizontal)

        self.vectorDim = value.get("dimension", self.vectorDim)
        self.precision = value.get("precision", self.precision)

        validator = QDoubleValidator()
        validator.setDecimals(self.precision)        
        
        for i in range(self.vectorDim):
            v = value["value"][i] if i < len(value["value"]) else 0.0
            widget = QLineEdit(str(round(v, self.precision)))
            widget.setValidator(validator)
            widget.editingFinished.connect(self.somethingChanged.emit)
            widget.contextMenuEvent = lambda event, w=widget: widgetContextMenu(event, w)
            layout.addWidget(widget, i//self.numColumns, i%self.numColumns)
            self.widgets.append(widget)

def listLerp(lst1, lst2, w):    
    return [p1*(1-w) + p2*w for p1, p2 in zip(lst1, lst2)]

def evaluateBezierCurve(cvs, param):
    param = clamp(param, 0, 1)
    absParam = param * (math.floor((len(cvs) + 2) / 3.0) - 1)

    offset = int(math.floor(absParam - 1e-5))
    if offset < 0:
        offset = 0

    t = absParam - offset

    p1 = cvs[offset * 3]
    p2 = cvs[offset * 3 + 1]
    p3 = cvs[offset * 3 + 2]
    p4 = cvs[offset * 3 + 3]

    return evaluateBezier(p1, p2, p3, p4, t)

def evaluateBezier(p1, p2, p3, p4, param): # De Casteljau's algorithm
    p1_p2 = listLerp(p1, p2, param)
    p2_p3 = listLerp(p2, p3, param)
    p3_p4 = listLerp(p3, p4, param)

    p1_p2_p2_p3 = listLerp(p1_p2, p2_p3, param)
    p2_p3_p3_p4 = listLerp(p2_p3, p3_p4, param)
    return listLerp(p1_p2_p2_p3, p2_p3_p3_p4, param)

def bezierSplit(p1, p2, p3, p4, at=0.5):
    p1_p2 = listLerp(p1, p2, at)
    p2_p3 = listLerp(p2, p3, at)
    p3_p4 = listLerp(p3, p4, at)

    p1_p2_p2_p3 = listLerp(p1_p2, p2_p3, at)
    p2_p3_p3_p4 = listLerp(p2_p3, p3_p4, at)
    p = listLerp(p1_p2_p2_p3, p2_p3_p3_p4, at)

    return (p1, p1_p2, p1_p2_p2_p3, p), (p, p2_p3_p3_p4, p3_p4, p4)

def findFromX(p1, p2, p3, p4, x, *, epsilon=1e-3):
    cvs1, cvs2 = bezierSplit(p1, p2, p3, p4)
    midp = cvs2[0]

    if abs(midp[0] - x) < epsilon:
        return midp
    elif x < midp[0]:
        return findFromX(cvs1[0], cvs1[1], cvs1[2], cvs1[3], x, epsilon=epsilon)
    else:
        return findFromX(cvs2[0], cvs2[1], cvs2[2], cvs2[3], x, epsilon=epsilon)

def evaluateBezierCurveFromX(cvs, x, *, epsilon=1e-3):
    x = clamp(x, 0, 1)

    for i in range(0, len(cvs), 3):
        if cvs[i][0] > x:
            break

    return findFromX(cvs[i-3], cvs[i-2], cvs[i-1], cvs[i], x, epsilon=epsilon)

def normalizedPoint(p, minX, maxX, minY, maxY):
    x = (p[0] - minX) / (maxX - minX)
    y = (p[1] - minY) / (maxY - minY)
    return [x, y]

class CurvePointItem(QGraphicsItem):
    Size = 10
    def __init__(self, **kwargs):
        super().__init__(**kwargs)

        self.setFlags(QGraphicsItem.ItemIsMovable | QGraphicsItem.ItemIsSelectable | QGraphicsItem.ItemSendsGeometryChanges)

        self.fixedX = None

    def boundingRect(self):
        size = CurvePointItem.Size
        return QRectF(-size/2, -size/2, size, size)

    def paint(self, painter, option, widget):
        size = CurvePointItem.Size

        if self.isSelected():
            painter.setBrush(QBrush(QColor(100, 200, 100)))

        painter.setPen(QColor(250, 250, 250))
        painter.drawRect(-size/2, -size/2, size, size)

    def itemChange(self, change, value):
        if not self.scene():
            return super().itemChange(change, value)

        if change == QGraphicsItem.GraphicsItemChange.ItemPositionChange:
            if self.fixedX is not None:
                value.setX(self.fixedX)

            if CurveScene.MaxX > 0:
                if value.x() < 0:
                    value.setX(0)

                elif value.x() > CurveScene.MaxX:
                    value.setX(CurveScene.MaxX)

            else:
                if value.x() > 0:
                    value.setX(0)

                elif value.x() < CurveScene.MaxX:
                    value.setX(CurveScene.MaxX)
            # y
            if CurveScene.MaxY > 0:
                if value.y() < 0:
                    value.setY(0)

                elif value.y() > CurveScene.MaxY:
                    value.setY(CurveScene.MaxY)

            else:
                if value.y() > 0:
                    value.setY(0)

                elif value.y() < CurveScene.MaxY:
                    value.setY(CurveScene.MaxY)

        return super().itemChange(change, value)

class CurveScene(QGraphicsScene):
    MaxX = 300
    MaxY = -100
    DrawCurveSamples = 33
    def __init__(self, **kwargs):
        super().__init__(**kwargs)

        self.cvs = []

        item1 = CurvePointItem()
        item1.setPos(0, CurveScene.MaxY)
        item1.fixedX = 0
        self.addItem(item1)

        item2 = CurvePointItem()
        item2.setPos(CurveScene.MaxX / 2, 0)
        self.addItem(item2)

        item3 = CurvePointItem()
        item3.fixedX = CurveScene.MaxX
        item3.setPos(CurveScene.MaxX, CurveScene.MaxY)
        self.addItem(item3)

    def mouseDoubleClickEvent(self, event):
        pos = event.scenePos()

        if CurveScene.MaxX > 0 and (pos.x() < 0 or pos.x() > CurveScene.MaxX):
            return

        if CurveScene.MaxX < 0 and (pos.x() > 0 or pos.x() < CurveScene.MaxX):
            return

        if CurveScene.MaxY > 0 and (pos.y() < 0 or pos.y() > CurveScene.MaxY):
            return

        if CurveScene.MaxY < 0 and (pos.y() > 0 or pos.y() < CurveScene.MaxY):
            return

        item = CurvePointItem()
        item.setPos(pos)
        self.addItem(item)

    def mousePressEvent(self, event):
        self._oldCvs = self.cvs[:]

        if event.button() == Qt.RightButton:
            for item in self.selectedItems():
                if item.fixedX is None: # don't remove tips
                    self.removeItem(item)

            event.accept()
        else:
            super().mousePressEvent(event)

    def mouseReleaseEvent(self, event):
        super().mouseReleaseEvent(event)

        self.calculateCVs()

        if self.cvs != self._oldCvs:
            for view in self.views():
                if type(view) == CurveView:
                    view.somethingChanged.emit()

    def calculateCVs(self):
        self.cvs = []

        if len(self.items()) < 2:
            return

        items = sorted(self.items(), key=lambda item: item.pos().x()) # sorted by x position

        tangents = []
        for i, _ in enumerate(items): # calculate tangents
            if i == 0:
                tg = QVector2D(items[i+1].pos() - items[i].pos()).normalized()
            elif i == len(items) - 1:
                tg = QVector2D(items[i].pos() - items[i-1].pos()).normalized()
            else:
                prevy = items[i-1].pos().y()
                nexty = items[i+1].pos().y()
                y = items[i].pos().y()
                if (y > prevy and y > nexty) or (y < prevy and y < nexty):
                    w = 1
                else:
                    d1 = abs(y - prevy)
                    d2 = abs(y - nexty)
                    s = d1 + d2 + 1e-5
                    w1 = d1 / s
                    w2 = d2 / s
                    w = max(w1, w2)*2 - 1 # from 0 to 1, because max(w1,w2) is always >= 0.5
                    w = w ** 4
                tg = QVector2D(items[i+1].pos() - items[i-1].pos()).normalized() * (1-w) + QVector2D(1, 0) * w

            tangents.append(tg)

        for i, _ in enumerate(items):
            if i == 0:
                continue

            p1 = items[i-1].pos()
            p4 = items[i].pos()

            d = (p4.x() - p1.x()) / 3
            p2 = p1 + tangents[i-1].toPointF() * d
            p3 = p4 - tangents[i].toPointF() * d

            self.cvs.append(normalizedPoint([p1.x(), p1.y()], 0, CurveScene.MaxX, 0, CurveScene.MaxY))
            self.cvs.append(normalizedPoint([p2.x(), p2.y()], 0, CurveScene.MaxX, 0, CurveScene.MaxY))
            self.cvs.append(normalizedPoint([p3.x(), p3.y()], 0, CurveScene.MaxX, 0, CurveScene.MaxY))

        self.cvs.append(normalizedPoint([p4.x(), p4.y()], 0, CurveScene.MaxX, 0, CurveScene.MaxY))

    def drawBackground(self, painter, rect):
        painter.fillRect(QRect(0,0,CurveScene.MaxX,CurveScene.MaxY), QColor(140, 140, 140))
        painter.setPen(QColor(0, 0, 0))
        painter.drawRect(QRect(0,0,CurveScene.MaxX,CurveScene.MaxY))

        self.calculateCVs()

        font = painter.font()
        setFontSize(font, fontSize(font) - 4)        
        painter.setFont(font)

        GridSize = 4
        TextOffset = 3
        xstep = CurveScene.MaxX / GridSize
        ystep = CurveScene.MaxY / GridSize

        for i in range(GridSize):
            painter.setPen(QColor(40,40,40, 70))
            painter.drawLine(i*xstep, 0, i*xstep, CurveScene.MaxY)
            painter.drawLine(0, i*ystep, CurveScene.MaxX, i*ystep)

            painter.setPen(QColor(0, 0, 0))

            v = "%.2f"%(i/float(GridSize))
            painter.drawText(i*xstep + TextOffset, -TextOffset, v) # X axis

            if i > 0:
                painter.drawText(TextOffset, i*ystep - TextOffset, v) # Y axis

        xFactor = 1.0 / CurveScene.MaxX
        yFactor = 1.0 / CurveScene.MaxY

        if not self.cvs:
            return

        pen = QPen()
        pen.setWidth(2)
        pen.setColor(QColor(40,40,150))
        painter.setPen(pen)

        path = QPainterPath()

        p = normalizedPoint(evaluateBezierCurve(self.cvs, 0), 0, xFactor, 0, yFactor)
        path.moveTo(p[0], p[1])

        N = CurveScene.DrawCurveSamples
        for i in range(N):
            param = i / float(N - 1)
            p = normalizedPoint(evaluateBezierCurve(self.cvs, param), 0, xFactor, 0, yFactor)

            path.lineTo(p[0], p[1])
            path.moveTo(p[0], p[1])

        p = normalizedPoint(evaluateBezierCurve(self.cvs, 1), 0, xFactor, 0, yFactor)
        path.lineTo(p[0], p[1])

        painter.drawPath(path)

class CurveView(QGraphicsView):
    somethingChanged = Signal()

    def __init__(self, **kwargs):
        super().__init__(**kwargs)

        self.setRenderHint(QPainter.Antialiasing, True)
        self.setRenderHint(QPainter.TextAntialiasing, True)
        self.setViewportUpdateMode(QGraphicsView.FullViewportUpdate)
        self.setTransformationAnchor(QGraphicsView.AnchorUnderMouse)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)

        self.setScene(CurveScene())

    def contextMenuEvent(self, event):
        event.accept()

    def resizeEvent(self, event):
        self.fitInView(self.scene().sceneRect(), Qt.KeepAspectRatio)

class CurveTemplateWidget(TemplateWidget):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)

        layout = QVBoxLayout()
        layout.setContentsMargins(QMargins())
        self.setLayout(layout)

        self.curveView = CurveView()
        self.curveView.somethingChanged.connect(self.somethingChanged.emit)
        layout.addWidget(self.curveView)

    def getDefaultData(self):
        return {'default': 'cvs', 'cvs': [[0.0, 1.0], [0.13973423457023273, 0.722154453101879], 
                                          [0.3352803473835302, -0.0019584480764515554], [0.5029205210752953, -0.0], 
                                          [0.6686136807168636, 0.0019357021806590401], [0.8623842449806401, 0.7231513901834298], [1.0, 1.0]]}

    def getJsonData(self):
        return {"cvs": self.curveView.scene().cvs, "default": "cvs"}

    def setJsonData(self, value):
        scene = self.curveView.scene()
        scene.clear()

        for i, (x, y) in enumerate(value["cvs"]):
            if i % 3 == 0: # ignore tangents
                item = CurvePointItem()
                item.setPos(x * CurveScene.MaxX, y * CurveScene.MaxY)
                scene.addItem(item)

                if i == 0 or i == len(value["cvs"]) - 1:
                    item.fixedX = item.pos().x()

class JsonTemplateWidget(TemplateWidget):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)

        layout = QVBoxLayout()
        self.setLayout(layout)
        layout.setContentsMargins(QMargins())

        self.jsonWidget = JsonWidget()
        self.jsonWidget.itemChanged.connect(lambda _,__:self.somethingChanged.emit())
        self.jsonWidget.itemMoved.connect(lambda _:self.somethingChanged.emit())
        self.jsonWidget.itemAdded.connect(lambda _:self.somethingChanged.emit())
        self.jsonWidget.itemRemoved.connect(lambda _:self.somethingChanged.emit())
        self.jsonWidget.dataLoaded.connect(self.somethingChanged.emit)
        self.jsonWidget.cleared.connect(self.somethingChanged.emit)
        self.jsonWidget.readOnlyChanged.connect(lambda _: self.somethingChanged.emit())
        self.jsonWidget.rootChanged.connect(lambda _: self.updateInfoLabel())
        self.jsonWidget.itemClicked.connect(lambda _: self.updateInfoLabel())

        incSizeBtn = QPushButton("+")
        incSizeBtn.setFixedSize(25, 25)
        incSizeBtn.clicked.connect(self.incSize)
        decSizeBtn = QPushButton("-")
        decSizeBtn.setFixedSize(25, 25)
        decSizeBtn.clicked.connect(self.decSize)

        self.infoLabel = QLabel()

        hlayout = QHBoxLayout()
        hlayout.addWidget(decSizeBtn)
        hlayout.addWidget(incSizeBtn)
        hlayout.addStretch()
        hlayout.addWidget(self.infoLabel)

        layout.addLayout(hlayout)
        layout.addWidget(self.jsonWidget)
        layout.addStretch()

    def updateInfoLabel(self):
        rootIndex = self.jsonWidget.rootIndex()
        root = self.jsonWidget.itemFromIndex(rootIndex).getPath() if rootIndex != QModelIndex() else ""

        item = self.jsonWidget.selectedItem()
        path = item.getPath() if item else ""
        self.infoLabel.setText("Root:{} Path:{}".format(root, path.replace(root,"")))

    def incSize(self):
        self.jsonWidget.setFixedHeight(self.jsonWidget.height() + 50)
        self.somethingChanged.emit()

    def decSize(self):
        self.jsonWidget.setFixedHeight(self.jsonWidget.height() - 50)
        self.somethingChanged.emit()

    def getDefaultData(self):
        return {"data": [{"a": 1, "b": 2}], "height":200, "readonly": False, "default": "data"}

    def getJsonData(self):
        return {"data": self.jsonWidget.toJsonList(), 
                "height":self.jsonWidget.height(),
                "readonly": self.jsonWidget.isReadOnly(),
                "default": "data"}

    def setJsonData(self, value):
        self.jsonWidget.setFixedHeight(value["height"])
        with blockedWidgetContext(self.jsonWidget) as w:
            w.clear()
            w.loadFromJsonList(value["data"])
            w.setReadOnly(value["readonly"])

class EditCompountWidgetsDialog(QDialog):
    saved = Signal(list) # [(template, data), ...]

    def __init__(self, compoundWidget, **kwargs):
        super().__init__(**kwargs)

        self.compoundWidget = compoundWidget

        self.setWindowTitle("Edit widgets")
        self.setGeometry(100, 100, 300, 400)

        layout = QVBoxLayout()
        self.setLayout(layout)

        self.listWidget = QListWidget()
        self.listWidget.setDragEnabled(True)
        self.listWidget.setDragDropMode(QAbstractItemView.InternalMove)
        self.listWidget.contextMenuEvent = self.listContextMenuEvent
        self.listWidget.setDropIndicatorShown(True)
        self.listWidget.setIconSize(QSize(64, 64))

        for w in compoundWidget.getWidgets():
            self.listWidget.addItem(self.itemFromWidget(w))

        saveBtn = QPushButton("Save")
        saveBtn.clicked.connect(self.save)

        layout.addWidget(self.listWidget)
        layout.addWidget(saveBtn)

        centerWindow(self)

    def listContextMenuEvent(self, event):
        menu = QMenu(self)

        addMenu = menu.addMenu("Add")
        for template in TemplateWidgets:
            w = TemplateWidgets[template]()
            w.setJsonData(w.getDefaultData())
            w.template = template
            addMenu.addAction(template, Callback(self.listWidget.addItem, self.itemFromWidget(w)))

        menu.addAction("Remove", lambda: self.listWidget.takeItem(self.listWidget.currentRow()))
        menu.addAction("Clear", self.listWidget.clear)    
        menu.popup(event.globalPos())

    def itemFromWidget(self, w):
        item = QListWidgetItem()
        item.setIcon(QIcon(QPixmap.grabWidget(w)))
        item.setText(w.template)
        item.setData(Qt.UserRole, w.getJsonData())        
        return item
    
    def save(self):
        widgetsData = []
        for i in range(self.listWidget.count()):
            item = self.listWidget.item(i)
            data = item.data(Qt.UserRole)
            template = item.text()
            widgetsData.append((template, data))

        self.saved.emit(widgetsData)
        self.accept()

class CompoundTemplateWidget(TemplateWidget):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)

        layout = QHBoxLayout()
        self.setLayout(layout)
        layout.setContentsMargins(QMargins())

    def contextMenuEvent(self, event):
        menu = QMenu(self)
        menu.addAction("Edit widgets", self.editWidgets)
        menu.popup(event.globalPos())

    def editWidgets(self):
        def saveWidgets(widgetsData):
            clearLayout(self.layout())
            
            templates, widgets, values = [], [], []            
            for template, d in widgetsData:
                templates.append(template)
                widgets.append(d)
                values.append(d[d["default"]])

            self.setJsonData({"templates": templates, "widgets": widgets, "values": values, "default": "values"})
            self.somethingChanged.emit()

        dlg = EditCompountWidgetsDialog(self)
        dlg.saved.connect(saveWidgets)
        dlg.exec_()

    def getWidgets(self):
        layout = self.layout()
        widgets = []
        for i in range(layout.count()):
            w = layout.itemAt(i).widget()
            if w:                
                widgets.append(w)
        return widgets

    def getDefaultData(self):
        d1 = ListBoxTemplateWidget().getDefaultData()
        d2 = ButtonTemplateWidget().getDefaultData()
        return {"widgets": [d1, d2], "values": [d1[d1["default"]], d2[d2["default"]]], "templates":["listBox", "button"], "default": "values"}

    def getJsonData(self):
        values, widgets, templates = [], [], []
        for w in self.getWidgets():
            d = w.getJsonData()
            templates.append(w.template)
            values.append(d[d["default"]])
            widgets.append(d)
        return {"templates": templates, "widgets": widgets, "values": values, "default": "values"}

    def setJsonData(self, value):
        layout = self.layout()

        widgets = value["widgets"]
        templates = value["templates"]
        values = value["values"]

        clearLayout(layout)
        for i in range(len(widgets)):
            w = TemplateWidgets[templates[i]](executor=self.executor)
            w.template = templates[i]

            d = dict(widgets[i])
            d[d["default"]] = values[i]
            w.setJsonData(d)

            w.somethingChanged.connect(self.somethingChanged.emit)

            layout.addWidget(w, alignment=Qt.AlignTop)
            layout.addSpacing(5)

        layout.addStretch()

TemplateWidgets = {
    "button": ButtonTemplateWidget,
    "checkBox": CheckBoxTemplateWidget,
    "comboBox": ComboBoxTemplateWidget,
    "curve": CurveTemplateWidget,
    "compound": CompoundTemplateWidget,
    "json": JsonTemplateWidget,
    "label": LabelTemplateWidget,
    "lineEdit": LineEditTemplateWidget,
    "lineEditAndButton": LineEditAndButtonTemplateWidget,
    "listBox": ListBoxTemplateWidget,
    "radioButton": RadioButtonTemplateWidget,
    "table": TableTemplateWidget,
    "text": TextTemplateWidget,
    "vector": VectorTemplateWidget}

def curve_evaluate(data, param, *, epsilon=1e-3):
    return evaluateBezierCurve(data["cvs"], param, epsilon=epsilon)

def curve_evaluateFromX(data, param, *, epsilon=1e-3): 
    return evaluateBezierCurveFromX(data["cvs"], param, epsilon=epsilon)

def listBox_setSelected(data, indices):
    data["selected"] = indices

def listBox_selected(data):
    return [data["items"][idx] for idx in data["selected"] if idx < len(data["items"])]    

def comboBox_items(data):
    return data["items"]

def comboBox_setItems(data, items):
    data["items"] = items

def runButtonCommand(module, buttonLabel):
    """Execute button command by label.
    
    Args:
        module: Module object containing attributes
        buttonLabel: Label text of the button to execute
    
    Returns:
        dict: Environment dictionary after execution
    """
    for attr in module.attributes():
        if attr.template() in ["button", "lineEditAndButton"]:
            data = attr.localData()
            if data.get("buttonLabel") == buttonLabel or data.get("label") == buttonLabel:
                command = data.get("buttonCommand") or data.get("command", "")
                if command:
                    env = module.getEnv()
                    if attr.template() == "lineEditAndButton":
                        env["value"] = smartConversion(data.get("value", ""))
                    
                    localEnv = dict(WidgetsAPI)
                    localEnv.update(env)
                    exec(command, localEnv)
                    
                    # Update value for lineEditAndButton
                    if attr.template() == "lineEditAndButton":
                        data["value"] = localEnv.get("value", data.get("value", ""))
                        attr.setData(data)
                    
                    return localEnv
    
    raise ValueError(f"Button with label '{buttonLabel}' not found in module '{module.name()}'")

WidgetsAPI = {
    "listLerp": listLerp,
    "clamp": clamp,
    "smartConversion": smartConversion,
    "fromSmartConversion": fromSmartConversion,

    # data based
    "curve_evaluate": curve_evaluate,
    "curve_evaluateFromX": curve_evaluateFromX,
    "listBox_selected": listBox_selected,
    "listBox_setSelected": listBox_setSelected,
    "comboBox_items": comboBox_items,
    "comboBox_setItems": comboBox_setItems,
    
    # button commands
    "runButtonCommand": runButtonCommand,

    # obsolete
    "evaluateBezierCurve": evaluateBezierCurve,
    "evaluateBezierCurveFromX": evaluateBezierCurveFromX,
}