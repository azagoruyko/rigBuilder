from __future__ import annotations

from .qt import QDesktopServices, QTextBrowser, QUrl, Signal, Qt
from .widgets.ui import EditTextDialog

HELP_TEXT = """HTML documentation for this module (double-click to edit).

Examples:
- Paragraph: <p>Short description of what this module does.</p>
- Section title: <h2>Usage</h2>
- External link: <a href="https://your.wiki/rig">Rigging guide</a>
- Open another module in Rig Builder: <a href="module:character/rig/Arm_L">Arm_L module</a>

Use basic HTML tags such as p, h2, ul, li, a, b, i.
You can also use module:SPEC links, where SPEC is anything you would pass to Module.loadModule(SPEC)
such as a UID, relative module path, or full path."""

class HtmlBrowser(QTextBrowser):
    """
    Generic HTML browser with embedded link handling:
    - http/https: open in system browser
    - other schemes: emitted via linkClicked for external handling
    """

    linkClicked = Signal(object)
    moduleLinkClicked = Signal(str)  # spec for Module.loadModule
    htmlEdited = Signal(str)         # emitted when HTML is edited via built-in editor

    def __init__(self, parent=None):
        super().__init__(parent)
        self._sourceHtml = ""
        self.setOpenLinks(False)
        self.anchorClicked.connect(self._onAnchorClicked)
        self.setPlaceholderText(HELP_TEXT)

        self.document().setDefaultStyleSheet("a { color: #55aaee; }")

    def setHtml(self, text: str) -> None:
        self._sourceHtml = text
        super().setHtml(text)

    def _onAnchorClicked(self, url):
        url = QUrl(url)
        scheme = url.scheme()

        if scheme in ("http", "https"):
            QDesktopServices.openUrl(url)
            return

        if scheme == "module":
            spec = url.toString()[len("module:") :].strip()
            if spec:
                self.moduleLinkClicked.emit(spec)
            return

        self.linkClicked.emit(url)

    def mouseDoubleClickEvent(self, event):
        """Open simple HTML editor on double click and emit htmlEdited on save."""
        del event

        def save(text):
            self.setHtml(text)
            self.htmlEdited.emit(text)

        w = EditTextDialog(
            self._sourceHtml,
            title="Edit HTML documentation",
            placeholder=HELP_TEXT,
            words=set(),
            python=False,
        )
        w.saved.connect(save)
        w.show()

