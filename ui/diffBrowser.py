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

class DiffHighlighter(QSyntaxHighlighter):
    """Git-style coloring for unified diff: removed red, added green, hunk header blue."""

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

    def highlightBlock(self, text: str):
        if not text:
            return
        
        if text.startswith("-") and not text.startswith("---"):
            self.setFormat(0, len(text), self.removedFormat)
        elif text.startswith("+") and not text.startswith("+++"):
            self.setFormat(0, len(text), self.addedFormat)
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
        DiffHighlighter(self.textEdit.document())
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
