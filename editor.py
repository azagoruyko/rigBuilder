from PySide2.QtGui import *
from PySide2.QtCore import *
from PySide2.QtWidgets import *

import re
from .utils import clamp, getActions, setActionsLocalShortcut, wordAtCursor, findBracketSpans, fontSize, setFontSize

class PythonHighlighter(QSyntaxHighlighter):
    def __init__(self, parent):
        super().__init__(parent)

        self.highlightingRules = []

        assignFormat = QTextCharFormat()
        assignFormat.setForeground(QColor(200, 150, 100))
        assignRegexp = QRegExp("\\b(\\w+)\\s*(?=[-+*/]*=)")
        assignRegexp.setMinimal(True)
        self.highlightingRules.append((assignRegexp, assignFormat))

        numFormat = QTextCharFormat()
        numFormat.setForeground(QColor(150, 200, 150))
        self.highlightingRules.append((QRegExp("\\b(0x[0-9]+)\\b|\\b[0-9\\.]+f*\\b"), numFormat))

        functionFormat = QTextCharFormat()
        functionFormat.setForeground(QColor(100, 150, 200))
        self.highlightingRules.append((QRegExp("\\b\\w+(?=\\s*\\()"), functionFormat))

        keywordFormat = QTextCharFormat()
        keywordFormat.setForeground(QColor(150, 130, 200))

        keywords = ["\\b%s\\b"%k for k in ["False", "await", "else", "import", "pass",
                                             "None", "break", "except", "in", "raise",
                                             "True", "class", "finally", "is", "return",
                                             "and", "continue", "for", "lambda", "try",
                                             "as", "def", "from", "nonlocal", "while","exec", "eval",
                                             "assert", "del", "global", "not", "with",
                                             "async", "elif", "if", "or", "yield", "print", "self"]]

        self.highlightingRules += [(QRegExp(pattern), keywordFormat) for pattern in keywords]

        boolFormat = QTextCharFormat()
        boolFormat.setForeground(QColor(200, 100, 50))
        self.highlightingRules.append((QRegExp("\\bTrue\\b|\\bFalse\\b|\\bNone\\b"), boolFormat))

        attrFormat = QTextCharFormat()
        attrFormat.setForeground(QColor(100, 180, 180))
        self.highlightingRules.append((QRegExp("@\\b\\w+\\b"), attrFormat))

        self.quotationFormat = QTextCharFormat()
        self.quotationFormat.setForeground(QColor(130, 200, 130))
        self.highlightingRules.append((QRegExp("(\"(\\\\\"|[^\"])*\")|(\'(\\\\\'|[^\'])*\')"), self.quotationFormat))

        singleLineCommentFormat = QTextCharFormat()
        singleLineCommentFormat.setForeground(QColor(90, 90, 90))
        self.highlightingRules.append((QRegExp("#[^\\n]*"), singleLineCommentFormat))

        self.multiLineCommentFormat = QTextCharFormat()
        self.multiLineCommentFormat.setForeground(QColor(170, 170, 100))

        self.highlightedWordFormat = QTextCharFormat()
        self.highlightedWordFormat.setForeground(QColor(200, 200, 200))
        self.highlightedWordFormat.setBackground(QBrush(QColor(100, 55, 170)))
        self.highlightedWordRegexp = None

    def highlightBlock(self, text):
        for pattern, format in self.highlightingRules:
            if not pattern:
                continue

            expression = QRegExp(pattern)
            index = expression.indexIn(text)
            while index >= 0:
                length = expression.matchedLength()
                self.setFormat(index, length, format)
                index = expression.indexIn(text, index + length)

        self.setCurrentBlockState(0)

        # Do multi-line strings
        in_multiline = self.match_multiline(text, QRegExp("'''"), 1, self.multiLineCommentFormat)
        if not in_multiline:
            in_multiline = self.match_multiline(text, QRegExp('"""'), 2, self.multiLineCommentFormat)

        if self.highlightedWordRegexp:
            expression = QRegExp(self.highlightedWordRegexp)
            index = expression.indexIn(text)
            while index >= 0:
                length = expression.matchedLength()
                self.setFormat(index, length, self.highlightedWordFormat)
                index = expression.indexIn(text, index + length)

    def match_multiline(self, text, delimiter, in_state, style):
        """Do highlighting of multi-line strings. ``delimiter`` should be a
        ``QRegExp`` for triple-single-quotes or triple-double-quotes, and
        ``in_state`` should be a unique integer to represent the corresponding
        state changes when inside those strings. Returns True if we're still
        inside a multi-line string when this function is finished.
        """
        # If inside triple-single quotes, start at 0
        if self.previousBlockState() == in_state:
            start = 0
            add = 0
        # Otherwise, look for the delimiter on this line
        else:
            start = delimiter.indexIn(text)
            # Move past this match
            add = delimiter.matchedLength()
        # As long as there's a delimiter match on this line...
        while start >= 0:
            # Look for the ending delimiter
            end = delimiter.indexIn(text, start + add)
            # Ending delimiter on this line?
            if end >= add:
                length = end - start + add + delimiter.matchedLength()
                self.setCurrentBlockState(0)
            # No; multi-line string
            else:
                self.setCurrentBlockState(in_state)
                length = len(text) - start + add
            # Apply formatting
            self.setFormat(start, length, style)
            # Look for the next match
            start = delimiter.indexIn(text, start + length)
        # Return True if still inside a multi-line string, False otherwise
        if self.currentBlockState() == in_state:
            return True
        else:
           return False

def highlightLine(widget, line=None, *, clear=False):
    if line is None:
        block = widget.textCursor().block()
    else:
        block = widget.document().findBlockByLineNumber(line)

        if not block.isValid():
            return

    fmt = QTextCharFormat()
    if not clear:
        fmt.setBackground(QColor(50, 80, 100))

    cursor = widget.textCursor()
    cursor.setPosition(block.position())
    cursor.select(QTextCursor.LineUnderCursor)
    cursor.setCharFormat(fmt)
    cursor.clearSelection()
    cursor.movePosition(QTextCursor.StartOfLine)
    widget.setTextCursor(cursor)

class SwoopHighligher(QSyntaxHighlighter):
    def __init__(self, parent):
        super().__init__(parent)

        self.highlightingRules = []

        linumFormat = QTextCharFormat()
        linumFormat.setForeground(QColor(180, 100, 120))
        self.highlightingRules.append((QRegExp("^\\s*\\d+\\s+"), linumFormat))

        headerFormat = QTextCharFormat()
        headerFormat.setForeground(QColor(120, 100, 180))
        headerFormat.setFontWeight(QFont.Bold)
        self.highlightingRules.append((QRegExp("^[a-zA-Z][\\w -]*"), headerFormat))

        subHeaderFormat = QTextCharFormat()
        subHeaderFormat.setForeground(QColor(120, 180, 120))
        self.highlightingRules.append((QRegExp("\\[[\\w ]+\\]$"), subHeaderFormat))

        commentFormat = QTextCharFormat()
        commentFormat.setForeground(QColor(90, 90, 90))
        self.highlightingRules.append((QRegExp("//.*$"), commentFormat))

        highlightedWordsFormat = QTextCharFormat()
        highlightedWordsFormat.setForeground(QColor(200, 200, 200))
        highlightedWordsFormat.setBackground(QBrush(QColor(100, 55, 170)))
        self.highlightingRules.append((None, highlightedWordsFormat))

    def highlightBlock(self, text):
        for pattern, format in self.highlightingRules:
            if not pattern:
                continue

            expression = QRegExp(pattern)
            index = expression.indexIn(text)
            while index >= 0:
                length = expression.matchedLength()
                self.setFormat(index, length, format)
                index = expression.indexIn(text, index + length)

        self.setCurrentBlockState(0)

class SwoopSearchDialog(QDialog):
    def __init__(self, textWidget, **kwargs):
        super().__init__(**kwargs)

        self.textWidget = textWidget

        self.replaceMode = False
        self.replacePattern = None
        self.previousLines = []

        self.savedSettings = {}

        self.setWindowFlags(Qt.FramelessWindowHint | Qt.Window)
        self.setWindowTitle("Swoop")

        layout = QVBoxLayout()
        self.setLayout(layout)

        self.filterWidget = QLineEdit()
        self.filterWidget.textChanged.connect(self.filterTextChanged)
        self.filterWidget.keyPressEvent = self.filterKeyPressEvent

        self.replaceModeBtn = QPushButton("Replace")
        self.replaceModeBtn.clicked.connect(lambda _:self.switchReplaceMode())
        
        filterLayout = QHBoxLayout()
        filterLayout.addWidget(self.filterWidget)
        filterLayout.addWidget(self.replaceModeBtn)

        settingsLayout = QHBoxLayout()
        self.caseSensitiveWidget = QCheckBox("Case sensitive")
        self.caseSensitiveWidget.setChecked(True)
        self.caseSensitiveWidget.stateChanged.connect(self.filterTextChanged)
        self.wholeWordWidget = QCheckBox("Whole word")
        self.wholeWordWidget.stateChanged.connect(self.filterTextChanged)
        self.indentDeeperWidget = QCheckBox("Indent deeper")
        self.indentDeeperWidget.stateChanged.connect(self.filterTextChanged)
        settingsLayout.addWidget(self.caseSensitiveWidget)
        settingsLayout.addWidget(self.wholeWordWidget)
        settingsLayout.addWidget(self.indentDeeperWidget)

        self.resultsWidget = QTextEdit()
        self.resultsWidget.setReadOnly(True)
        self.resultsWidget.setWordWrapMode(QTextOption.NoWrap)
        self.resultsWidget.syntax = SwoopHighligher(self.resultsWidget.document())
        self.resultsWidget.mousePressEvent = self.resultsMousePressEvent
        self.resultsWidget.keyPressEvent = self.filterWidget.keyPressEvent

        layout.addLayout(filterLayout)
        layout.addLayout(settingsLayout)
        layout.addWidget(self.resultsWidget)
        self.rejected.connect(self.whenRejected)

    def showEvent(self, event):
        cursor = self.textWidget.textCursor()
        text = self.textWidget.toPlainText()

        self.savedSettings["cursor"] = cursor
        self.savedSettings["scroll"] = self.textWidget.verticalScrollBar().value()
        self.savedSettings["lines"] = text.split("\n")        

        findText = cursor.selectedText()
        if not findText:
            findText = wordAtCursor(cursor)[0]

        if findText == self.filterWidget.text():
            self.filterTextChanged()
        else:
            self.filterWidget.setText(findText)

        self.switchReplaceMode(False)
        self.reposition()

    def resultsMousePressEvent(self, event):
        cursor = self.resultsWidget.cursorForPosition(event.pos())
        highlightLine(self.resultsWidget, clear=True)
        highlightLine(self.resultsWidget, cursor.block().blockNumber())
        self.resultsLineChanged()

    def reposition(self):
        c = self.textWidget.mapToGlobal(self.textWidget.cursorRect().bottomLeft())
        w = self.resultsWidget.document().idealWidth() + 30
        h = self.resultsWidget.document().blockCount()*self.resultsWidget.cursorRect().height() + 110
        self.setGeometry(c.x(), c.y()+3, clamp(w, 0, 500), clamp(h, 0, 400))

    def switchReplaceMode(self, value=None):
        self.replaceMode = not self.replaceMode if value is None else value
        
        if self.replaceMode:            
            self.filterWidget.setStyleSheet("background-color: #433567")
            self.replacePattern = self.getFilterPattern()
            self.replaceModeBtn.setText("Cancel")            
        else:
            self.filterWidget.setStyleSheet("")
            self.replaceModeBtn.setText("Replace")
            self.filterTextChanged()

        self.caseSensitiveWidget.setEnabled(not self.replaceMode)
        self.wholeWordWidget.setEnabled(not self.replaceMode)
        self.indentDeeperWidget.setEnabled(not self.replaceMode)

    def resultsLineChanged(self):
        if self.replaceMode:
            return
        
        caseSensitive = self.caseSensitiveWidget.isChecked()

        resultsLine = self.resultsWidget.textCursor().block().text()
        if not resultsLine:
            return

        lineNumber = re.search("^(\\d+)", resultsLine).group()
        self.textWidget.gotoLine(int(lineNumber))

        currentFilter = self.getFilterPattern()
        cursor = self.textWidget.textCursor()
        currentLine = cursor.block().text()

        r = re.search(currentFilter, currentLine, re.IGNORECASE if not caseSensitive else 0)

        if r:
            pos = cursor.block().position() + r.start()
            if pos > 0:
                cursor.setPosition(pos)
                self.textWidget.setTextCursor(cursor)

            cursorY = self.textWidget.cursorRect().top()
            scrollBar = self.textWidget.verticalScrollBar()
            scrollBar.setValue(scrollBar.value() + cursorY - self.textWidget.geometry().height()/2)

        self.reposition()

    def filterKeyPressEvent(self, event):
        ctrl = event.modifiers() & Qt.ControlModifier

        if event.key() in [Qt.Key_Down, Qt.Key_Up, Qt.Key_PageDown, Qt.Key_PageUp]:
            rw = self.resultsWidget
            line = rw.textCursor().block().blockNumber()
            lineCount = rw.document().blockCount()-1

            highlightLine(rw, clamp(line, 0, lineCount), clear=True)
            if event.key() == Qt.Key_Down:
                highlightLine(rw, clamp(line+1, 0, lineCount))
            elif event.key() == Qt.Key_Up:
                highlightLine(rw, clamp(line-1, 0, lineCount))

            elif event.key() == Qt.Key_PageDown:
                highlightLine(rw, clamp(line+5, 0, lineCount))

            elif event.key() == Qt.Key_PageUp:
                highlightLine(rw, clamp(line-5, 0, lineCount))

            self.resultsLineChanged()

        elif event.key() == Qt.Key_Return: # accept
            if self.replaceMode:
                cursor = self.textWidget.textCursor()

                savedBlock = self.savedSettings["cursor"].block()
                savedColumn = self.savedSettings["cursor"].positionInBlock()

                doc = self.textWidget.document()

                getIndent = lambda s: s[:len(s) - len(s.lstrip())]

                cursor.beginEditBlock()
                lines = self.resultsWidget.toPlainText().split("\n")
                for line in lines:
                    if not line.strip():
                        continue

                    lineNumber, text = re.search("^(\\d+)\\s*(.*)$", line).groups()
                    lineNumber = int(lineNumber)

                    blockPos = doc.findBlockByLineNumber(lineNumber-1).position()
                    cursor.setPosition(blockPos)
                    cursor.select(QTextCursor.LineUnderCursor)
                    indent = getIndent(cursor.selectedText())
                    cursor.removeSelectedText()
                    cursor.insertText(indent+text)

                cursor.endEditBlock()

                cursor.setPosition(savedBlock.position() + savedColumn)
                self.textWidget.setTextCursor(cursor)
                self.textWidget.verticalScrollBar().setValue(self.savedSettings["scroll"])

            self.textWidget.setFocus()
            self.accept()

        else:
            QLineEdit.keyPressEvent(self.filterWidget, event)

    def whenRejected(self):
        self.textWidget.setTextCursor(self.savedSettings["cursor"])
        self.textWidget.verticalScrollBar().setValue(self.savedSettings["scroll"])
        self.textWidget.setFocus()

    def getFilterPattern(self):
        currentFilter = re.escape(self.filterWidget.text())
        useWordBoundary = self.wholeWordWidget.isChecked()

        if not currentFilter:
            return ""

        if useWordBoundary:
            currentFilter = "\\b" + currentFilter + "\\b"

        return currentFilter

    def filterTextChanged(self):
        self.resultsWidget.clear()
        self.resultsWidget.setCurrentCharFormat(QTextCharFormat())

        caseSensitive = self.caseSensitiveWidget.isChecked()
        deeperOnly = self.indentDeeperWidget.isChecked()

        getIndent = lambda s: s[:len(s) - len(s.lstrip())]

        if self.replaceMode: # replace mode
            replaceString = self.filterWidget.text()
            pattern = self.getFilterPattern()

            lines = []
            for line in self.previousLines:
                n, text = re.search("^(\\d+)\\s*(.*)$", line).groups()
                text = re.sub(self.replacePattern, replaceString, text, 0, re.IGNORECASE if not caseSensitive else 0)
                lines.append("{0:<5} {1}".format(n, text.strip()))

            self.resultsWidget.setText("\n".join(lines))
            self.resultsWidget.syntax.highlightingRules[-1] = (pattern, self.resultsWidget.syntax.highlightingRules[-1][1])
            self.resultsWidget.syntax.rehighlight()

        else: # search mode
            currentFilter = self.getFilterPattern()
            currentBlockNumber = self.savedSettings["cursor"].block().blockNumber()

            indent = getIndent(self.savedSettings["cursor"].block().text())

            counter = 0
            currentIndex = 0

            self.previousLines = []
            for i, line in enumerate(self.savedSettings["lines"]):
                if not line.strip():
                    continue

                if deeperOnly: # works down and indent deeper only
                    if i < currentBlockNumber: # skip previous lines
                        continue

                    elif getIndent(line) < indent:
                        break

                if i == currentBlockNumber:
                    currentIndex = counter

                r = re.search(currentFilter, line, re.IGNORECASE if not caseSensitive else 0)
                if r:
                    self.previousLines.append("{0:<5} {1}".format(i+1, line.strip()))
                    counter += 1

            self.resultsWidget.setText("\n".join(self.previousLines))

            self.resultsWidget.syntax.highlightingRules[-1] = (currentFilter, self.resultsWidget.syntax.highlightingRules[-1][1])
            self.resultsWidget.syntax.rehighlight()

            highlightLine(self.resultsWidget, currentIndex)
            self.resultsLineChanged()

class CompletionWidget(QTextEdit):
    def __init__(self, items, **kwargs):
        super().__init__(**kwargs)

        self._prevLine = 0

        self.setWindowFlags(Qt.FramelessWindowHint)
        self.setAttribute(Qt.WA_ShowWithoutActivating)

        self.setReadOnly(True)
        self.setWordWrapMode(QTextOption.NoWrap)

        self.updateItems([])

    def currentLine(self):
        return self.textCursor().block().blockNumber()

    def lineCount(self):
        return self.document().blockCount()

    def gotoLine(self, line):
        line = clamp(line, 0, self.lineCount()-1)        
        highlightLine(self, self._prevLine, clear=True)
        self._prevLine = line
        highlightLine(self, self._prevLine)

    def mousePressEvent(self, event):
        super().mousePressEvent(event)
        self.gotoLine(self.currentLine())

    def keyPressEvent(self, event):
        if event.key() == Qt.Key_Return:
            super().keyPressEvent(event)
        else:
            lineCount = self.lineCount()

            keyMove = {Qt.Key_Down: 1, Qt.Key_Up: -1, Qt.Key_PageDown: 10, Qt.Key_PageUp: -10}
            offset = keyMove.get(event.key(), 0)
            if offset != 0:
                self.gotoLine(clamp(self._prevLine+offset, 0, lineCount))

    def updateItems(self, items):
        if not items:
            return

        self.clear()
        self.setCurrentCharFormat(QTextCharFormat())

        lines = []
        for line in items:
            lines.append(line)

        self.setText("\n".join(lines))

        highlightLine(self, 0)
        self._prevLine = 0

        self.autoResize()

    def autoResize(self):
        w = self.document().idealWidth() + 10
        h = self.document().blockCount()*self.cursorRect().height() + 30

        maxWidth = self.parent().width() - self.parent().cursorRect().left() - 30
        maxHeight = self.parent().height() - self.parent().cursorRect().top() - 30

        self.setFixedSize(clamp(w, 0,maxWidth), clamp(h, 0, maxHeight))

    def showEvent(self, event):
        self.autoResize()

class TextBlockData(QTextBlockUserData):
    def __init__(self):
        super().__init__()
        self.hasBookmark = False

class CodeEditorWidget(QTextEdit):
    editorState = {}
    TabSpaces = 4

    def __init__(self, **kwargs):
        super().__init__(**kwargs)

        self.preset = "default"
        self.commentChar = "#"
        self.ignoreStates = False # don't save/load states

        self.syntax = PythonHighlighter(self.document())

        self._editorState = {}

        self._canShowCompletions = True

        self.words = []
        self._currentWord = ("", 0, 0)

        self._searchStartWord = ("", 0, 0)
        self._prevCursorPosition = 0
        self.swoopSearchDialog = SwoopSearchDialog(self, parent=self)

        self.completionWidget = CompletionWidget([], parent=self)
        self.completionWidget.hide()

        self.setTabStopWidth(32)
        self.setAcceptRichText(False)
        self.setWordWrapMode(QTextOption.NoWrap)

        self.cursorPositionChanged.connect(self.editorCursorPositionChanged)
        self.verticalScrollBar().valueChanged.connect(self.scrollBarChanged)
        self.textChanged.connect(self.editorTextChanged)

        self.addActions(getActions(self.getMenu()))
        setActionsLocalShortcut(self)

    def event(self, event):
        if event.type() == QEvent.KeyPress:
            if event.key() == Qt.Key_Tab:
                cursor = self.textCursor()
                tabSpaces = " "*CodeEditorWidget.TabSpaces
                start = cursor.selectionStart()
                end = cursor.selectionEnd()

                cursor.beginEditBlock()
                if end == start:
                    cursor.insertText(tabSpaces)
                else:
                    cursor.clearSelection()
                    cursor.setPosition(start)

                    while cursor.position() < end:
                        cursor.movePosition(QTextCursor.StartOfLine)
                        cursor.insertText(tabSpaces)
                        if not cursor.movePosition(QTextCursor.Down):
                            break
                        end += len(tabSpaces)

                cursor.endEditBlock()

                event.accept()
                return True

        return super().event(event)
    
    def scrollBarChanged(self, _):
        self.saveState(cursor=False, scroll=True, bookmarks=False)
        if self.completionWidget.isVisible():
            self.completionWidget.hide()

    def setBookmark(self, line=-1):
        if line == -1:
            block = self.textCursor().block()
        else:
            block = self.document().findBlockByNumber(line)

        blockData = block.userData()

        if not blockData:
            blockData = TextBlockData()
            blockData.hasBookmark = True
        else:
            blockData.hasBookmark = not blockData.hasBookmark

        if isinstance(self.parent(), CodeEditorWithNumbersWidget):
            self.parent().numberBarWidget.updateState()

        block.setUserData(blockData)
        self.saveState(cursor=False, scroll=False, bookmarks=True)

    def gotoNextBookmark(self):
        doc = self.document()

        def gotoBookmark(startLine):
            for i in range(startLine, doc.blockCount()):
                b = doc.findBlockByNumber(i)

                blockData = b.userData()
                if blockData and blockData.hasBookmark:
                    self.setTextCursor(QTextCursor(b))
                    self.centerLine()
                    break

        startLine = self.textCursor().block().blockNumber()
        gotoBookmark(startLine + 1)

        if startLine == self.textCursor().block().blockNumber():        
            gotoBookmark(0)

    def loadState(self, cursor=True, scroll=True, bookmarks=True):
        if self.ignoreStates:
            return

        scrollBar = self.verticalScrollBar()

        self.ignoreStates = True

        if not self.preset or not self._editorState.get(self.preset):
            c = self.textCursor()
            c.setPosition(0)
            self.setTextCursor(c)
            scrollBar.setValue(0)

        else:
            state = self._editorState[self.preset]
            if cursor:
                c = self.textCursor()
                c.setPosition(state["cursor"])
                self.setTextCursor(c)

            if scroll:
                scrollBar = self.verticalScrollBar()
                scrollBar.setValue(state["scroll"])

            if bookmarks:
                for i in state.get("bookmarks", []):
                    self.setBookmark(i)

        self.ignoreStates = False

    def saveState(self, cursor=True, scroll=True, bookmarks=False):
        if not self.preset or self.ignoreStates:
            return

        if not self._editorState.get(self.preset):
            self._editorState[self.preset] = {"cursor": 0, "scroll": 0, "bookmarks": []}

        state = self._editorState[self.preset]

        if cursor:
            state["cursor"] = self.textCursor().position()
        if scroll:
            state["scroll"] = self.verticalScrollBar().value()
        if bookmarks:
            doc = self.document()

            state["bookmarks"] = []
            for i in range(doc.blockCount()):
                b = doc.findBlockByNumber(i)
                data = b.userData()
                if data and data.hasBookmark:
                    state["bookmarks"].append(i)
    
    def getMenu(self):
        menu = QMenu(self)
        menu.addAction("Swoop search", self.swoopSearch, "F3")
        menu.addAction("Highlight selected", self.highlightSelected, "Ctrl+H")
        menu.addSeparator()
        menu.addAction("Goto line", self.gotoLine, "Ctrl+G")
        menu.addAction("Duplicate line", self.duplicateLine, "Ctrl+D")
        menu.addAction("Move line up", lambda: self.moveLine("up"), "Alt+Up")
        menu.addAction("Move line down", lambda: self.moveLine("down"), "Alt+Down")
        menu.addAction("Remove line", self.removeLines, "Ctrl+K")
        menu.addAction("Comment line", self.toggleCommentBlock, "Ctrl+;")
        menu.addSeparator()
        menu.addAction("Set bookmark", self.setBookmark, "Alt+F2")
        menu.addAction("Next bookmark", self.gotoNextBookmark, "F2")
        menu.addSeparator()
        menu.addAction("Select All", self.selectAll, "Ctrl+A")
        return menu

    def contextMenuEvent(self, event):
        menu = self.getMenu()
        menu.popup(event.globalPos())

    def wheelEvent(self, event):
        shift = event.modifiers() & Qt.ShiftModifier
        ctrl = event.modifiers() & Qt.ControlModifier
        alt = event.modifiers() & Qt.AltModifier

        if ctrl:
            d = event.delta() / abs(event.delta())
            font = self.font()
            sz = clamp(fontSize(font) + d, 8, 40)
            setFontSize(font, sz)
            self.setFont(font)
            self.parent().numberBarWidget.updateState()

        else:
            super().wheelEvent(event)

    def keyPressEvent(self, event):
        shift = event.modifiers() & Qt.ShiftModifier
        ctrl = event.modifiers() & Qt.ControlModifier
        alt = event.modifiers() & Qt.AltModifier
        key = event.key()

        if ctrl and alt and key == Qt.Key_Space:
            self.selectInBracket()

        elif key in [Qt.Key_Left, Qt.Key_Right]:
            super().keyPressEvent(event)
            self.completionWidget.hide()

        elif key == Qt.Key_Escape:
            self.completionWidget.hide()

        elif key == Qt.Key_Return:
            if self.completionWidget.isVisible():
                self.replaceWithAutoCompletion()

                self.completionWidget.hide()
            else:
                cursor = self.textCursor()
                block = cursor.block().text()
                spc = re.search("^(\\s*)", block).groups("")[0]

                super().keyPressEvent(event)

                if spc:
                    cursor.insertText(spc)
                    self.setTextCursor(cursor)

        elif key == Qt.Key_Backtab:
            self.decreaseIndent()

        elif key in [Qt.Key_Up, Qt.Key_Down, Qt.Key_PageDown, Qt.Key_PageUp]:
            if self.completionWidget.isVisible():
                keyMove = {Qt.Key_Up: -1, Qt.Key_Down: 1, Qt.Key_PageDown: 10, Qt.Key_PageUp: -10}
                d = keyMove.get(key, 0)

                self.completionWidget.gotoLine(self.completionWidget.currentLine()+d)
            else:
                super().keyPressEvent(event)

        else:
            super().keyPressEvent(event)

    def decreaseIndent(self):
        cursor = self.textCursor()
        tabSpaces = " "*CodeEditorWidget.TabSpaces
        start, end = cursor.selectionStart(), cursor.selectionEnd()
        cursor.clearSelection()

        cursor.setPosition(start)

        cursor.beginEditBlock()
        while cursor.position() < end:
            cursor.movePosition(QTextCursor.StartOfLine)
            cursor.movePosition(QTextCursor.NextWord, QTextCursor.KeepAnchor)
            selText = cursor.selectedText()

            # if the text starts with the tab_char, replace it
            if selText.startswith(tabSpaces):
                text = selText.replace(tabSpaces, "", 1)
                end -= len(tabSpaces)
                cursor.insertText(text)

            if not cursor.movePosition(QTextCursor.Down):
                break

        cursor.endEditBlock()

    def selectInBracket(self):
        cursor = self.textCursor()
        pos = cursor.position()
        start, end = findBracketSpans(self.toPlainText(), pos)
        if start is not None and end is not None:
            cursor.setPosition(start+1)
            cursor.setPosition(end, QTextCursor.KeepAnchor)
            self.setTextCursor(cursor)

    def swoopSearch(self):        
        self.swoopSearchDialog.exec_()

    def duplicateLine(self):
        cursor = self.textCursor()
        line = cursor.block().text()
        cursor.movePosition(QTextCursor.EndOfBlock)
        cursor.beginEditBlock()
        cursor.insertBlock()
        cursor.insertText(line)
        cursor.endEditBlock()
        self.setTextCursor(cursor)        

    def moveLine(self, direction):
        cursor = self.textCursor()

        text = cursor.block().text()
        pos = cursor.positionInBlock()

        cursor.beginEditBlock()
        cursor.movePosition(QTextCursor.StartOfBlock)
        cursor.movePosition(QTextCursor.EndOfBlock, QTextCursor.KeepAnchor)
        cursor.removeSelectedText()

        if direction == "up":
            cursor.deletePreviousChar()
            cursor.movePosition(QTextCursor.StartOfBlock)
            cursor.insertText(text)
            cursor.insertBlock()
            cursor.movePosition(QTextCursor.Up)

        elif direction == "down":
            cursor.deleteChar()
            cursor.movePosition(QTextCursor.EndOfBlock)
            cursor.insertBlock()
            cursor.insertText(text)

        cursor.endEditBlock()        
        cursor.movePosition(QTextCursor.StartOfBlock)
        cursor.movePosition(QTextCursor.Right, n=pos)

        self.setTextCursor(cursor)

    def centerLine(self):
        cursorY = self.cursorRect().top()
        scrollBar = self.verticalScrollBar()
        scrollBar.setValue(scrollBar.value() + cursorY - self.geometry().height()/2)

    def removeLines(self):
        cursor = self.textCursor()

        if cursor.hasSelection():
            startLine, endLine = self.selectedLineRange(cursor)

            cursor.beginEditBlock()
            cursor.setPosition(self.document().findBlockByLineNumber(startLine).position())

            for _ in range(endLine-startLine+1):
                self.removeLine(cursor)

            cursor.endEditBlock()
            self.setTextCursor(cursor)
            
        else:
            self.removeLine()

    def removeLine(self, initialCursor=None):
        cursor = initialCursor or self.textCursor()
        cursor.beginEditBlock()
        cursor.movePosition(QTextCursor.StartOfBlock)
        cursor.movePosition(QTextCursor.NextBlock, QTextCursor.KeepAnchor)
        cursor.removeSelectedText()
        cursor.endEditBlock()
        if not initialCursor:
            self.setTextCursor(cursor)    

    def toggleCommentBlock(self):
        cursor = self.textCursor()        
        selectedText = cursor.selectedText()

        if selectedText:
            startLine, endLine = self.selectedLineRange()
            cursor.beginEditBlock()

            cursor.setPosition(self.document().findBlockByLineNumber(startLine).position())
            c = self.indentSizeUnderCursor(cursor)
            
            for _ in range(endLine-startLine+1):
                self.toggleCommentLine(cursor, columnPosition=c)
            cursor.endEditBlock()
            self.setTextCursor(cursor)

        else:
            self.toggleCommentLine()

    def indentSizeUnderCursor(self, cursor):
        cursor.select(QTextCursor.LineUnderCursor)
        line = cursor.selectedText()
        return len(re.match("^\\s*", line).group())

    def toggleCommentLine(self, initialCursor=None, *, columnPosition=None):
        cursor = initialCursor or self.textCursor()

        linePos = cursor.block().position()
        cursor.select(QTextCursor.LineUnderCursor)
        lineText = cursor.selectedText()
        cursor.clearSelection()

        indentSize = self.indentSizeUnderCursor(cursor)       

        cursor.beginEditBlock()

        m = re.match("^\\s*({}\\s?)".format(re.escape(self.commentChar)), lineText)
        if not m:
            offset = indentSize if columnPosition is None else min(indentSize, columnPosition)
            cursor.setPosition(linePos + offset)
            cursor.insertText(self.commentChar + " ")
        else:
            # some line
            cursor.setPosition(linePos + indentSize)
            for _ in range(len(m.group(1))):
                cursor.deleteChar()            
            
        cursor.endEditBlock()

        cursor.movePosition(QTextCursor.NextBlock)
        if not initialCursor:
            self.setTextCursor(cursor)        

    def selectedLineRange(self, initialCursor=None):
        cursor = initialCursor or self.textCursor()
        doc = self.document()
        ss = cursor.selectionStart()
        se = cursor.selectionEnd()
        sl = doc.findBlock(ss).blockNumber()
        el = doc.findBlock(se).blockNumber()
        startLine = min(sl, el)
        endLine = max(sl, el)
        cursor.setPosition(se)
        if cursor.columnNumber() == 0:
            endLine -= 1
        return startLine, endLine

    def gotoLine(self, line=-1):
        if line == -1:
            cursor = self.textCursor()
            currentLine = cursor.blockNumber()+1
            maxLine = self.document().lineCount()
            line, ok = QInputDialog.getInt(self, "Editor", "Goto line number", currentLine, 1, maxLine)
            if not ok:
                return

        self.setTextCursor(QTextCursor(self.document().findBlockByLineNumber(line-1)))

    def replaceWithAutoCompletion(self):
        if self.completionWidget.lineCount() == 0:
            return

        block = self.completionWidget.textCursor().block()
        word = block.text().split()[0]

        cursor = self.textCursor()
        cursor.setPosition(self._currentWord[1])
        cursor.setPosition(self._currentWord[2], QTextCursor.KeepAnchor)
        cursor.removeSelectedText()
        cursor.insertText(word)
        self.setTextCursor(cursor)
        self._canShowCompletions = False

    def highlightSelected(self):
        cursor = self.textCursor()
        sel = cursor.selectedText()

        reg = None
        if sel:
            reg = QRegExp("%s"%QRegExp.escape(sel))
        else:
            word, _,_ = wordAtCursor(cursor)
            if word:
                if word.startswith("@"):
                    reg = QRegExp("@\\b%s\\b"%QRegExp.escape(word[1:]))
                else:
                    reg = QRegExp("\\b%s\\b"%QRegExp.escape(word))

        self.syntax.highlightedWordRegexp = reg

        self.blockSignals(True)
        self.syntax.rehighlight()
        self.blockSignals(False)

    def editorCursorPositionChanged(self):
        cursor = self.textCursor()
        pos = cursor.position()

        if abs(pos - self._prevCursorPosition) > 1:
            self.completionWidget.hide()

        if cursor.selectedText():
            self.setExtraSelections([])
            return

        self.saveState(cursor=True, scroll=False, bookmarks=False)

        self._prevCursorPosition = pos

        start, end = findBracketSpans(self.toPlainText(), pos)

        extra = []
        for pos in [start, end]:
            if pos is None:
                continue
            cursor = self.textCursor()
            cursor.setPosition(pos)
            cursor.setPosition(pos+1, QTextCursor.KeepAnchor)
            es = QTextEdit.ExtraSelection()
            es.cursor = cursor
            es.format.setForeground(QColor(0, 0, 0))
            es.format.setBackground(QColor(200, 140, 140) if start is None or end is None else QColor(70, 130, 140))
            extra.append(es)

        self.setExtraSelections(extra)

    def editorTextChanged(self):
        text = self.toPlainText()

        cursor = self.textCursor()

        self._currentWord = wordAtCursor(cursor)
        currentWord, start, end = self._currentWord

        if start == 0 and end - start <= 1:
            return

        words = set(self.words)
        words |= set(re.split("[^\\w@]+", text))
        words -= set([currentWord])

        if currentWord:
            self._searchStartWord = self._currentWord
            items = [w for w in words if re.match(currentWord, w, re.IGNORECASE)]

            if items and cursor.position() == end:
                self.showCompletions(items)
            else:
                self.completionWidget.hide()

        else:
            self.completionWidget.hide()

    def showCompletions(self, items):
        rect = self.cursorRect()
        c = rect.center()

        self.completionWidget.setGeometry(c.x(), c.y()+10, 200, 200)
        if items:
            self.completionWidget.updateItems(items)

        self.completionWidget.show()

class NumberBarWidget(QWidget):
    def __init__(self, textWidget, *kwargs):
        super().__init__(*kwargs)
        self.textWidget = textWidget
        self.highest_line = 0

    def updateState(self, *args):
        self.setFont(self.textWidget.font())

        width = self.fontMetrics().width(str(self.highest_line)) + 19
        self.setFixedWidth(width)
        self.update()

    def paintEvent(self, event):
        contents_y = self.textWidget.verticalScrollBar().value()
        page_bottom = contents_y + self.textWidget.viewport().height()
        font_metrics = self.fontMetrics()
        current_block = self.textWidget.document().findBlock(self.textWidget.textCursor().position())

        painter = QPainter(self)

        line_count = 0
        # Iterate over all text blocks in the document.
        block = self.textWidget.document().begin()
        while block.isValid():
            line_count += 1

            # The top left position of the block in the document
            position = self.textWidget.document().documentLayout().blockBoundingRect(block).topLeft()

            # Check if the position of the block is out side of the visible
            # area.
            if position.y() > page_bottom:
                break

            # Draw the line number right justified at the y position of the
            # line. 3 is a magic padding number. drawText(x, y, text).
            painter.drawText(self.width() - font_metrics.width(str(line_count)) - 3, round(position.y()) - contents_y + font_metrics.ascent(), str(line_count))
            data = block.userData()
            if data and data.hasBookmark:
                painter.drawText(3, round(position.y()) - contents_y + font_metrics.ascent(), "*")

            block = block.next()

        self.highest_line = self.textWidget.document().blockCount()
        painter.end()

        QWidget.paintEvent(self, event)

class CodeEditorWithNumbersWidget(QWidget):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)

        self.editorWidget = CodeEditorWidget()

        self.numberBarWidget = NumberBarWidget(self.editorWidget)
        self.editorWidget.document().blockCountChanged.connect(lambda _: self.numberBarWidget.updateState())
        self.editorWidget.document().documentLayoutChanged.connect(self.numberBarWidget.updateState)
        self.editorWidget.verticalScrollBar().valueChanged.connect(lambda _: self.numberBarWidget.updateState())

        hlayout = QHBoxLayout()
        hlayout.setContentsMargins(0, 0, 0, 0)
        hlayout.addWidget(self.numberBarWidget)
        hlayout.addWidget(self.editorWidget)

        self.setLayout(hlayout)
