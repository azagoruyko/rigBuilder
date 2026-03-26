import difflib
from ..qt import *
from .utils import centerWindow

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
        self.textEdit = QPlainTextEdit()
        self.textEdit.setReadOnly(True)
        self.textEdit.setPlainText(diffText)
        DiffHighlighter(self.textEdit.document())
        layout.addWidget(self.textEdit)

        closeBtn = QPushButton("🚪 Close")
        closeBtn.clicked.connect(self.accept)
        layout.addWidget(closeBtn)

        centerWindow(self)
