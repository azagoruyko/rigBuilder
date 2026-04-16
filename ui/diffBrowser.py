import os
import difflib
import asyncio
from typing import List
from ..core import Module
from ..qt import *
from .utils import centerWindow
from .logger import logger
from .. import ai
from ..ai import engine


activeWorkers = []


def calculateModulesDiff(modules: List[Module]) -> str:
    """Calculate unified diffs for a list of modules against their disk state."""
    diffTexts = []
    for m in modules:
        filePath = m.referenceFile()
        if filePath and os.path.exists(filePath):
            try:
                with open(filePath, "r", encoding="utf-8") as f:
                    oldXml = f.read()
                newXml = m.toXml()
                diff = difflib.unified_diff(
                    oldXml.splitlines(),
                    newXml.splitlines(),
                    fromfile=filePath,
                    tofile=filePath + " (memory)",
                    lineterm=""
                )
                diffText = "\n".join(diff)
                if diffText:
                    diffTexts.append(diffText)
            except Exception as e:
                logger.error(f"Error calculating diff for {m.name()}: {e}")
        else:
            # New module or no file on disk - show all as additions
            newXml = m.toXml()
            diff = difflib.unified_diff(
                [],
                newXml.splitlines(),
                fromfile="/dev/null",
                tofile=m.name(),
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

    def __init__(self, parent: QTextDocument):
        super().__init__(parent)

        self.defaultFormat = QTextCharFormat()
        self.defaultFormat.setForeground(QColor(180, 180, 180))

        self.removedFormat = QTextCharFormat()
        self.removedFormat.setForeground(QColor(200, 100, 100))

        self.addedFormat = QTextCharFormat()
        self.addedFormat.setForeground(QColor(100, 200, 100))

        self.hunkFormat = QTextCharFormat()
        self.hunkFormat.setForeground(QColor(130, 130, 220))
        self.hunkFormat.setFontWeight(QFont.Bold)

        self.removedWordFormat = QTextCharFormat()
        self.removedWordFormat.setBackground(QColor(120, 50, 50))
        self.removedWordFormat.setForeground(QColor(255, 200, 200))

        self.addedWordFormat = QTextCharFormat()
        self.addedWordFormat.setBackground(QColor(50, 120, 50))
        self.addedWordFormat.setForeground(QColor(200, 255, 200))

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
        
        if text.startswith("-") and not text.startswith("---"):
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


class DiffBrowserDialog(QDialog):
    """Modal dialog showing inline unified diff with git-style coloring."""

    def __init__(self, originalText="", currentText="", fromDesc="", toDesc="", *, diffText="", **kwargs):
        super().__init__(**kwargs)

        if not diffText:
            diffLines = difflib.unified_diff(
                originalText.splitlines(),
                currentText.splitlines(),
                fromfile=fromDesc,
                tofile=toDesc,
                lineterm="",
            )
            diffText = "\n".join(diffLines)        

        self.setWindowTitle("Diff: {} vs {}".format(fromDesc, toDesc))
        self.setMinimumSize(700, 450)
        self.resize(900, 550)

        layout = QVBoxLayout(self)
        self.worker = None

        # Create Splitter
        self.splitter = QSplitter(Qt.Vertical)
        layout.addWidget(self.splitter)

        self.textEdit = QPlainTextEdit()
        self.textEdit.setReadOnly(True)
        self.textEdit.setPlainText(diffText)
        self.highlighter = DiffHighlighter(self.textEdit.document())
        self.splitter.addWidget(self.textEdit)

        # AI Summary Section
        self.aiGroup = QGroupBox("🤖 AI Summary")
        aiLayout = QVBoxLayout(self.aiGroup)
        
        self.aiText = QTextEdit()
        self.aiText.setReadOnly(True)
        self.aiText.setPlaceholderText("Analyzing changes...")
        self.aiText.setStyleSheet("font-style: italic; color: #8a92a3; background-color: #2b313b; border: none;")
        
        aiLayout.addWidget(self.aiText)
        self.splitter.addWidget(self.aiGroup)        

        self.splitter.setSizes([400, 400])

        closeBtn = QPushButton("Close")
        closeBtn.clicked.connect(self.accept)
        layout.addWidget(closeBtn)

        # Hide AI group if Ollama is not available or if there is no diff
        if not engine.OLLAMA_AVAILABLE or not diffText.strip():
            self.aiGroup.hide()
        else:
            # Create worker without parent so it's not destroyed with the dialog
            worker = DiffDescriptionWorker(diffText)
            worker.finished.connect(self._onAiFinished)
            
            # Keep alive in global list
            activeWorkers.append(worker)
            worker.finished.connect(lambda: activeWorkers.remove(worker) if worker in activeWorkers else None)
            
            worker.start()
            self.worker = worker

        centerWindow(self)

    def _onAiFinished(self, summary: str):
        if summary:
            self.aiText.setMarkdown(summary)
            self.aiText.setStyleSheet("color: #c8cfdb; background-color: #2b313b; border: none;") # Normal color once finished
        else:
            self.aiGroup.hide()
        self.worker = None
