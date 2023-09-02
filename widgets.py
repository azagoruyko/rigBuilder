from PySide2.QtGui import *
from PySide2.QtCore import *
from PySide2.QtWidgets import *

import sys
import os
import json
import math
import time

if sys.version_info.major > 2:
    RootPath = os.path.dirname(__file__) # Rig Builder root folder
else:
    RootPath = os.path.dirname(__file__.decode(sys.getfilesystemencoding())) # legacy

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
        return str(x)

def fromSmartConversion(x):
    if sys.version_info.major > 2:
        return json.dumps(x) if not isinstance(x, str) else x
    else:
        return json.dumps(x) if type(x) not in [str, unicode] else x

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
        self.outputText = self.textWidget.toPlainText()
        self.accept()

class LabelTemplateWidget(TemplateWidget):
    def __init__(self, **kwargs):
        super(LabelTemplateWidget, self).__init__(**kwargs)

        self.actualText = ""

        layout = QVBoxLayout()
        self.setLayout(layout)
        layout.setContentsMargins(0, 0, 0, 0)

        self.label = QLabel()
        self.label.setCursor(Qt.PointingHandCursor)
        self.label.setWordWrap(True)
        self.label.setToolTip("You can use $ROOT as a path to Rig Builder's root directory, like $ROOT/images/icons")
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

class ButtonTemplateWidget(TemplateWidget):
    def __init__(self, **kwargs):
        super(ButtonTemplateWidget, self).__init__(**kwargs)

        self.buttonCommand = "print('Hello world')"

        layout = QHBoxLayout()
        self.setLayout(layout)
        layout.setContentsMargins(0, 0, 0, 0)

        self.buttonWidget = QPushButton("Press me")
        self.buttonWidget.clicked.connect(self.buttonClicked)
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
                mainWindow.attributesTabWidget.updateTabs()

    def getDefaultData(self):
        return {"command": "a = module.someAttr.get()\nprint(a)",
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
        self.checkBox.setChecked(value["checked"])

class ComboBoxTemplateWidget(TemplateWidget):
    def __init__(self, **kwargs):
        super(ComboBoxTemplateWidget, self).__init__(**kwargs)

        layout = QVBoxLayout()
        self.setLayout(layout)
        layout.setContentsMargins(0, 0, 0, 0)

        self.comboBox = QComboBox()
        self.comboBox.currentIndexChanged.connect(self.somethingChanged)
        self.comboBox.contextMenuEvent = self.comboBoxContextMenuEvent
        layout.addWidget(self.comboBox)

    def comboBoxContextMenuEvent(self, event):
        menu = QMenu(self)

        appendAction = QAction("Append", self)
        appendAction.triggered.connect(self.appendItem)
        menu.addAction(appendAction)

        removeAction = QAction("Remove", self)
        removeAction.triggered.connect(self.removeItem)
        menu.addAction(removeAction)

        editAction = QAction("Edit", self)
        editAction.triggered.connect(self.editItems)
        menu.addAction(editAction)

        menu.addSeparator()

        clearAction = QAction("Clear", self)
        clearAction.triggered.connect(self.clearItems)
        menu.addAction(clearAction)

        menu.popup(event.globalPos())

    def editItems(self):
        items = ";".join([self.comboBox.itemText(i) for i in range(self.comboBox.count())])
        newItems, ok = QInputDialog.getText(self, "Rig Builder", "Items separated with ';'", QLineEdit.Normal, items)
        if ok and newItems:
            self.comboBox.clear()
            self.comboBox.addItems([x.strip() for x in newItems.split(";")])
            self.somethingChanged.emit()

    def clearItems(self):
        ok = QMessageBox.question(self, "Rig Builder", "Really clear all items?", QMessageBox.Yes and QMessageBox.No, QMessageBox.Yes) == QMessageBox.Yes
        if ok:
            self.comboBox.clear()
            self.somethingChanged.emit()

    def appendItem(self):
        name, ok = QInputDialog.getText(self, "Rig Builder", "Name", QLineEdit.Normal, "")
        if ok and name:
            self.comboBox.addItem(name)
            self.somethingChanged.emit()

    def removeItem(self):
        self.comboBox.removeItem(self.comboBox.currentIndex())
        self.somethingChanged.emit()

    def getDefaultData(self):
        return {"items": ["a", "b"], "current": "a", "default": "current"}

    def getJsonData(self):
        return {"items": [self.comboBox.itemText(i) for i in range(self.comboBox.count())],
                "current": self.comboBox.currentText(),
                "default": "current"}

    def setJsonData(self, value):
        self.comboBox.clear()
        self.comboBox.addItems(value["items"])

        if value["current"] in value["items"]:
            self.comboBox.setCurrentIndex(value["items"].index(value["current"]))

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
            env = {"value": self.textWidget.text()}
            exec(self.buttonCommand, env)
            self.setCustomText(env["value"])

            self.somethingChanged.emit()

    def getJsonData(self):
        return {"value": smartConversion(self.textWidget.text().strip()),
                "buttonCommand": self.buttonCommand,
                "buttonLabel": self.buttonWidget.text(),
                "default": "value"}

    def setCustomText(self, value):
        self.textWidget.setText(fromSmartConversion(value))

    def setJsonData(self, data):
        self.setCustomText(data["value"])
        self.buttonCommand = data["buttonCommand"]
        self.buttonWidget.setText(data["buttonLabel"])

class ListBoxTemplateWidget(TemplateWidget):
    def __init__(self, **kwargs):
        super(ListBoxTemplateWidget, self).__init__(**kwargs)

        layout = QVBoxLayout()
        self.setLayout(layout)
        layout.setContentsMargins(0, 0, 0, 0)

        self.listWidget = QListWidget()
        self.listWidget.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.listWidget.itemDoubleClicked.connect(self.itemDoubleClicked)
        #self.listWidget.itemChanged.connect(self.changeCallback)
        #self.listWidget.itemClicked.connect(self.changeCallback)
        self.listWidget.contextMenuEvent = self.listContextMenuEvent

        layout.addWidget(self.listWidget, alignment=Qt.AlignLeft|Qt.AlignTop)
        self.resizeList()

    def listContextMenuEvent(self, event):
        menu = QMenu(self)

        appendAction = QAction("Append", self)
        appendAction.triggered.connect(self.appendClicked)
        menu.addAction(appendAction)

        removeAction = QAction("Remove", self)
        removeAction.triggered.connect(self.removeClicked)
        menu.addAction(removeAction)

        editAction = QAction("Edit", self)
        editAction.triggered.connect(self.editClicked)
        menu.addAction(editAction)

        sortAction = QAction("Sort", self)
        sortAction.triggered.connect(self.listWidget.sortItems)
        menu.addAction(sortAction)

        menu.addSeparator()

        getAction = QAction("Get selected from Maya", self)
        getAction.triggered.connect(lambda: self.getFromMayaClicked(False))
        menu.addAction(getAction)

        addSelectedAction = QAction("Add selected from Maya", self)
        addSelectedAction.triggered.connect(lambda: self.getFromMayaClicked(True))
        menu.addAction(addSelectedAction)

        selectAction = QAction("Select in Maya", self)
        selectAction.triggered.connect(self.selectInMayaClicked)
        menu.addAction(selectAction)

        clearAction = QAction("Clear", self)
        clearAction.triggered.connect(self.clearClicked)
        menu.addAction(clearAction)

        menu.popup(event.globalPos())

    def resizeList(self):
        h = self.listWidget.sizeHintForRow(0) * self.listWidget.count() + 2 * self.listWidget.frameWidth() + 25
        height = clamp(50, 250, h)
        self.listWidget.setMinimumHeight(height)
        self.listWidget.setMaximumHeight(height)

    def editClicked(self):
        items = ";".join([self.listWidget.item(i).text() for i in range(self.listWidget.count())])
        newItems, ok = QInputDialog.getText(self, "Rig Builder", "Items separated with ';'", QLineEdit.Normal, items)
        if ok and newItems:
            self.listWidget.clear()
            self.listWidget.addItems([x.strip() for x in newItems.split(";")])
            self.somethingChanged.emit()

    def selectInMayaClicked(self):
        import pymel.core as pm

        items = [self.listWidget.item(i).text() for i in range(self.listWidget.count())]
        pm.select(items)

    def getFromMayaClicked(self, add=False):
        import pymel.core as pm

        if not add:
            self.listWidget.clear()

        self.listWidget.addItems([n.name() for n in pm.ls(sl=True)])
        self.resizeList()
        self.somethingChanged.emit()

    def clearClicked(self):
        self.listWidget.clear()
        self.resizeList()
        self.somethingChanged.emit()

    def appendClicked(self):
        self.listWidget.addItem("newItem%d"%(self.listWidget.count()+1))
        self.resizeList()
        self.somethingChanged.emit()

    def removeClicked(self):
        self.listWidget.takeItem(self.listWidget.currentRow())
        self.resizeList()
        self.somethingChanged.emit()

    def itemDoubleClicked(self, item):
        newText, ok = QInputDialog.getText(self, "Rig Builder", "New text", QLineEdit.Normal, item.text())
        if ok:
            item.setText(newText)
            self.somethingChanged.emit()

    def getDefaultData(self):
        return {"items": ["a", "b"], "default": "items"}#, "current": self.listWidget.currentRow()}

    def getJsonData(self):
        return {"items": [self.listWidget.item(i).text() for i in range(self.listWidget.count())],
                #"current": self.listWidget.currentRow(),
                "default": "items"}

    def setJsonData(self, value):
        self.listWidget.clear()
        self.listWidget.addItems([str(v) for v in value["items"]])
        #self.listWidget.setCurrentRow(value.get("current", 0))

        self.resizeList()

class RadioButtonTemplateWidget(TemplateWidget):
    Columns = [2,3,4,5]

    def __init__(self, **kwargs):
        super(RadioButtonTemplateWidget, self).__init__(**kwargs)

        layout = QGridLayout()        
        self.setLayout(layout)
        layout.setContentsMargins(0, 0, 0, 0)

        self.buttonsGroupWidget = QButtonGroup()
        self.buttonsGroupWidget.buttonClicked.connect(self.buttonClicked)

    def contextMenuEvent(self, event):
        menu = QMenu(self)

        editAction = QAction("Edit", self)
        editAction.triggered.connect(self.editClicked)
        menu.addAction(editAction)

        menu.addSeparator()

        columnsMenu = QMenu("Columns", self)
        for n in RadioButtonTemplateWidget.Columns:
            action = QAction(str(n) + " columns", self)
            action.triggered.connect(lambda _=None, n=n: self.setColumns(n))
            columnsMenu.addAction(action)
        menu.addMenu(columnsMenu)

        menu.popup(event.globalPos())

    def setColumns(self, n):
        data = self.getJsonData()
        data["columns"] = n
        self.setJsonData(data)
        self.somethingChanged.emit()

    def colorizeButtons(self):
        for b in self.buttonsGroupWidget.buttons():
            b.setStyleSheet("background-color: #2a6931" if b.isChecked() else "")

    def buttonClicked(self, b):
        self.colorizeButtons()
        self.somethingChanged.emit()

    def clearButtons(self):
        gridLayout = self.layout()
        clearLayout(gridLayout)

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
        return {"items": ["Helpers", "Run"], "current": 0, "default": "current", "columns":3}

    def getJsonData(self):
        return {"items": [b.text() for b in self.buttonsGroupWidget.buttons()],
                "current": self.buttonsGroupWidget.checkedId(),
                "columns": self.layout().columnCount(),
                "default": "current"}

    def setJsonData(self, value):
        gridLayout = self.layout()

        self.clearButtons()

        columns = value.get("columns", 3)
        gridLayout.setDefaultPositioning(columns, Qt.Horizontal)

        row = 0
        column = 0
        for i, item in enumerate(value["items"]):
            if i % columns == 0 and i > 0:
                row += 1
                column = 0

            button = QRadioButton(item)
            gridLayout.addWidget(button, row, column)

            self.buttonsGroupWidget.addButton(button)
            self.buttonsGroupWidget.setId(button, i)
            column += 1

        self.buttonsGroupWidget.buttons()[value["current"]].setChecked(True)
        self.colorizeButtons()

class TableTemplateWidget(TemplateWidget):
    def __init__(self, **kwargs):
        super(TableTemplateWidget, self).__init__(**kwargs)

        layout = QVBoxLayout()
        self.setLayout(layout)
        layout.setContentsMargins(0, 0, 0, 0)

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
        self.resizeTable()

    def sectionMoved(self, idx, oldIndex, newIndex):
        self.somethingChanged.emit()

    def tableItemChanged(self, item):
        self.somethingChanged.emit()

    def sectionDoubleClicked(self, column):
        newName, ok = QInputDialog.getText(self, "Rename", "New name", QLineEdit.Normal, self.tableWidget.horizontalHeaderItem(column).text())
        if ok:
            self.tableWidget.horizontalHeaderItem(column).setText(newName.replace(" ", "_"))
            self.somethingChanged.emit()

    def tableContextMenuEvent(self, event):
        menu = QMenu(self)

        duplicateRowAction = QAction("Duplicate", self)
        duplicateRowAction.triggered.connect(lambda _=None: self.duplicateRow())
        menu.addAction(duplicateRowAction)

        menu.addSeparator()

        rowMenu = QMenu("Row", self)
        insertRowAction = QAction("Insert", self)
        insertRowAction.triggered.connect(lambda _=None: self.tableWidget.insertRow(self.tableWidget.currentRow()))
        rowMenu.addAction(insertRowAction)

        appendRowAction = QAction("Append", self)
        appendRowAction.triggered.connect(lambda _=None: self.tableWidget.insertRow(self.tableWidget.currentRow()+1))
        rowMenu.addAction(appendRowAction)

        rowMenu.addSeparator()
        removeRowAction = QAction("Remove", self)
        removeRowAction.triggered.connect(lambda _=None: (self.tableWidget.removeRow(self.tableWidget.currentRow()), self.somethingChanged.emit()))
        rowMenu.addAction(removeRowAction)

        menu.addMenu(rowMenu)

        columnMenu = QMenu("Column", self)
        insertColumnAction = QAction("Insert", self)
        insertColumnAction.triggered.connect(lambda _=None: self.insertColumn(self.tableWidget.currentColumn()))
        columnMenu.addAction(insertColumnAction)

        appendColumnAction = QAction("Append", self)
        appendColumnAction.triggered.connect(lambda _=None: self.insertColumn(self.tableWidget.currentColumn()+1))
        columnMenu.addAction(appendColumnAction)

        columnMenu.addSeparator()

        removeColumnAction = QAction("Remove", self)
        removeColumnAction.triggered.connect(lambda _=None: (self.tableWidget.removeColumn(self.tableWidget.currentColumn()), self.somethingChanged.emit()))
        columnMenu.addAction(removeColumnAction)

        menu.addMenu(columnMenu)

        resizeAction = QAction("Resize", self)
        resizeAction.triggered.connect(lambda _=None: self.updateSize())
        menu.addAction(resizeAction)

        clearAction = QAction("Clear", self)
        clearAction.triggered.connect(self.clearAll)
        menu.addAction(clearAction)

        menu.popup(event.globalPos())

    def updateSize(self):
        self.tableWidget.resizeRowsToContents()
        self.resizeTable()

    def resizeTable(self):
        height = 0
        for i in range(self.tableWidget.rowCount()):
            height += self.tableWidget.verticalHeader().sectionSize(i)

        height += self.tableWidget.horizontalHeader().height() + 25
        self.tableWidget.setMaximumHeight(clamp(50, height, height))

    def clearAll(self):
        ok = QMessageBox.question(self, "Rig Builder", "Really remove all elements?",
                                  QMessageBox.Yes and QMessageBox.No, QMessageBox.Yes) == QMessageBox.Yes
        if ok:
            self.tableWidget.clearContents()
            self.tableWidget.setRowCount(1)
            self.resizeTable()
            self.somethingChanged.emit()

    def insertColumn(self, current):
        self.tableWidget.insertColumn(current)
        self.tableWidget.setHorizontalHeaderItem(current, QTableWidgetItem("Untitled"))

    def duplicateRow(self):
        newRow = self.tableWidget.currentRow()+1
        prevRow = self.tableWidget.currentRow()
        self.tableWidget.insertRow(newRow)

        for c in range(self.tableWidget.columnCount()):
            prevItem = self.tableWidget.item(prevRow, c)
            self.tableWidget.setItem(newRow, c, prevItem.clone() if prevItem else QTableWidgetItem())

        self.resizeTable()

    def getDefaultData(self):
        return {"items": [("a", "1")], "header": ["name", "value"], "default": "items"}

    def getJsonData(self):
        header = [self.tableWidget.horizontalHeaderItem(c).text() for c in range(self.tableWidget.columnCount())]
        items = []

        vheader = self.tableWidget.verticalHeader()
        hheader = self.tableWidget.horizontalHeader()

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
            for c, data in enumerate(row):
                item = QTableWidgetItem(fromSmartConversion(data))
                self.tableWidget.setItem(r, c, item)

        self.updateSize()

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
        return {"value": [float(self.xWidget.text() or 0), float(self.yWidget.text() or 0), float(self.zWidget.text() or 0)],
                "default": "value"}

    def setJsonData(self, value):
        self.xWidget.setText(str(value["value"][0]))
        self.yWidget.setText(str(value["value"][1]))
        self.zWidget.setText(str(value["value"][2]))

def listLerp(lst1, lst2, coeff):
    return [p1*(1-coeff) + p2*coeff for p1, p2 in zip(lst1, lst2)]

def evaluateBezierCurve(cvs, param):
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

def findFromX(p1, p2, p3, p4, x):
    cvs1, cvs2 = bezierSplit(p1, p2, p3, p4)
    midp = cvs2[0]

    if abs(midp[0] - x) < 1e-3:
        return midp
    elif x < midp[0]:
        return findFromX(cvs1[0], cvs1[1], cvs1[2], cvs1[3], x)
    else:
        return findFromX(cvs2[0], cvs2[1], cvs2[2], cvs2[3], x)

def evaluateBezierCurveFromX(cvs, x):
    for i in range(0, len(cvs), 3):
        if cvs[i][0] > x:
            break

    return findFromX(cvs[i-3], cvs[i-2], cvs[i-1], cvs[i], x)

def normalizedPoint(p, minX, maxX, minY, maxY):
    x = (p[0] - minX) / (maxX - minX)
    y = (p[1] - minY) / (maxY - minY)
    return (x, y)

class CurvePointItem(QGraphicsItem):
    Size = 10
    def __init__(self, **kwargs):
        super(CurvePointItem, self).__init__(**kwargs)

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
            return super(CurvePointItem, self).itemChange(change, value)

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

        if change == QGraphicsItem.GraphicsItemChange.ItemPositionHasChanged:
            scene = self.scene()
            scene.calculateCVs()
            for view in scene.views():
                if type(view) == CurveView:
                    view.somethingChanged.emit()

        return super(CurvePointItem, self).itemChange(change, value)

class CurveScene(QGraphicsScene):
    MaxX = 300
    MaxY = -100
    DrawCurveSamples = 33
    def __init__(self, **kwargs):
        super(CurveScene, self).__init__(**kwargs)

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

        self.calculateCVs()

        for view in self.views():
            if type(view) == CurveView:
                view.somethingChanged.emit()

    def mousePressEvent(self, event):
        if event.button() == Qt.RightButton:
            somethingChanged = False
            for item in self.selectedItems():
                if item.fixedX is None: # don't remove tips
                    self.removeItem(item)
                    somethingChanged = True

            if somethingChanged:
                self.calculateCVs()

                for view in self.views():
                    if type(view) == CurveView:
                        view.somethingChanged.emit()

            event.accept()
        else:
            super(CurveScene,self).mousePressEvent(event)

    def calculateCVs(self):
        self.cvs = []

        if len(self.items()) < 2:
            return

        items = sorted(self.items(), key=lambda item: item.pos().x()) # sorted by x position

        tangents = []
        for i, item in enumerate(items): # calculate tangents
            if i == 0:
                tangents.append(QVector2D(items[i+1].pos() - items[i].pos()).normalized())
            elif i == len(items) - 1:
                tangents.append(QVector2D(items[i].pos() - items[i-1].pos()).normalized())
            else:
                tg = (QVector2D(items[i+1].pos() - items[i].pos()) / (items[i+1].pos().x() - items[i].pos().x()) +
                      QVector2D(items[i].pos() - items[i-1].pos()) / (items[i].pos().x() - items[i-1].pos().x())) / 2.0

                tangents.append(tg)

        for i, item in enumerate(items):
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
        if font.pointSize() > 2:
            font.setPointSize(font.pointSize()-2)
            painter.setFont(font)

        GridSize = 4
        TextOffset = 3
        xstep = CurveScene.MaxX / GridSize
        ystep = CurveScene.MaxY / GridSize

        for i in range(GridSize):
            painter.setPen(QColor(40,40,40, 50))
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
        super(CurveView, self).__init__(**kwargs)

        self.setRenderHint(QPainter.Antialiasing, True)
        self.setRenderHint(QPainter.TextAntialiasing, True)
        self.setRenderHint(QPainter.HighQualityAntialiasing, True)
        #self.setRenderHint(QPainter.SmoothPixmapTransform, True)
        #self.setRenderHint(QPainter.NonCosmeticDefaultPen, True)
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
        super(CurveTemplateWidget, self).__init__(**kwargs)

        layout = QVBoxLayout()
        layout.setContentsMargins(0, 0, 0, 0)
        self.setLayout(layout)

        self.curveView = CurveView()
        self.curveView.somethingChanged.connect(self.somethingChanged)
        layout.addWidget(self.curveView)

    def getDefaultData(self):
        return {'default': 'cvs', 'cvs': [(0.0, 1.0), (0.13973423457023273, 0.722154453101879), (0.3352803473835302, -0.0019584480764515554), (0.5029205210752953, -0.0), (0.6686136807168636, 0.0019357021806590401), (0.8623842449806401, 0.7231513901834298), (1.0, 1.0)]}

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

TemplateWidgets = {
    "button": ButtonTemplateWidget,
    "checkBox": CheckBoxTemplateWidget,
    "comboBox": ComboBoxTemplateWidget,
    "curve": CurveTemplateWidget,
    "label": LabelTemplateWidget,
    "lineEdit": LineEditTemplateWidget,
    "lineEditAndButton": LineEditAndButtonTemplateWidget,
    "listBox": ListBoxTemplateWidget,
    "radioButton": RadioButtonTemplateWidget,
    "table": TableTemplateWidget,
    "text": TextTemplateWidget,
    "vector": VectorTemplateWidget}
