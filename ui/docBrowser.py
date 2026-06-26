from typing import Optional
from functools import partial
import asyncio

from .qt import *
from .. import ai
from ..ai import engine
from ..core import Module
from ..core.logger import logger

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
                
                summary = await ai.run("doc_generator", combinedText)
            
            return summary

        try:
            summary = asyncio.run(_internal())
            self.finished.emit(summary)
        except Exception as e:
            logger.error(f"Error generating documentation: {e}")
            self.finished.emit("")

class DocBrowser(QTextBrowser):
    """Markdown browser for module documentation with AI generation."""
    
    moduleRequested = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)

        self.setOpenLinks(False)
        self.anchorClicked.connect(self._onAnchorClicked)
        self.setPlaceholderText("Double-click to edit. Markdown supported.")

        self.module = None
        self._worker = None
        self._generating = False

    def updateDoc(self, module: Optional[Module] = None):
        if module is not None:
            self.module = module
            
        if not self.module:
            self.clear()
            return

        self.setMarkdown(self.module.doc())

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
        if not self.module or self._generating:
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

        self._generating = True
        self.setMarkdown("Generating...")
        
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
        self._generating = False
        
        if summary:
            module.setDoc(summary)
            # Only refresh UI if the returned module is still selected
            if module == self.module:
                self.updateDoc()
        else:
            QMessageBox.warning(self, "Rig Builder", "AI failed to generate documentation.")
            if module == self.module:
                self.updateDoc()

    def contextMenuEvent(self, event):
        """Show standard context menu extended with doc editing and AI generation actions."""
        menu = self.createStandardContextMenu()
        menu.addSeparator()

        editAction = menu.addAction("Edit")
        editAction.setEnabled(bool(self.module) and not self._generating)
        editAction.triggered.connect(self._onEditDoc)

        if engine.IS_OLLAMA_AVAILABLE:
            if self._generating:
                genAction = menu.addAction("⌛ Generating...")
                genAction.setEnabled(False)
            else:
                genAction = menu.addAction("✨ Generate with AI")
                genAction.setEnabled(bool(self.module))
                genAction.triggered.connect(self._onGenerateDoc)

        menu.exec_(event.globalPos())

    def _onEditDoc(self):
        """Open editor dialog to manually edit the module documentation."""
        if not self.module or self._generating:
            return

        from .widgets import EditTextDialog

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

    def mouseDoubleClickEvent(self, event):
        """Edit source text and save it to module."""
        self._onEditDoc()
