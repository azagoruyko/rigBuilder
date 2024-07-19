import sys
import re
from contextlib import contextmanager

from PySide2.QtGui import *
from PySide2.QtCore import *
from PySide2.QtWidgets import *

def Callback(f, *args, **kwargs):
   return lambda: f(*args, **kwargs)

def clamp(val, low, high):
    return max(low, min(high, val))

def replaceSpecialChars(text):
    return re.sub("[^a-zA-Z0-9_]", "_", text)

def replacePairs(pairs, text):
    for k, v in pairs:
        text = re.sub(k, v, text)
    return text

@contextmanager
def captureOutput(stream):
    default_stdout = sys.stdout
    default_stderr = sys.stderr

    sys.stdout = stream
    sys.stderr = stream
    yield
    sys.stdout = default_stdout
    sys.stderr = default_stderr

def printErrorStack():
    exc_type, exc_value, exc_traceback = sys.exc_info()

    tbs = []
    tb = exc_traceback
    while tb:
        tbs.append(tb)
        tb = tb.tb_next

    skip = True
    indent = "  "
    for tb in tbs:
        if tb.tb_frame.f_code.co_filename == "<string>":
            skip = False

        if not skip:
            print("{}{}, {}, in line {},".format(indent, tb.tb_frame.f_code.co_filename, tb.tb_frame.f_code.co_name, tb.tb_lineno))
            indent += "  "
    print("Error: {}".format(exc_value))

def centerWindow(window):
    screen = QDesktopWidget().screenGeometry()
    cp = screen.center()
    geom = window.frameGeometry()
    geom.moveCenter(cp)
    window.move(geom.topLeft())

def clearLayout(layout):
     if layout is not None:
         while layout.count():
             item = layout.takeAt(0)
             widget = item.widget()
             if widget is not None:
                 widget.setParent(None)
             else:
                 clearLayout(item.layout())

def getActions(menu, recursive=True):
    actions = []
    for action in menu.actions():
        if action.menu() and recursive:
            actions.extend(getActions(action.menu(), True))
        else:
            actions.append(action)
    return actions

def setActionsLocalShortcut(widget):
    for a in getActions(widget):
        a.setShortcutContext(Qt.WidgetShortcut)

def findOpeningBracketPosition(text, offset, brackets="{(["):
    openingBrackets = "{(["
    closingBrackets = "})]"
    stack = [0 for i in range(len(openingBrackets))] # for each bracket set 0 as default

    if offset < 0 or offset >= len(text):
        return None

    if text[offset] in closingBrackets:
        offset -= 1

    for i in range(offset, -1, -1):
        c = text[i]

        if c in brackets and c in openingBrackets and stack[openingBrackets.index(c)] == 0:
            return i

        elif c in openingBrackets:
            stack[openingBrackets.index(c)] += 1

        elif c in closingBrackets:
            stack[closingBrackets.index(c)] -= 1

def findClosingBracketPosition(text, offset, brackets="})]"):
    openingBrackets = "{(["
    closingBrackets = "})]"
    stack = [0 for _ in range(len(openingBrackets))] # for each bracket set 0 as default

    if offset < 0 or offset >= len(text):
        return None

    if text[offset] in openingBrackets:
        offset += 1

    for i in range(offset, len(text)):
        c = text[i]

        if c in brackets and c in closingBrackets and stack[closingBrackets.index(c)] == 0:
            return i

        elif c in openingBrackets:
            stack[openingBrackets.index(c)] += 1

        elif c in closingBrackets:
            stack[closingBrackets.index(c)] -= 1

def findBracketSpans(text, offset):
    s = findOpeningBracketPosition(text, offset, "{([")
    if s is not None:
        matchingClosingBracket = {"{":"}", "(":")", "[":"]"}[text[s]]
        e = findClosingBracketPosition(text, offset, matchingClosingBracket)
    else:
        e = findClosingBracketPosition(text, offset, "})]")
    return (s,e)

def wordAtCursor(cursor):
    cursor = QTextCursor(cursor)
    pos = cursor.position()

    lpart = ""
    start = pos-1
    ch = cursor.document().characterAt(start)
    while ch and re.match("[@\\w]", ch):
        lpart += ch
        start -= 1

        if ch == "@": # @ can be the first character only
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

class SearchReplaceDialog(QDialog):
    onReplace = Signal(str, str, dict) # old, new, options

    def __init__(self, options=[], **kwargs):
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
        gridLayout.addWidget(QLabel("Search"),0,0)
        gridLayout.addWidget(self.searchWidget,0,1)
        gridLayout.addWidget(QLabel("Replace"),1,0)
        gridLayout.addWidget(self.replaceWidget,1,1)
        layout.addLayout(gridLayout)

        for opt in options:
            w = QCheckBox(opt)
            self.optionsWidgets[opt] = w
            layout.addWidget(w)

        layout.addWidget(btn)

    def replaceClicked(self):
        opts = {l:w.isChecked() for l,w in self.optionsWidgets.items()}
        self.onReplace.emit(self.searchWidget.text(), self.replaceWidget.text(), opts)
        self.accept()

class SimpleUndo():
    def __init__(self):
        self.undoEnabled = True
        
        self._undoStack = []
        self._undoTempStack = []
        self._tempEditBlockName = ""
        self._undoOrder = 0 # undo inc/dec this

    def isEmpty(self):
        return not self._undoStack

    def flush(self):
        self._undoStack = []
        self._undoTempStack = []

    def isInEditBlock(self):        
        return self._undoOrder > 0
    
    def beginEditBlock(self, name="temp"):
        self._tempEditBlockName = name
        self._undoOrder += 1

    def endEditBlock(self):
        self._undoOrder -= 1

        # append all temporary operations as a single undo function
        if self._undoTempStack and not self.isInEditBlock():
            def f(stack=self._undoTempStack):
                for _, func in stack:
                    func()

            self.push(self._tempEditBlockName, f)
            self._undoTempStack = []

    def getLastOperationName(self):
        if not self._undoStack:
            return
        cmd = self._undoStack[-1][0] 
        return re.match(r"(.+)\s+#", cmd).group(1)

    def push(self, name, undoFunc, operationId=None):
        def _getLastOperation():
            if self.isInEditBlock():
                return self._undoTempStack[-1] if self._undoTempStack else None
            else:
                return self._undoStack[-1] if self._undoStack else None

        if not self.undoEnabled:
            return

        lastOp = _getLastOperation()

        cmd = "{} #{}".format(name, operationId) # generate unique command name
        if operationId is not None and lastOp and lastOp[0] == cmd: # the same operation, do not add
            pass
        else:
            if self.isInEditBlock():
                self._undoTempStack.append((cmd, undoFunc))
            else:
                self._undoStack.append((cmd, undoFunc))

    def undo(self):
        if not self._undoStack:
            print("Nothing to undo")
        else:
            self.undoEnabled = False # prevent undoing while undoing

            while True and self._undoStack:
                _, undoFunc = self._undoStack.pop()

                if callable(undoFunc):
                    undoFunc()
                    break

            self.undoEnabled = True          