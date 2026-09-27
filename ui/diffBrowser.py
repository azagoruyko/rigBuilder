from __future__ import annotations

import os
import difflib
import asyncio
from ..core import Module
from .qt import *
from .utils import centerWindow
from ..core.logger import logger
from .. import ai
from ..ai import engine

activeWorkers = []


def calculateModulesDiff(modules: list[Module], paths: list[str] | None = None) -> str:
    """Calculate unified diffs for the current in-memory module state vs its saved file."""
    diffTexts = []
    for index, m in enumerate(modules):
        filePath = paths[index] if paths is not None else m.referenceFile()
        preview = m.copy()
        if filePath:
            preview.setName(os.path.splitext(os.path.basename(filePath))[0])

        preview._muted = False
        for attr in preview.attributes():
            attr.setConnect("")

        newText = preview.toText()
        if filePath and os.path.exists(filePath):
            oldModule = Module.loadModule(filePath) # load and sync
            oldText = oldModule.toText()
            oldLabel = os.path.basename(filePath)
            newLabel = oldLabel + " (memory)"
            diff = difflib.unified_diff(
                oldText.splitlines(),
                newText.splitlines(),
                fromfile=oldLabel,
                tofile=newLabel,
                lineterm=""
            )
            diffText = "\n".join(diff)
            if diffText:
                diffTexts.append(diffText)
        else:
            # New module or no file on disk - show all as additions
            targetName = os.path.basename(filePath or m.name())
            diff = difflib.unified_diff(
                [],
                newText.splitlines(),
                fromfile="/dev/null",
                tofile=targetName,
                lineterm=""
            )
            diffText = "\n".join(diff)
            if diffText:
                diffTexts.append(diffText)

    return "\n".join(diffTexts)

class DiffUserData(QTextBlockUserData):
    """Custom data for storing intra-line diff spans for a block."""
    def __init__(self, spans=None):
        super().__init__()
        self.spans = spans or [] # List of (start, length, format_name)

class DiffHighlighter(QSyntaxHighlighter):
    """Git-style coloring with intra-line highlighting for unified diff."""

    def __init__(self, parent: QTextDocument, darkTheme: bool):
        super().__init__(parent)

        self.defaultFormat = QTextCharFormat()
        self.defaultFormat.setForeground(QColor(180, 180, 180) if darkTheme else QColor(45, 45, 45))

        self.removedFormat = QTextCharFormat()
        self.removedFormat.setForeground(QColor(220, 125, 125) if darkTheme else QColor(125, 25, 25))
        self.removedFormat.setBackground(QColor(65, 39, 43) if darkTheme else QColor(255, 232, 232))

        self.addedFormat = QTextCharFormat()
        self.addedFormat.setForeground(QColor(130, 215, 130) if darkTheme else QColor(20, 105, 45))
        self.addedFormat.setBackground(QColor(36, 60, 43) if darkTheme else QColor(226, 248, 230))

        self.hunkFormat = QTextCharFormat()
        self.hunkFormat.setForeground(QColor(150, 155, 235) if darkTheme else QColor(55, 65, 150))
        self.hunkFormat.setFontWeight(QFont.Bold)

        self.fileFormat = QTextCharFormat()
        self.fileFormat.setForeground(QColor(140, 190, 235) if darkTheme else QColor(35, 80, 135))
        self.fileFormat.setFontWeight(QFont.Bold)

        self.removedWordFormat = QTextCharFormat()
        self.removedWordFormat.setBackground(QColor(120, 50, 50) if darkTheme else QColor(245, 185, 185))
        self.removedWordFormat.setForeground(QColor(255, 200, 200) if darkTheme else QColor(95, 15, 15))

        self.addedWordFormat = QTextCharFormat()
        self.addedWordFormat.setBackground(QColor(50, 120, 50) if darkTheme else QColor(165, 225, 175))
        self.addedWordFormat.setForeground(QColor(200, 255, 200) if darkTheme else QColor(10, 75, 30))

        # Re-calculate diffs immediately
        self.recalculateIntraLineDiffs()

    def recalculateIntraLineDiffs(self):
        """Pre-calculate differences by matching '-' and '+' lines 1-to-1 in order."""
        doc = self.document()
        curr = doc.begin()
        
        while curr.isValid():
            text = curr.text()
            # Find the start of a '-' block
            if text.startswith("-") and not text.startswith("---"):
                minusStart = curr
                minusCount = 0
                while curr.isValid() and curr.text().startswith("-") and not curr.text().startswith("---"):
                    minusCount += 1
                    curr = curr.next()
                
                # Now curr is at the start of the next block. Check if it's a '+' block.
                if curr.isValid() and curr.text().startswith("+"):
                    plusStart = curr
                    plusCount = 0
                    while curr.isValid() and curr.text().startswith("+") and not curr.text().startswith("+++"):
                        plusCount += 1
                        curr = curr.next()
                    
                    # Match them 1-to-1 up to the smaller block size
                    count = min(minusCount, plusCount)
                    m = minusStart
                    p = plusStart
                    for _ in range(count):
                        self._calculateAndStoreDiff(m, p, m.text()[1:], p.text()[1:])
                        m = m.next()
                        p = p.next()
                continue
            curr = curr.next()

    def _calculateAndStoreDiff(self, m_block, p_block, oldText, newText):
        """Calculate character-level diffs and store in block metadata."""
        matcher = difflib.SequenceMatcher(None, oldText, newText)

        # If lines are too different, don't show intra-line highlights (GitHub-style behavior)
        if matcher.ratio() < 0.9:
            return

        m_spans = []
        p_spans = []
        for tag, i1, i2, j1, j2 in matcher.get_opcodes():
            if tag in ('delete', 'replace'):
                m_spans.append((i1 + 1, i2 - i1)) 
            if tag in ('insert', 'replace'):
                p_spans.append((j1 + 1, j2 - j1))
        
        if m_spans:
            data = m_block.userData() or DiffUserData()
            data.spans.extend(m_spans)
            m_block.setUserData(data)
            
        if p_spans:
            data = p_block.userData() or DiffUserData()
            data.spans.extend(p_spans)
            p_block.setUserData(data)

    def highlightBlock(self, text: str):
        if not text:
            return
        
        if text.startswith(("diff --git ", "--- ", "+++ ")):
            self.setFormat(0, len(text), self.fileFormat)

        elif text.startswith("-") and not text.startswith("---"):
            self.setFormat(0, len(text), self.removedFormat)
            data = self.currentBlock().userData()
            if data and isinstance(data, DiffUserData):
                for start, length in data.spans:
                    self.setFormat(start, length, self.removedWordFormat)

        elif text.startswith("+") and not text.startswith("+++"):
            self.setFormat(0, len(text), self.addedFormat)
            data = self.currentBlock().userData()
            if data and isinstance(data, DiffUserData):
                for start, length in data.spans:
                    self.setFormat(start, length, self.addedWordFormat)

        elif text.startswith("@@"):
            self.setFormat(0, len(text), self.hunkFormat)
        else:
            self.setFormat(0, len(text), self.defaultFormat)


class DiffDescriptionWorker(QThread):
    """Background worker to fetch AI-generated diff summary."""
    finished = Signal(str)

    def __init__(self, diffText: str, parent=None):
        super().__init__(parent)
        self.diffText = diffText

    def run(self):
        try:
            # Run the async ai.run in a new event loop for this thread
            summary = asyncio.run(ai.run("diff_description", self.diffText))
            self.finished.emit(summary)
        except Exception as e:
            print(f"Error analyzing diff: {e}")
            self.finished.emit("")


class DiffBrowserWidget(QWidget):
    """Widget showing inline unified diff with git-style coloring."""

    def __init__(self, originalText="", currentText="", fromDesc="", toDesc="", *, diffText="", parent=None, **kwargs):
        super().__init__(parent=parent, **kwargs)

        if not diffText:
            diffLines = difflib.unified_diff(
                originalText.splitlines(),
                currentText.splitlines(),
                fromfile=fromDesc,
                tofile=toDesc,
                lineterm="",
            )
            diffText = "\n".join(diffLines)        

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self.worker = None

        lines = diffText.splitlines()
        self.changeBlocks = [index for index, line in enumerate(lines) if line.startswith("@@")]
        added = sum(line.startswith("+") and not line.startswith("+++") for line in lines)
        removed = sum(line.startswith("-") and not line.startswith("---") for line in lines)

        toolbar = QHBoxLayout()
        if diffText.strip():
            self.summaryLabel = QLabel("")
            toolbar.addWidget(self.summaryLabel)
        else:
            self.summaryLabel = QLabel("No changes to review")
            toolbar.addWidget(self.summaryLabel)
        toolbar.addStretch()
        layout.addLayout(toolbar)

        self.textEdit = QPlainTextEdit()
        self.textEdit.setReadOnly(True)
        self.textEdit.setFont(QFontDatabase.systemFont(QFontDatabase.FixedFont))
        self.textEdit.setPlainText(diffText if diffText.strip() else "No changes to review.")
        darkTheme = self.textEdit.palette().color(QPalette.Base).lightness() < 128
        self.highlighter = DiffHighlighter(self.textEdit.document(), darkTheme)
        layout.addWidget(self.textEdit, 1)

        self.aiButton = QPushButton("AI summary ▸")
        self.aiButton.setCheckable(True)
        self.aiButton.toggled.connect(self.toggleAiSummary)
        layout.addWidget(self.aiButton)
        self.aiText = QTextEdit()
        self.aiText.setReadOnly(True)
        self.aiText.setPlaceholderText("Analyzing changes...")
        self.aiText.setStyleSheet("font-style: italic; color: #8a92a3; background-color: #2b313b; border: none;")
        self.aiText.setFixedHeight(130)
        self.aiText.hide()
        layout.addWidget(self.aiText)

        if not engine.isOllamaAvailable() or not diffText.strip():
            self.aiButton.hide()
        else:
            worker = DiffDescriptionWorker(diffText)
            worker.finished.connect(self._onAiFinished)
            activeWorkers.append(worker)
            worker.finished.connect(lambda: activeWorkers.remove(worker))
            worker.start()
            self.worker = worker

    def toggleAiSummary(self, visible: bool):
        """Expand or collapse the optional AI summary."""
        self.aiButton.setText("AI summary ▾" if visible else "AI summary ▸")
        self.aiText.setVisible(visible)

    def _onAiFinished(self, summary: str):
        if summary:
            self.aiText.setMarkdown(summary)
            self.aiText.setStyleSheet("color: #c8cfdb; background-color: #2b313b; border: none;") # Normal color once finished
        else:
            self.aiButton.hide()
            self.aiText.hide()
        self.worker = None


class DiffBrowserDialog(QDialog):
    """Modal dialog showing inline unified diff with git-style coloring."""

    def __init__(self, originalText="", currentText="", fromDesc="", toDesc="", *, diffText="", parent=None, **kwargs):
        super().__init__(parent=parent, **kwargs)

        self.setWindowTitle("Diff: {} vs {}".format(fromDesc, toDesc))
        self.setMinimumSize(700, 450)
        self.resize(900, 550)

        layout = QVBoxLayout(self)
        self.browserWidget = DiffBrowserWidget(originalText, currentText, fromDesc, toDesc, diffText=diffText)
        layout.addWidget(self.browserWidget)

        closeBtn = QPushButton("Close")
        closeBtn.clicked.connect(self.accept)
        layout.addWidget(closeBtn)

        centerWindow(self)


class DiffBrowserDialogWithConfirm(QDialog):
    """Modal dialog showing diff with Confirm/Cancel buttons."""

    def __init__(self, originalText="", currentText="", fromDesc="", toDesc="", *, diffText="", parent=None, **kwargs):
        super().__init__(parent=parent, **kwargs)

        self.setWindowTitle("Confirm Changes: {} vs {}".format(fromDesc, toDesc))
        self.setMinimumSize(700, 450)
        self.resize(900, 550)

        layout = QVBoxLayout(self)
        self.browserWidget = DiffBrowserWidget(originalText, currentText, fromDesc, toDesc, diffText=diffText)
        layout.addWidget(self.browserWidget)

        btnLayout = QHBoxLayout()
        confirmBtn = QPushButton("Confirm")
        confirmBtn.clicked.connect(self.accept)
        cancelBtn = QPushButton("Cancel")
        cancelBtn.clicked.connect(self.reject)
        
        btnLayout.addStretch()
        btnLayout.addWidget(confirmBtn)
        btnLayout.addWidget(cancelBtn)

        layout.addLayout(btnLayout)

        centerWindow(self)
