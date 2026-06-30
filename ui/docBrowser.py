import asyncio
import markdown
from typing import Optional
from pygments.formatters import HtmlFormatter

from .qt import *
from .. import ai
from ..ai import engine
from ..core.logger import logger

activeWorkers = []

# Generate pygments syntax coloring CSS rules once at module level
_formatter = HtmlFormatter(style='monokai')
highlighterCss = _formatter.get_style_defs('.codehilite') + "\n.codehilite { background-color: transparent !important; }"

class DocGeneratorWorker(QThread):
    """Background worker to fetch AI-generated documentation."""
    finished = Signal(str)

    def __init__(self, code: str, childrenDocs: str = "", parent=None):
        super().__init__(parent)
        self.code = code
        self.childrenDocs = childrenDocs

    def run(self):
        async def _internal():
            summary = ""
            # Step 1: Generate doc for the current module code if available
            if self.code:
                summary = await ai.run("code_description", self.code)
            
            # Step 2: If we have children docs, synthesize them with the module's summary
            if self.childrenDocs:
                if summary:
                    combinedText = f"Module Summary:\n{summary}\n\nChildren Modules Documentation:\n{self.childrenDocs}"
                else:
                    combinedText = f"Children Modules Documentation:\n{self.childrenDocs}"
                
                summary = await ai.run("doc_generator", combinedText)
            
            return summary

        try:
            summary = asyncio.run(_internal())
            self.finished.emit(summary)
        except Exception as e:
            logger.error(f"Error generating documentation: {e}")
            self.finished.emit("")


class DocBrowser(QTextBrowser):
    """Generic markdown browser for displaying documentation with edit signals."""
    
    moduleRequested = Signal(str)
    editRequested = Signal()
    generationRequested = Signal()

    def __init__(self, parent=None, editable=True):
        super().__init__(parent)
        self.editable = editable
        self._generating = False
        self.zoomLevel = 0

        self.setOpenLinks(False)
        self.setOpenExternalLinks(True)
        self.anchorClicked.connect(self._onAnchorClicked)
        self.setPlaceholderText("Double-click to edit. Markdown supported.")


    def zoomIn(self, range: int = 1):
        super().zoomIn(range)
        self.zoomLevel += range

    def zoomOut(self, range: int = 1):
        super().zoomOut(range)
        self.zoomLevel -= range

    def resetZoom(self):
        if self.zoomLevel > 0:
            super().zoomOut(self.zoomLevel)
        elif self.zoomLevel < 0:
            super().zoomIn(-self.zoomLevel)
        self.zoomLevel = 0

    def wheelEvent(self, event: QWheelEvent):
        if event.modifiers() == Qt.ControlModifier:
            if event.angleDelta().y() > 0:
                self.zoomIn(1)
            else:
                self.zoomOut(1)
            event.accept()
        else:
            super().wheelEvent(event)

    def keyPressEvent(self, event: QKeyEvent):
        if event.modifiers() == Qt.ControlModifier:
            key = event.key()
            if key in (Qt.Key_Plus, Qt.Key_Equal):
                self.zoomIn(1)
                event.accept()
                return
            elif key == Qt.Key_Minus:
                self.zoomOut(1)
                event.accept()
                return
            elif key == Qt.Key_0:
                self.resetZoom()
                event.accept()
                return
        super().keyPressEvent(event)

    def setGenerating(self, generating: bool):
        self._generating = generating
        if generating:
            self.setPlaceholderText("⌛ Generating documentation with AI...")
            self.clear()
        else:
            self.setPlaceholderText("Double-click to edit. Markdown supported.")

    def setDoc(self, docText: str):
        """Directly convert markdown doc text to HTML and display it with custom styles."""
        if not docText:
            self.setHtml("<p style='color: #8a92a3; font-style: italic;'>No documentation available.</p>")
            return

        html = markdown.markdown(
            docText,
            extensions=["fenced_code", "tables", "nl2br",
                        "sane_lists", "codehilite", "toc", "extra"],
            output_format="html5")

        htmlStyled = f"""
        <style>
            body {{
                color: #e8eaed;
                line-height: 1.4;
            }}
            h1, h2, h3, h4 {{
                color: #6ea7ff;
                margin-top: 10px;
                margin-bottom: 5px;
            }}
            pre {{
                background-color: #1a1e24;
                border: 1px solid #343c49;
                border-radius: 4px;
                padding: 8px;
            }}
            code {{
                background-color: #1a1e24;
                color: #e5c07b;
                padding: 1px 3px;
                border-radius: 3px;
            }}
            a {{
                color: #55aaee;
                text-decoration: none;
            }}
            {highlighterCss}
        </style>
        {html}
        """
        self.setHtml(htmlStyled)

    def _onAnchorClicked(self, url):
        url = QUrl(url)
        scheme = url.scheme()

        if scheme in ("http", "https"):
            QDesktopServices.openUrl(url)
            return

        if scheme == "module":
            spec = url.toString()[len("module:"):].strip()
            if spec:
                self.moduleRequested.emit(spec)
            return

    def contextMenuEvent(self, event):
        """Show standard context menu extended with doc editing and AI generation actions."""
        if not self.editable:
            super().contextMenuEvent(event)
            return

        menu = self.createStandardContextMenu()
        menu.addSeparator()

        editAction = menu.addAction("Edit")
        editAction.setEnabled(not self._generating)
        editAction.triggered.connect(self.editRequested.emit)

        if engine.IS_OLLAMA_AVAILABLE:
            if self._generating:
                genAction = menu.addAction("⌛ Generating...")
                genAction.setEnabled(False)
            else:
                genAction = menu.addAction("✨ Generate with AI")
                genAction.triggered.connect(self.generationRequested.emit)

        menu.exec_(event.globalPos())

    def mouseDoubleClickEvent(self, event):
        """Emit edit signal if editable."""
        if not self.editable or self._generating:
            super().mouseDoubleClickEvent(event)
            return
        self.editRequested.emit()
