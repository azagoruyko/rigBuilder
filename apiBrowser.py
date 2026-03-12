"""API Registry browser. Shows registered names and their types for user reference."""

from __future__ import annotations

import inspect

from .core import APIRegistry
from .qt import *
from .ui_utils import applyStylesheet
from . import ui as rigBuilderUi

TABLE_COLUMNS = ["Name", "Type"]
DEFAULT_WINDOW_SIZE = (400, 700)


def _formatEntry(name, obj):
    """Return (typeStr, details) for an API registry entry."""
    typeStr = "class" if inspect.isclass(obj) else type(obj).__name__
    objName = getattr(obj, "__name__", name)
    details = []
    if inspect.isclass(obj):
        details.append("Class: {}".format(objName))
    elif callable(obj):
        try:
            details.append("Signature: {}{}".format(objName, inspect.signature(obj)))
        except (ValueError, TypeError):
            details.append("(signature not available)")
    doc = inspect.getdoc(obj)
    if doc:
        details.append("Doc: {}".format(doc.split("\n")[0].strip()))
    if not details:
        details.append("Type: {}".format(typeStr))

    return typeStr, "\n".join(details)


class ApiBrowserWindow(QWidget):
    """Browse APIRegistry contents: registered names, types, and signatures."""

    windowInstance = None

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.setWindowFlags(Qt.Window | Qt.WindowCloseButtonHint | Qt.WindowMinMaxButtonsHint)
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setAutoFillBackground(True)
        self.setWindowTitle("Rig Builder API Browser")
        self.resize(*DEFAULT_WINDOW_SIZE)

        rootLayout = QVBoxLayout()
        self.setLayout(rootLayout)

        toolLayout = QHBoxLayout()
        rootLayout.addLayout(toolLayout)
        toolLayout.addWidget(QLabel("Filter:"))
        self.filterEdit = QLineEdit()
        self.filterEdit.setPlaceholderText("Filter by name or type...")
        self.filterEdit.textChanged.connect(self.refreshList)
        toolLayout.addWidget(self.filterEdit, 1)

        self.refreshButton = QPushButton("Refresh")
        self.refreshButton.clicked.connect(self.refreshList)
        toolLayout.addWidget(self.refreshButton)

        splitter = QSplitter(Qt.Vertical)
        rootLayout.addWidget(splitter, 1)

        tablePane = QWidget()
        tableLayout = QVBoxLayout()
        tableLayout.setContentsMargins(0, 0, 0, 0)
        tablePane.setLayout(tableLayout)
        tableLayout.addWidget(QLabel("Registered API"))
        self.tableWidget = QTableWidget()
        self.tableWidget.setColumnCount(len(TABLE_COLUMNS))
        self.tableWidget.setHorizontalHeaderLabels(TABLE_COLUMNS)
        self.tableWidget.setAlternatingRowColors(True)
        self.tableWidget.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.tableWidget.setSelectionMode(QAbstractItemView.SingleSelection)
        
        header = self.tableWidget.horizontalHeader()
        for i in range(len(TABLE_COLUMNS)):
            header.setSectionResizeMode(i, QHeaderView.ResizeToContents)

        self.tableWidget.setSortingEnabled(True)
        self.tableWidget.itemSelectionChanged.connect(self._onSelectionChanged)
        tableLayout.addWidget(self.tableWidget)
        splitter.addWidget(tablePane)

        detailsPane = QWidget()
        detailsLayout = QVBoxLayout()
        detailsLayout.setContentsMargins(0, 0, 0, 0)
        detailsPane.setLayout(detailsLayout)
        detailsLayout.addWidget(QLabel("Details"))
        self.detailsText = QTextEdit()
        self.detailsText.setReadOnly(True)
        self.detailsText.setPlaceholderText("Select an entry to view details.")
        detailsLayout.addWidget(self.detailsText)
        splitter.addWidget(detailsPane)
        splitter.setStretchFactor(0, 8)
        splitter.setStretchFactor(1, 2)

        applyStylesheet(self)
        self.refreshList()

    def refreshList(self):
        api = APIRegistry.api()
        filterText = self.filterEdit.text().strip().lower()
        self.tableWidget.setSortingEnabled(False)

        rows = []
        for name in sorted(api.keys()):
            typeStr, _ = _formatEntry(name, api[name])
            if filterText and filterText not in name.lower() and filterText not in typeStr.lower():
                continue
            rows.append((name, typeStr))

        self.tableWidget.setRowCount(len(rows))
        for i, (name, typeStr) in enumerate(rows):
            self.tableWidget.setItem(i, 0, QTableWidgetItem(name))
            self.tableWidget.setItem(i, 1, QTableWidgetItem(typeStr))
        self.tableWidget.setSortingEnabled(True)

    def _onSelectionChanged(self):
        items = self.tableWidget.selectedItems()
        if not items:
            self.detailsText.clear()
            return
        row = items[0].row()
        name = self.tableWidget.item(row, 0).text()
        api = APIRegistry.api()
        obj = api.get(name)
        if obj is None:
            self.detailsText.setText("(not found)")
            return
        _, details = _formatEntry(name, obj)
        self.detailsText.setText(details)

    def closeEvent(self, event):
        ApiBrowserWindow.windowInstance = None
        super().closeEvent(event)


def showApiBrowser():
    """Show singleton API browser window."""
    existing = ApiBrowserWindow.windowInstance
    if existing and existing.isVisible():
        existing.raise_()
        existing.activateWindow()
        return existing

    parent = getattr(rigBuilderUi, "parentWindow", None) or getattr(rigBuilderUi, "ParentWindow", None)
    window = ApiBrowserWindow(parent=parent)
    ApiBrowserWindow.windowInstance = window
    window.show()
    return window
