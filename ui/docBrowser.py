from typing import Optional
from functools import partial
from ..qt import *
from ..core import Module
from .logger import logger
import markdown

def convertMarkdownToHTML(text: str) -> str:
    """Convert Markdown to HTML."""
    return markdown.markdown(
        text, 
        extensions=['fenced_code', 'codehilite', 'tables', 'extra', 'sane_lists'], 
        output_format="html5")

def convertTextToHTML(text: str) -> str:
    """Convert text to HTML."""
    return text.replace("\n", "<br>").replace("\t", "&nbsp;"*4)

class DocBrowser(QTextBrowser):
    """HTML/Markdown browser for module documentation."""
    
    moduleRequested = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)

        self.setOpenLinks(False)
        self.anchorClicked.connect(self._onAnchorClicked)
        self.setPlaceholderText("Double-click to edit. HTML or Markdown supported.")
        self.document().setDefaultStyleSheet("a { color: #55aaee; }")
        
        self.module = None

    def updateDoc(self, module: Optional[Module] = None):
        if module is not None:
            self.module = module
            
        if not self.module:
            self.clear()
            return

        if self.module.docFormat() == "markdown":
            html = convertMarkdownToHTML(self.module.doc())
        else:
            html = convertTextToHTML(self.module.doc())

        self.setHtml(html)

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
        if not self.module:
            return

        def setDocFormat(format: str):
            self.module.setDocFormat(format)
            self.updateDoc()

        menu = QMenu(self)
        action = menu.addAction("Show as HTML", partial(setDocFormat, "html"))
        action.setCheckable(True)
        action.setChecked(self.module.docFormat() == "html")

        action = menu.addAction("Show as Markdown", partial(setDocFormat, "markdown"))
        action.setCheckable(True)
        action.setChecked(self.module.docFormat() == "markdown")

        menu.popup(event.globalPos())

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
