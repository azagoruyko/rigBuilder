"""API Registry browser. Shows registered names, docstrings, and signatures for user reference."""

from __future__ import annotations

import inspect
from typing import Any

from ..core import APIRegistry
from ..qt import *

def getObjectInfo(name: str, obj: Any) -> tuple[str, str, str, str]:
    """Helper to extract type, header, and docstring for an object."""
    objType = type(obj)
    
    if inspect.isclass(obj):
        typeName = "class"
    elif inspect.isroutine(obj):
        typeName = "def"
    else:
        typeName = objType.__name__
    
    sigParams = ""
    if callable(obj):
        try:
            sig = inspect.signature(obj)
            sigParams = str(sig)
        except (ValueError, TypeError):
            sigParams = "(...)"
    
    # Hide docstrings for simple built-ins to reduce noise
    isSimpleBuiltin = objType.__module__ == "builtins" and not inspect.isroutine(obj) and not inspect.isclass(obj)
    
    doc = ""
    if not isSimpleBuiltin:
        doc = inspect.getdoc(obj) or ""
        
    header = f"<span class='keyword'>{typeName}</span> <span class='name'>{name}</span>{sigParams}"
    return typeName, header, doc, sigParams

def getMatchingMembers(obj: Any, filterText: str, displayedTypes: set[int]) -> list[tuple[str, str]]:
    """Collect public members of an object that match the given filter."""
    objType = obj if inspect.isclass(obj) else type(obj)
    typeId = id(objType)
    
    isClass = inspect.isclass(obj)
    isInstance = not inspect.isroutine(obj) and not isClass and not isinstance(obj, (int, float, str, list, dict, bool, type(None)))
    
    # If we already showed members for this type (or if it's a simple type), skip
    if not (isClass or isInstance) or typeId in displayedTypes:
        return []
        
    matchingMembers = []
    try:
        allMembers = inspect.getmembers(obj)
        for mName, mObj in sorted(allMembers):
            if mName.startswith("_"):
                continue
            mType, mHeader, mDoc, _ = getObjectInfo(mName, mObj)
            
            # Check if member matches filter
            if not filterText or filterText in mName.lower() or filterText in mType.lower():
                matchingMembers.append((mHeader, mDoc))
    except Exception:
        pass
        
    return matchingMembers

class ApiBrowserView(QTextBrowser):
    """Custom QTextBrowser that handles font scaling with Ctrl + Mouse Wheel."""
    
    def wheelEvent(self, event: QWheelEvent):
        if event.modifiers() == Qt.ControlModifier:
            if event.angleDelta().y() > 0:
                self.zoomIn(1)
            else:
                self.zoomOut(1)
            event.accept()
        else:
            super().wheelEvent(event)

class ApiBrowserWidget(QWidget):
    """Embeddable API browser using QTextBrowser for interactive documentation."""
    
    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        
        self.filterEdit = QLineEdit()
        self.filterEdit.setPlaceholderText("Filter API...")
        self.filterEdit.setClearButtonEnabled(True)
        self.filterEdit.textChanged.connect(self.refreshContent)
        layout.addWidget(self.filterEdit)
        
        self.browser = ApiBrowserView()
        self.browser.setOpenExternalLinks(False)
        self.browser.setReadOnly(True)
        self.browser.setWordWrapMode(QTextOption.NoWrap)
        self.browser.setUndoRedoEnabled(False)
        layout.addWidget(self.browser)
        
        # Initial refresh
        self.refreshContent()

    def refreshContent(self):
        """Rebuild the API documentation view based on the current filter."""
        api = APIRegistry.api()
        filterText = self.filterEdit.text().strip().lower()
        
        html = [
            "<style>",
            "body { font-family: 'Segoe UI', sans-serif; color: #abb2bf; background-color: #21252b; line-height: 1.3; font-size: 1.0em; }",
            ".entry { margin-bottom: 0.6em; padding: 0.4em 0.8em; background-color: #282c34; border-left: 2px solid #4e5666; }",
            ".member-entry { margin-bottom: 0.2em; padding: 0.2em 0.8em; margin-left: 1.5em; border-left: 1px solid #3e4451; background-color: transparent; }",
            ".header { color: #98c379; font-family: 'Consolas', monospace; font-size: 1em; }",
            ".keyword { color: #c678dd; font-weight: bold; }",
            ".name { font-weight: bold; color: #d19a66; font-size: 1.1em; font-family: 'Consolas', monospace; }",
            ".doc-string { color: #848da1; margin-top: 0.1em; font-size: 0.9em; padding-left: 1em; font-style: italic; }",
            ".no-results { color: #5c6370; text-align: center; margin-top: 3em; font-style: italic; }",
            "</style>",
            "<body>",
            "<h3>API Registry</h3>"
        ]
        
        foundAny = False
        displayedTypes = set()
        
        for name in sorted(api.keys()):
            obj = api[name]
            typeName, header, doc, _ = getObjectInfo(name, obj)
            
            # Collect members that match the filter
            matchingMembers = getMatchingMembers(obj, filterText, displayedTypes)

            # Final filter check: does the parent match OR do we have matching members?
            parentMatches = not filterText or filterText in name.lower() or filterText in typeName.lower()
            
            if not parentMatches and not matchingMembers:
                continue
                
            foundAny = True
            
            # Dedup: only show members for the first instance of a type in the search results
            objType = obj if inspect.isclass(obj) else type(obj)
            displayedTypes.add(id(objType))

            html.append("<div class='entry'>")
            html.append(f"<div class='header'>{header}</div>")
            if doc:
                html.append(f"<div class='doc-string'>{doc}</div>")
                
            for mHeader, mDoc in matchingMembers:
                html.append("<div class='member-entry'>")
                html.append(f"<div class='header'>{mHeader}</div>")
                if mDoc:
                    html.append(f"<div class='doc-string'>{mDoc}</div>")
                html.append("</div>")
                    
            html.append("</div>")
            
        if not foundAny:
            html.append("<div class='no-results'>No API matches found.</div>")
            
        html.append("</body>")
        self.browser.setHtml("".join(html))
