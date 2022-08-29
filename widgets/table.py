from .base import *

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

        self.tableWidget.setContextMenuPolicy(Qt.DefaultContextMenu)
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
                self.tableWidget.setItem(r, c, QTableWidgetItem(fromSmartConversion(data)))

        self.updateSize()
