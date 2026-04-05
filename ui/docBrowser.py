from typing import Optional
from functools import partial
from ..qt import *
from ..core import Module
from .logger import logger


class DocBrowser(QTextBrowser):
    """Markdown browser for module documentation."""
    
    moduleRequested = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)

        self.setOpenLinks(False)
        self.anchorClicked.connect(self._onAnchorClicked)
        self.setPlaceholderText("Double-click to edit. Markdown supported.")
        self.document().setDefaultStyleSheet("a { color: #55aaee; }")
        
        self.module = None

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
