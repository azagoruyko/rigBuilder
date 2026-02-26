import sys
import re
from contextlib import contextmanager

from .qt import *

def getFontWidth(fontMetrics, text: str) -> int:
    """Get text width using appropriate method for Qt version."""
    if hasattr(fontMetrics, 'horizontalAdvance'):
        return fontMetrics.horizontalAdvance(text)
    else:
        return fontMetrics.width(text)

JsonColors = {"none": QColor("#AAAAAA"),
              "bool": QColor("#CDEB8B"),
              "true": QColor("#82C777"),
              "false": QColor("#CC6666"),
              "int": QColor("#B88164"), 
              "float": QColor("#BF994D"), 
              "string": QColor("#BBBB88"), 
              "list": QColor("#538A53"), 
              "dict": QColor("#7AB1CC")}

def jsonColor(value) -> QColor:
    """Get color for JSON value based on type."""
    if value is None:
        return JsonColors["none"]
    elif value is True:
        return JsonColors["true"]
    elif value is False:
        return JsonColors["false"]    
    elif isinstance(value, int):
        return JsonColors["int"]
    elif isinstance(value, float):
        return JsonColors["float"]
    elif isinstance(value, str):
        return JsonColors["string"]
    elif isinstance(value, list):
        return JsonColors["list"]
    elif isinstance(value, dict):
        return JsonColors["dict"]

def Callback(f, *args, **kwargs):
    """Create lambda callback for Qt signals."""
    return lambda: f(*args, **kwargs)

@contextmanager
def blockedWidgetContext(widget):
    """Context manager to temporarily block widget signals."""
    widget.blockSignals(True)
    yield widget
    widget.blockSignals(False)

def centerWindow(window):
    """Center window on primary screen."""
    screen = QApplication.primaryScreen().geometry()
    cp = screen.center()
    geom = window.frameGeometry()
    geom.moveCenter(cp)
    window.move(geom.topLeft())

def clearLayout(layout):
    """Recursively clear all widgets from layout."""
    if layout is not None:
        while layout.count():
            item = layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.setParent(None)
            else:
                clearLayout(item.layout())

def getActions(menu, recursive: bool = True) -> list:
    """Get all actions from menu, optionally recursive."""
    actions = []
    for action in menu.actions():
        if action.menu() and recursive:
            actions.extend(getActions(action.menu(), True))
        else:
            actions.append(action)
    return actions

def setActionsLocalShortcut(widget):
    """Set all menu actions to use widget-local shortcuts."""
    for a in getActions(widget):
        a.setShortcutContext(Qt.WidgetShortcut)

def wordAtCursor(cursor):
    """Get word at cursor position including @ prefix."""
    cursor = QTextCursor(cursor)
    pos = cursor.position()

    lpart = ""
    start = pos-1
    ch = cursor.document().characterAt(start)
    while ch and re.match("[@\\w]", ch):
        lpart += ch
        start -= 1

        if ch == "@":  # @ can be the first character only
            break

        ch = cursor.document().characterAt(start)

    rpart = ""
    end = pos
    ch = cursor.document().characterAt(end)
    while ch and re.match("[\\w]", ch):
        rpart += ch
        end += 1
        ch = cursor.document().characterAt(end)

    return (lpart[::-1]+rpart, start+1, end)

def fontSize(font) -> float:
    """Get font size regardless of size type."""
    if font.pointSize() > 0:
        return font.pointSize()
    elif font.pixelSize() > 0:
        return font.pixelSize()
    elif font.pointSizeF() > 0:
        return font.pointSizeF()    

def setFontSize(font, size: float):
    """Set font size using appropriate method."""
    if font.pointSize() > 0:
        font.setPointSize(size)
    elif font.pixelSize() > 0:
        font.setPixelSize(size)
    elif font.pointSizeF() > 0:
        font.setPointSizeF(size)

class SearchReplaceDialog(QDialog):
    """Dialog for search and replace operations."""
    onReplace = Signal(str, str, dict)  # old, new, options

    def __init__(self, options: list = [], **kwargs):
        super().__init__(**kwargs)

        self.optionsWidgets = {}

        self.setWindowTitle("Search/Replace")
        layout = QVBoxLayout()
        self.setLayout(layout)

        self.searchWidget = QLineEdit("L_")
        self.replaceWidget = QLineEdit("R_")

        btn = QPushButton("Replace")
        btn.clicked.connect(self.replaceClicked)

        gridLayout = QGridLayout()
        gridLayout.addWidget(QLabel("Search"), 0, 0)
        gridLayout.addWidget(self.searchWidget, 0, 1)
        gridLayout.addWidget(QLabel("Replace"), 1, 0)
        gridLayout.addWidget(self.replaceWidget, 1, 1)
        layout.addLayout(gridLayout)

        for opt in options:
            w = QCheckBox(opt)
            self.optionsWidgets[opt] = w
            layout.addWidget(w)

        layout.addWidget(btn)

    def replaceClicked(self):
        opts = {l: w.isChecked() for l, w in self.optionsWidgets.items()}
        self.onReplace.emit(self.searchWidget.text(), self.replaceWidget.text(), opts)
        self.accept()

