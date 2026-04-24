from typing import Optional
from functools import partial
import asyncio

from ..qt import *
from .. import ai
from ..ai import engine
from ..core import Module
from ..logger import logger


activeWorkers = []

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
                
                summary = await ai.run("summarizer", combinedText)
            
            return summary

        try:
            summary = asyncio.run(_internal())
            self.finished.emit(summary)
        except Exception as e:
            logger.error(f"Error generating documentation: {e}")
            self.finished.emit("")

class DocBrowser(QWidget):
    """Markdown browser for module documentation with AI generation."""
    
    moduleRequested = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(2)

        # Internal Text Browser
        self.browser = QTextBrowser(self)
        self.browser.setOpenLinks(False)
        self.browser.anchorClicked.connect(self._onAnchorClicked)
        self.browser.setPlaceholderText("Double-click to edit. Markdown supported.")
        
        layout.addWidget(self.browser)

        # AI Generation Header (Bottom Right)
        footerLayout = QHBoxLayout()
        footerLayout.setContentsMargins(0, 0, 0, 0)
        footerLayout.addStretch()
        self.genButton = QPushButton("✨ Generate doc")
        self.genButton.setToolTip("Generate documentation from module's run code using AI")
        self.genButton.clicked.connect(self._onGenerateDoc)
        footerLayout.addWidget(self.genButton)
        layout.addLayout(footerLayout)

        # Context Menu & Event Overrides for the internal browser
        self.browser.contextMenuEvent = self.contextMenuEvent
        self.browser.mouseDoubleClickEvent = self.mouseDoubleClickEvent
        
        self.module = None
        self._worker = None

        if not engine.IS_OLLAMA_AVAILABLE:
            self.genButton.hide()

    def updateDoc(self, module: Optional[Module] = None):
        if module is not None:
            self.module = module
            
        if not self.module:
            self.browser.clear()
            self.genButton.setEnabled(False)
            return

        self.browser.setMarkdown(self.module.doc())
        self.genButton.setEnabled(True)

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

    def _onGenerateDoc(self):
        if not self.module:
            return

        # Prepare children documentation context
        childrenDocs = []
        for ch in self.module.children():
            doc = ch.doc().strip()
            if doc:
                childrenDocs.append(f"### {ch.name()}\n{doc}")
        
        childrenDocsStr = "\n\n".join(childrenDocs)

        code = self.module.runCode()
        if not code and not childrenDocsStr:
            QMessageBox.warning(self, "Rig Builder", "Module has no run code and no children documentation to analyze.")
            return

        self.genButton.setEnabled(False)
        self.genButton.setText("⌛ Generating...")
        
        # Create worker without parent so it's not destroyed with the widget
        self._worker = DocGeneratorWorker(code, childrenDocsStr)
        
        # Keep alive in global list
        activeWorkers.append(self._worker)
        self._worker.finished.connect(lambda: activeWorkers.remove(self._worker) if self._worker in activeWorkers else None)
        
        # Capture current module to ensure generation finishes on the correct one
        callback = partial(self._onGenerationFinished, self.module)
        self._worker.finished.connect(callback)
        self._worker.start()

    def _onGenerationFinished(self, module: Module, summary: str):
        self.genButton.setEnabled(True)
        self.genButton.setText("✨ Generate doc")
        
        if summary:
            module.setDoc(summary)
            # Only refresh UI if the returned module is still selected
            if module == self.module:
                self.updateDoc()
        else:
            QMessageBox.warning(self, "Rig Builder", "AI failed to generate documentation.")

    def mouseDoubleClickEvent(self, event):
        """Edit source text and save it to module."""
        if not self.module:
            return

        from ..widgets.ui import EditTextDialog

        def save(text):
            self.module.setDoc(text)
            self.updateDoc()

        w = EditTextDialog(
            self.module.doc(),
            title="Edit documentation",
            placeholder="Enter documentation here...",
            words=set(),
            python=False,
            parent=self)

        w.saved.connect(save)
        w.show()
