import time
import json
import re
import os
import subprocess
import inspect
import sys
import shutil
import logging
import fnmatch
from functools import partial
from typing import Callable, Optional, List, Dict, Union

from ..qt import *

from .. import __version__
from ..core import *
from .editor import *
from . import moduleHistoryBrowser
from .moduleHistoryBrowser import ModuleHistoryWidget
from ..workspace import saveWorkspace, loadWorkspace
from ..widgets.ui import TemplateWidgets, EditJsonDialog, EditTextDialog
from ..utils import *
from .utils import *

parentWindow = APIRegistry.getParentWindow()
updateFilesThread = None
trackFileChangesThreads = {} # by file path

DOC_HELP_TEXT = """Documentation for this module (double-click to edit). Supports HTML or Markdown.

HTML examples:
- Paragraph: <p>Short description of what this module does.</p>
- Section title: <h2>Usage</h2>
- External link: <a href="https://your.wiki/rig">Rigging guide</a>
- Open another module: <a href="module:character/rig/Arm_L">Arm_L module</a>

Markdown examples:
- **Bold**, *italic*, `code`
- ## Heading, - list, [link](url)
- Fenced code blocks, tables

module:SPEC links work in both formats; SPEC is a UID, relative path, or full path for Module.loadModule()."""

def convertMarkdownToHTML(text: str) -> str:
    """Convert Markdown to HTML."""
    try:
        import markdown
        return markdown.markdown(text, extensions=['fenced_code', 'codehilite', 'tables', 'extra', 'sane_lists'], output_format="html5")
    except ImportError:
        if text:
            text = "<b>Markdown is not installed. Using simple HTML conversion.</b><br><br>" + text
            text = convertTextToHTML(text)
    return text

def convertTextToHTML(text: str) -> str:
    """Convert text to HTML."""
    return text.replace("\n", "<br>").replace("\t", "&nbsp;"*4)

class DocBrowser(QTextBrowser):
    """HTML/Markdown browser for module documentation."""

    def __init__(self, *, mainWindow: 'RigBuilderWindow', parent=None):
        super().__init__(parent)
        self.mainWindow = mainWindow

        self.setOpenLinks(False)
        self.anchorClicked.connect(self._onAnchorClicked)
        self.setPlaceholderText(DOC_HELP_TEXT)
        self.document().setDefaultStyleSheet("a { color: #55aaee; }")

    def updateDoc(self):
        item = self.mainWindow.currentModule()
        if not item:
            self.clear()
            return

        if item.module.docFormat() == "markdown":
            html = convertMarkdownToHTML(item.module.doc())
        else:
            html = convertTextToHTML(item.module.doc())

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
                self.openModuleBySpec(spec)
            return

    def openModuleBySpec(self, spec: str):
        """Load and select module by spec (UID, relative or full path)."""
        try:
            module = Module.loadModule(spec)
        except ModuleNotFoundError:
            self.mainWindow.logger.warning("Module not found: {}".format(spec))
            return

        item = self.mainWindow.treeWidget.addModule(module)
        self.mainWindow.selectModule(item)

    def contextMenuEvent(self, event):
        item = self.mainWindow.currentModule()
        if not item:
            return

        def setDocFormat(format: str):
            item.module.setDocFormat(format)
            self.updateDoc()

        module = item.module
        menu = QMenu(self)
        action = menu.addAction("Show as HTML", partial(setDocFormat, "html"))
        action.setCheckable(True)
        action.setChecked(module.docFormat() == "html")

        action = menu.addAction("Show as Markdown", partial(setDocFormat, "markdown"))
        action.setCheckable(True)
        action.setChecked(module.docFormat() == "markdown")

        menu.popup(event.globalPos())

    def mouseDoubleClickEvent(self, event):
        """Edit source text and save it to module."""

        item = self.mainWindow.currentModule()
        if not item:
            return

        module = item.module

        def save(text):
            module.setDoc(text)
            self.updateDoc()

        w = EditTextDialog(
            module.doc(),
            title="Edit documentation",
            placeholder=DOC_HELP_TEXT,
            words=set(),
            python=False)

        w.saved.connect(save)
        w.show()

# === GLOBAL LOGGING SYSTEM ===
class RigBuilderLogHandler(logging.Handler):
    """Custom log handler that redirects to logWidget."""
    def __init__(self):
        super().__init__()
        self.logWidget = None
        
    def setLogWidget(self, logWidget: "LogWidget"):
        """Connect handler to specific logWidget."""
        self.logWidget = logWidget
        
    def emit(self, record: logging.LogRecord):
        if self.logWidget:
            msg = self.format(record)
            self.logWidget.write(msg + '\n')

def sendToServer(module: 'Module') -> bool:
    '''
    Send module to server with SVN, Git, Perforce or other VCS.
    '''
    module.sendToServer() # copy file to server and add to VCS
    return True

class TrackFileChangesThread(QThread):
    somethingChanged = Signal()

    def __init__(self, filePath: str):
        super().__init__()
        self.filePath = filePath

    def run(self):
        lastModified = os.path.getmtime(self.filePath)
        while True:
            currentModified = os.path.getmtime(self.filePath)
            if currentModified != lastModified:
                self.somethingChanged.emit()
                lastModified = currentModified
            time.sleep(1)

class DirectoryWatcher(QObject):
    """Watch directories recursively and emit debounced change events."""
    somethingChanged = Signal()

    def __init__(self, roots: List[str], *, debounceMs: int = 700, filePatterns: Optional[List[str]] = None, recursive: bool = True, parent: Optional[QObject] = None):
        super().__init__(parent=parent)
        self.roots = [os.path.normpath(p) for p in roots if os.path.exists(p)]
        self.debounceMs = debounceMs
        self.filePatterns = [p.lower() for p in (filePatterns or [])]
        self.recursive = recursive
        self.watcher = QFileSystemWatcher(self)
        self.debounceTimer = QTimer(self)
        self.debounceTimer.setSingleShot(True)

        self.watcher.directoryChanged.connect(self._onFilesystemChanged)
        self.watcher.fileChanged.connect(self._onFilesystemChanged)
        self.debounceTimer.timeout.connect(self._onDebounceTimeout)

        self.refreshWatchedPaths()

    def refreshWatchedPaths(self):
        paths = set()
        for root in self.roots:
            walkIterator = os.walk(root)
            for dirPath, _, fileNames in walkIterator:
                paths.add(os.path.normpath(dirPath))
                for fileName in fileNames:
                    fileNameLower = fileName.lower()
                    if not self.filePatterns or any(fnmatch.fnmatch(fileNameLower, p) for p in self.filePatterns):
                        paths.add(os.path.normpath(os.path.join(dirPath, fileName)))
                if not self.recursive:
                    break

        if not paths:
            return

        oldPaths = set(self.watcher.files() + self.watcher.directories())
        toRemove = list(oldPaths - paths)
        toAdd = list(paths - oldPaths)
        if toRemove:
            self.watcher.removePaths(toRemove)
        if toAdd:
            self.watcher.addPaths(toAdd)

    def _onFilesystemChanged(self, _path: str):
        self.debounceTimer.start(self.debounceMs)

    def _onDebounceTimeout(self):
        # File watchers can drop updated paths on some platforms, so refresh first.
        self.refreshWatchedPaths()
        self.somethingChanged.emit()

def updateFilesFromServer():
    def update():
        '''
        Update files from server with SVN, Git, Perforce or other VCS.
        '''
        pass

    global updateFilesThread
    if not updateFilesThread or not updateFilesThread.isRunning():
        updateFilesThread = MyThread(update)
        updateFilesThread.start()

class MyThread(QThread):
    def __init__(self, runFunction: Callable[[], None]):
        super().__init__()
        self.runFunction = runFunction

    def run(self):
        self.runFunction()

class AttributesWidget(QWidget):
    def __init__(self, moduleItem: 'ModuleItem', attributes: List['Attribute'], *, mainWindow: 'RigBuilderWindow', **kwargs):
        super().__init__(**kwargs)

        self.mainWindow = mainWindow
        self.moduleItem = moduleItem

        self._attributeAndWidgets = [] # [attribute, nameWidget, templateWidget]

        layout = QGridLayout()
        layout.setDefaultPositioning(2, Qt.Horizontal)
        layout.setColumnStretch(1, 1)
        self.setLayout(layout)

        def executor(cmd: str, context: Optional[Dict[str, object]] = None) -> Dict[str, object]:
            ctx: Dict[str, object] = {}
            ctx.update(self.moduleItem.module.context())
            if context:
                ctx.update(context)

            with captureOutput(self.mainWindow.logWidget):
                try:
                    exec(replaceAttrPrefix(cmd), ctx)
                except Exception as e:
                    self.mainWindow.logger.error(str(e))
                    self.mainWindow.showLog()
                else:
                    self.updateWidgets()
                    self.updateWidgetStyles()

            return ctx

        for idx, a in enumerate(attributes):
            templateWidget = TemplateWidgets[a.template()](executor=executor)
            nameWidget = QLabel(a.name())

            self._attributeAndWidgets.append((a, nameWidget, templateWidget))
            
            self.updateWidget(idx)
            self.updateWidgetStyle(idx)

            templateWidget.somethingChanged.connect(partial(self._onWidgetChange, idx))

            nameWidget.setAlignment(Qt.AlignRight)
            nameWidget.setCursor(Qt.PointingHandCursor)
            nameWidget.contextMenuEvent = partial(self.nameContextMenuEvent, attrWidgetIndex=idx)

            layout.addWidget(nameWidget)
            layout.addWidget(templateWidget)

        layout.addWidget(QLabel())
        layout.setRowStretch(layout.rowCount(), 1)

    def connectionMenu(self, menu: QMenu, module: 'Module', attrWidgetIndex: int, path: str = "/"):
        attr, _, _ = self._attributeAndWidgets[attrWidgetIndex]

        subMenu = QMenu(module.name(), self)

        for a in module.attributes():
            if a.template() == attr.template() and a.name(): # skip empty names as well
                subMenu.addAction(a.name(), partial(self.connectAttr, path+module.name()+"/"+a.name(), attrWidgetIndex))

        for ch in module.children():
            self.connectionMenu(subMenu, ch, attrWidgetIndex, path+module.name()+"/")

        if subMenu.actions():
            menu.addMenu(subMenu)

    def nameContextMenuEvent(self, event: QContextMenuEvent, attrWidgetIndex: int):
        attr, _, _ = self._attributeAndWidgets[attrWidgetIndex]

        menu = QMenu(self)
        titleAction = menu.addAction(attr.name())
        titleAction.setEnabled(False)
        font = titleAction.font()
        font.setBold(True)
        titleAction.setFont(font)
        menu.addSeparator()

        if self.moduleItem and self.moduleItem.parent():
            makeConnectionMenu = menu.addMenu("Make connection")

            for a in self.moduleItem.module.parent().attributes():
                if a.template() == attr.template() and a.name(): # skip empty names as well
                    makeConnectionMenu.addAction(a.name(), partial(self.connectAttr, "/"+a.name(), attrWidgetIndex))

            for ch in self.moduleItem.module.parent().children():
                if ch is not self.moduleItem.module:
                    self.connectionMenu(makeConnectionMenu, ch, attrWidgetIndex)

        if attr.connect():
            menu.addAction("Break connection", partial(self.disconnectAttr, attrWidgetIndex))

        menu.addSeparator()

        menu.addAction("Edit data", partial(self.editData, attrWidgetIndex))
        menu.addSeparator()
        menu.addAction("Edit expression", partial(self.editExpression, attrWidgetIndex))

        if attr.expression():
            menu.addAction("Evaluate expression", partial(self.updateWidget, attrWidgetIndex))
            menu.addAction("Clear expression", partial(self.clearExpression, attrWidgetIndex))

        menu.addSeparator()
        menu.addAction("Expose", partial(self.exposeAttr, attrWidgetIndex))
        menu.addSeparator()
        menu.addAction("Reset", partial(self.resetAttr, attrWidgetIndex))

        menu.popup(event.globalPos())

    def _wrapper(f: Callable[..., object]):
        def inner(self, attrWidgetIndex: int, *args, **kwargs):
            attr, _, widget = self._attributeAndWidgets[attrWidgetIndex]
            with captureOutput(self.mainWindow.logWidget):
                try:
                    return f(self, attrWidgetIndex, *args, **kwargs)
                
                except Exception as e:
                    self.mainWindow.logger.error(f"{self.moduleItem.module.name()}.{attr.name()}: {str(e)}")

                    if type(e) == AttributeResolverError:
                        with blockedWidgetContext(widget) as w:
                            w.setJsonData(attr.localData())

                    self.mainWindow.showLog()

        return inner
    
    @_wrapper
    def _onWidgetChange(self, attrWidgetIndex: int):
        attr, _, widget = self._attributeAndWidgets[attrWidgetIndex]

        widgetData = widget.getJsonData()
        attr.setData(widgetData) # implicitly push

        previousData = {id(a):a.localData() for a in self.moduleItem.module.attributes()}
        modifiedAttrs = []
        for otherAttr in self.moduleItem.module.attributes():
            otherAttr.pull()
            if otherAttr.localData() != previousData[id(otherAttr)]:
                modifiedAttrs.append(otherAttr)

        for idx, (otherAttr, _, otherWidget) in enumerate(self._attributeAndWidgets): # update attributes' widgets
            if otherAttr in modifiedAttrs:
                with blockedWidgetContext(otherWidget) as w:
                    w.setJsonData(otherAttr.localData())
                self.updateWidgetStyle(idx)

        if id(attr) not in modifiedAttrs: # update the modification style anyway
            self.updateWidgetStyle(attrWidgetIndex)       

    @_wrapper
    def updateWidget(self, attrWidgetIndex: int):
        attr, _, widget = self._attributeAndWidgets[attrWidgetIndex]
        with blockedWidgetContext(widget) as w:
            w.setJsonData(attr.data()) # pull data

    def updateWidgets(self):
        for i in range(len(self._attributeAndWidgets)):
            self.updateWidget(i)

    def updateWidgetStyle(self, attrWidgetIndex: int):
        attr, nameWidget, widget = self._attributeAndWidgets[attrWidgetIndex]

        style = ""
        tooltip = []
        if attr.connect():
            tooltip.append("Connect: "+attr.connect())
        if attr.expression():
            tooltip.append("Expression:\n" + attr.expression())

        if attr.connect() and not attr.expression(): # only connection (yellow)
            style = "TemplateWidget { border: 4px solid rgba(110, 110, 57, 0.45); background-color: rgba(110, 110, 57, 0.25) }"
        
        elif attr.expression() and not attr.connect(): # only expression (magenta)
            style = "TemplateWidget { border: 4px solid rgba(99, 32, 148, 0.45); background-color: rgba(99, 32, 148, 0.25) }"
        
        elif attr.expression() and attr.connect(): # both
            style = "TemplateWidget { border: 4px solid rgba(0,0,0,0); background: qlineargradient(x1: 0, y1: 0, x2: 1, y2: 0, stop: 0 rgba(110, 110, 57, 0.25), stop: 1 rgba(99, 32, 148, 0.25)); }"

        nameWidget.setText(attr.name()+("*" if attr.modified() else ""))

        widget.setStyleSheet(style)
        widget.setToolTip("\n".join(tooltip))

    def updateWidgetStyles(self):
        for i in range(len(self._attributeAndWidgets)):
            self.updateWidgetStyle(i)

    def exposeAttr(self, attrWidgetIndex: int):
        attr, _, _ = self._attributeAndWidgets[attrWidgetIndex]

        if not self.moduleItem.module.parent():
            QMessageBox.warning(self, "Rig Builder", "Can't expose attribute to parent: no parent module")
            return

        if self.moduleItem.module.parent().findAttribute(attr.name()):
            QMessageBox.warning(self, "Rig Builder", "Can't expose attribute to parent: attribute already exists")
            return

        doUsePrefix = QMessageBox.question(self, "Rig Builder", "Use prefix for the exposed attribute name?", QMessageBox.Yes and QMessageBox.No, QMessageBox.Yes) == QMessageBox.Yes
        prefix = self.moduleItem.module.name() + "_" if doUsePrefix else ""
        expAttr = attr.copy()
        expAttr.setName(prefix + expAttr.name())
        self.moduleItem.module.parent().addAttribute(expAttr)
        self.connectAttr("/"+expAttr.name(), attrWidgetIndex)

    @_wrapper
    def editData(self, attrWidgetIndex: int):
        def save(data):
            @AttributesWidget._wrapper
            def _save(_, attrWidgetIndex: int):
                attr.setData(data[0]) # use [0] because data is a list
                self.updateWidget(attrWidgetIndex)
                self.updateWidgetStyle(attrWidgetIndex)
            _save(self, attrWidgetIndex)

        attr, _, _ = self._attributeAndWidgets[attrWidgetIndex]
        w = EditJsonDialog(attr.localData(), title="Edit data")
        w.saved.connect(save)
        w.show()

    def editExpression(self, attrWidgetIndex: int):
        def save(text: str):
            attr.setExpression(text)
            self.updateWidgets()
            self.updateWidgetStyle(attrWidgetIndex)

        attr, _, _ = self._attributeAndWidgets[attrWidgetIndex]

        words = set(self.moduleItem.module.context().keys())
        placeholder = '# Example: value = ch("../someAttr") + 1 or data["items"] = [1,2,3]'
        w = EditTextDialog(attr.expression(), title="Edit expression for '{}'".format(attr.name()), placeholder=placeholder, words=words, python=True)
        w.saved.connect(save)
        w.show()

    def clearExpression(self, attrWidgetIndex: int):
        attr, _, _ = self._attributeAndWidgets[attrWidgetIndex]
        attr.setExpression("")
        self.updateWidgetStyle(attrWidgetIndex)

    def resetAttr(self, attrWidgetIndex: int):
        attr, _, _ = self._attributeAndWidgets[attrWidgetIndex]

        tmp = TemplateWidgets[attr.template()]()
        attr.setConnect("")
        attr.setData(tmp.getDefaultData())
        self.updateWidget(attrWidgetIndex)
        self.updateWidgetStyle(attrWidgetIndex)

    def disconnectAttr(self, attrWidgetIndex: int):
        attr, _, _ = self._attributeAndWidgets[attrWidgetIndex]
        attr.setConnect("")
        self.updateWidgetStyle(attrWidgetIndex)

    def connectAttr(self, connect: str, attrWidgetIndex: int):
        attr, _, _ = self._attributeAndWidgets[attrWidgetIndex]
        attr.setConnect(connect)
        self.updateWidget(attrWidgetIndex)
        self.updateWidgetStyle(attrWidgetIndex)

class AttributesTabWidget(QTabWidget):
    def __init__(self, moduleItem: 'ModuleItem', *, mainWindow: 'RigBuilderWindow', **kwargs):
        super().__init__(**kwargs)

        self.mainWindow = mainWindow
        self.moduleItem = moduleItem
        self.tabsAttributes = {}
        self._attributesWidget = None

        self.searchAndReplaceDialog = SearchReplaceDialog(["In all tabs"], parent=mainWindow)
        self.searchAndReplaceDialog.onReplace.connect(self._onReplace)

        self.currentChanged.connect(self._onTabChanged)

    def contextMenuEvent(self, event: QContextMenuEvent):
        menu = QMenu(self)

        if self.moduleItem:
            menu.addAction("Edit attributes", self.editAttributes)
            menu.addSeparator()
            menu.addAction("Replace in values", self.searchAndReplaceDialog.exec_)

        menu.popup(event.globalPos())

    def editAttributes(self):
        dialog = EditAttributesDialog(self.moduleItem, self.currentIndex(), parent=mainWindow)
        dialog.exec()

        self.mainWindow.codeEditorWidget.updateState()
        self.updateTabs()

    def _onReplace(self, old: str, new: str, opts: Dict[str, bool]):
        def replaceStringInData(data: object, old: str, new: str) -> object:
            try:
                return json.loads(json.dumps(data).replace(old,new))
            except ValueError:
                return data

        if opts.get("In all tabs"):
            attributes = []
            for attrs in self.tabsAttributes.values(): # merge all attributes
                attributes.extend(attrs)
        else:
            attributes = self.tabsAttributes[self.tabText(self.currentIndex())]

        for attr in attributes:
            v = replaceStringInData(attr.get(), old, new)
            attr.set(v)

        self.updateTabs()

    def _onTabChanged(self, idx: int):
        self.selectTab(idx)

    def selectTab(self, idx: int):
        """Switch to tab at index and build attributes widget."""

        if self.count() == 0:
            return

        idx = clamp(idx, 0, self.count()-1)

        title = self.tabText(idx)
        if title not in self.tabsAttributes:
            self._attributesWidget = None
            return

        scrollArea = self.widget(idx)
        self._attributesWidget = AttributesWidget(self.moduleItem, self.tabsAttributes[title], mainWindow=self.mainWindow)
        scrollArea.setWidget(self._attributesWidget)
        self.setCurrentIndex(idx)

    def updateTabs(self):
        oldIndex = self.currentIndex()
        oldCount = self.count()

        self._attributesWidget = None
        self.tabsAttributes.clear()

        if not self.moduleItem:
            return

        self.blockSignals(True)

        tabTitlesInOrder = []
        for a in self.moduleItem.module.attributes():
            if a.category() not in self.tabsAttributes:
                self.tabsAttributes[a.category()] = []
                tabTitlesInOrder.append(a.category())

            self.tabsAttributes[a.category()].append(a)

        if not tabTitlesInOrder: # no attributes, show placeholder
            label = QLabel("No attributes, right-click to add them.")
            label.setAlignment(Qt.AlignCenter)
            label.setStyleSheet("color: gray;")
            scrollArea = QScrollArea()
            scrollArea.setWidgetResizable(True)
            scrollArea.setWidget(label)
            self.addTab(scrollArea, "")

        for t in tabTitlesInOrder:
            scrollArea = QScrollArea() # empty, in tabChanged actual widget is set
            scrollArea.setWidgetResizable(True)
            self.addTab(scrollArea, t) # add new tabs in front of the old ones

        # remove previous tabs
        for _ in range(oldCount):
            w = self.widget(0)
            if w:
                w.deleteLater()
            self.removeTab(0)

        if self.count() == 1:
            self.tabBar().hide()
        else:
            self.tabBar().show()

        self.selectTab(oldIndex)
        self.blockSignals(False)

    def updateWidgetStyles(self):
        if self._attributesWidget:
            self._attributesWidget.updateWidgetStyles()

class ModuleBrowserTreeWidget(QTreeWidget):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.middlePressPos = QPoint()

        self.setHeaderLabels(["Module", "Modification time"])
        self.header().setSectionResizeMode(QHeaderView.ResizeToContents)
        self.setSortingEnabled(True)
        self.sortItems(1, Qt.DescendingOrder)

        self.setDragEnabled(True)
        self.setAcceptDrops(False)
        self.setDropIndicatorShown(False)
        self.setDragDropMode(QAbstractItemView.DragOnly)
        self.setDefaultDropAction(Qt.CopyAction)
        self.setMinimumHeight(100)

    def _collectDraggedModulePaths(self) -> list[str]:
        modulePaths = []
        for item in self.selectedItems():
            filePath = getattr(item, "filePath", "")
            if filePath:
                modulePaths.append(filePath)
        return modulePaths

    def _startModuleDrag(self):
        modulePaths = self._collectDraggedModulePaths()
        if not modulePaths:
            return

        mimeData = QMimeData()
        mimeData.setUrls([QUrl.fromLocalFile(path) for path in modulePaths])

        drag = QDrag(self)
        drag.setMimeData(mimeData)
        execFunc(drag, Qt.CopyAction)

    def startDrag(self, supportedActions: Qt.DropActions):
        del supportedActions
        self._startModuleDrag()

    def mousePressEvent(self, event: QMouseEvent):
        if event.button() == Qt.MiddleButton:
            self.middlePressPos = event.pos()
            item = self.itemAt(event.pos())
            if item:
                if not (event.modifiers() & (Qt.ControlModifier | Qt.ShiftModifier)):
                    self.clearSelection()
                item.setSelected(True)
                self.setCurrentItem(item)
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event: QMouseEvent):
        if event.buttons() & Qt.MiddleButton:
            if (event.pos() - self.middlePressPos).manhattanLength() >= QApplication.startDragDistance():
                self._startModuleDrag()
                self.middlePressPos = QPoint()
                event.accept()
                return
        super().mouseMoveEvent(event)

    def contextMenuEvent(self, event: QContextMenuEvent):
        menu = QMenu(self)
        menu.addAction("Locate", self.browseModuleDirectory)
        menu.addAction("Open server folder", self.openServerModulesFolder)
        menu.addAction("Open local folder", self.openLocalModulesFolder)
        menu.addSeparator()
        menu.addAction("Set server modules folder...", self.parent().browseServerModulesPath)
        menu.addAction("Clear server modules folder", self.parent().clearServerModulesPath)
        menu.addSeparator()
        menu.addAction("Refresh", self.parent().refreshModules)
        menu.popup(event.globalPos())

    def browseModuleDirectory(self):
        for item in self.selectedItems():
            if item.childCount() == 0:
                subprocess.call("explorer /select,\"{}\"".format(os.path.normpath(item.filePath)))

    def openServerModulesFolder(self):
        folderPath = getServerModulesPath()
        subprocess.call("explorer \"{}\"".format(folderPath))

    def openLocalModulesFolder(self):
        folderPath = getLocalModulesPath()
        subprocess.call("explorer \"{}\"".format(folderPath))

class ModuleSelectorWidget(QWidget):
    """Embeddable module selector with filter, source options, and module tree."""
    modulesReloaded = Signal()

    def __init__(self, **kwargs):
        super().__init__(**kwargs)

        layout = QVBoxLayout()
        layout.setContentsMargins(0, 0, 0, 0)
        self.setLayout(layout)

        self.updateSourceWidget = QComboBox()
        self.updateSourceWidget.addItems(["All", "Server", "Local", "None"])
        self.updateSourceWidget.setCurrentIndex({"all": 0, "server": 1, "local": 2, "": 3}[Module.UpdateSource])
        self.updateSourceWidget.currentIndexChanged.connect(lambda _=None: self.updateSource())

        self.modulesFromButtonGroup = QButtonGroup(self)
        self.modulesFromServerRadio = QRadioButton("Server")
        self.modulesFromLocalRadio = QRadioButton("Local")
        self.modulesFromButtonGroup.addButton(self.modulesFromServerRadio, 0)
        self.modulesFromButtonGroup.addButton(self.modulesFromLocalRadio, 1)
        self.modulesFromServerRadio.setChecked(True)
        self.modulesFromButtonGroup.buttonClicked.connect(self.applyMask)

        self.maskWidget = QLineEdit()
        self.maskWidget.setPlaceholderText("Filter modules...")
        self.maskWidget.textChanged.connect(self.applyMask)

        self.clearFilterButton = QPushButton("Clear")
        self.clearFilterButton.clicked.connect(self.maskWidget.clear)
        self.clearFilterButton.hide()
        self.maskWidget.textChanged.connect(self._onMaskTextChanged)

        filterLayout = QHBoxLayout()
        filterLayout.addWidget(QLabel("Filter"))
        filterLayout.addWidget(self.maskWidget)
        filterLayout.addWidget(self.clearFilterButton)
        layout.addLayout(filterLayout)

        self.treeWidget = ModuleBrowserTreeWidget()

        self.loadingLabel = QLabel("Pulling modules from server...")
        self.loadingLabel.hide()

        controlsLayout = QHBoxLayout()
        controlsLayout.addWidget(QLabel("Modules from"))
        controlsLayout.addWidget(self.modulesFromServerRadio)
        controlsLayout.addWidget(self.modulesFromLocalRadio)
        controlsLayout.addStretch()
        controlsLayout.addWidget(QLabel("Update source"))
        controlsLayout.addWidget(self.updateSourceWidget)

        layout.addWidget(self.treeWidget)
        layout.addWidget(self.loadingLabel)
        layout.addLayout(controlsLayout)

        self.refreshModules()

    def refreshModules(self):
        """Internal refresh used by startup and auto-reload flows."""
        self.loadingLabel.show()
        updateFilesFromServer()

        def onFinished():
            Module.updateUidsCache()
            self.loadingLabel.hide()
            self.applyMask()
            self.modulesReloaded.emit()

        global updateFilesThread
        if updateFilesThread and updateFilesThread.isRunning():
            updateFilesThread.finished.connect(onFinished)
        else:
            onFinished()

    def updateSource(self):
        updateSource = self.updateSourceWidget.currentIndex()
        UpdateSourceFromInt = {0: "all", 1: "server", 2: "local", 3: ""}
        Module.UpdateSource = UpdateSourceFromInt[updateSource]

    def browseServerModulesPath(self):
        current = getServerModulesPath()
        folder = QFileDialog.getExistingDirectory(self, "Server modules folder", current)
        if folder:
            Settings["serverModulesPath"] = folder
            Module.updateUidsCache()
            self.applyMask()

    def clearServerModulesPath(self):
        Settings["serverModulesPath"] = ""
        Module.updateUidsCache()
        self.applyMask()

    def getModulesRootDirectory(self) -> str:
        modulesFrom = self.modulesFromButtonGroup.checkedId()
        return getServerModulesPath() if modulesFrom == 0 else getLocalModulesPath()

    def _onMaskTextChanged(self, text: str):
        self.clearFilterButton.setVisible(bool(text))

    def applyMask(self, *_):
        """Rebuild module tree from mask and source settings. Accepts optional args from Qt signals."""
        def findChildByText(text: str, parent: QTreeWidgetItem, column: int = 0):
            for i in range(parent.childCount()):
                ch = parent.child(i)
                if text == ch.text(column):
                    return ch

        modulesFrom = self.modulesFromButtonGroup.checkedId()
        modulesDirectory = self.getModulesRootDirectory()
        modules = list(Module.ServerUids.values()) if modulesFrom == 0 else list(Module.LocalUids.values())
        modules = sorted(modules)

        self.treeWidget.clear()

        mask = self.maskWidget.text().split() # split by spaces, '/folder mask /other mask'

        # make tree dict from module files
        for f in modules:
            relativePath = os.path.relpath(f, modulesDirectory)
            relativeDir = os.path.dirname(relativePath)
            name, _ = os.path.splitext(os.path.basename(f))

            okMask = True
            dirMask = "/"+relativePath.replace("\\", "/")+"/"
            for m in mask:
                if not re.search(re.escape(m), dirMask, re.IGNORECASE):
                    okMask = False
                    break

            if not okMask:
                continue

            dirItem = self.treeWidget.invisibleRootItem()
            if relativeDir:
                for p in relativeDir.split("\\"):
                    ch = findChildByText(p, dirItem)
                    if ch:
                        dirItem = ch
                    else:
                        ch = QTreeWidgetItem([p, ""])
                        ch.setFlags((ch.flags() | Qt.ItemIsEnabled | Qt.ItemIsSelectable) & ~Qt.ItemIsDragEnabled)
                        font = ch.font(0)
                        font.setBold(True)
                        ch.setForeground(0, QColor(130, 130, 230))
                        ch.setFont(0, font)

                        dirItem.addChild(ch)
                        dirItem.setExpanded(True if mask else False)
                        dirItem = ch

            modtime = time.strftime("%Y/%m/%d %H:%M", time.localtime(os.path.getmtime(f)))
            item = QTreeWidgetItem([name, modtime])
            item.setFlags(item.flags() | Qt.ItemIsDragEnabled)
            item.filePath = f
            dirItem.addChild(item)
            dirItem.setExpanded(True if mask else False)


class ModuleItem(QTreeWidgetItem):
    def __init__(self, module: 'Module', **kwargs):
        super().__init__(**kwargs)
        self.module = module

        self.setFlags(Qt.ItemIsSelectable | Qt.ItemIsEnabled | Qt.ItemIsEditable | Qt.ItemIsDragEnabled | Qt.ItemIsDropEnabled)

    def clone(self) -> "ModuleItem":
        item = ModuleItem(self.module.copy())
        for i in range(self.childCount()):
            item.addChild(self.child(i).clone())
        return item

    def data(self, column: int, role: int):
        if column == 0: # name
            if role == Qt.EditRole:
                return self.module.name()

            elif role == Qt.DisplayRole:
                return self.module.name() + ("*" if self.module.modified() else " ")

            elif role == Qt.ForegroundRole:
                isParentMuted = False
                isParentReferenced = False

                parent = self.parent()
                while parent:
                    isParentMuted = isParentMuted or parent.module.muted()
                    isParentReferenced = isParentReferenced or parent.module.uid()
                    parent = parent.parent()

                color = QColor(200, 200, 200)

                if isParentReferenced:
                    color = QColor(140, 140, 180)

                if self.module.muted() or isParentMuted:
                    color = QColor(100, 100, 100)

                return color

            elif role == Qt.BackgroundRole:
                if not re.match("\\w*", self.module.name()):
                    return QColor(170, 50, 50)

                itemParent = self.parent()
                if itemParent and len([ch for ch in itemParent.module.children() if ch.name() == self.module.name()]) > 1:
                    return QColor(170, 50, 50)

                return super().data(column, role)

        elif column == 1: # path
            if role == Qt.DisplayRole:
                return self.module.relativePathString().replace("\\", "/") + " "

            elif role == Qt.EditRole:
                return "(not editable)"

            elif role == Qt.FontRole:
                font = QFont()
                font.setItalic(True)
                return font

            elif role == Qt.ForegroundRole:
                return QColor(125, 125, 125)

        elif column == 2: # source
            source = ""
            if self.module.loadedFromLocal():
                source = "local"
            elif self.module.loadedFromServer():
                source = "server"

            if role == Qt.DisplayRole:
                return source + " "

            elif role == Qt.EditRole:
                return "(not editable)"

            elif role == Qt.ForegroundRole:
                if source == "local":
                    return QColor(120, 220, 120)
                elif source == "server":
                    return QColor(120, 120, 120)

        elif column == 3: # uid
            if role == Qt.DisplayRole:
                return self.module.uid()[:8]
            elif role == Qt.EditRole:
                return "(not editable)"
            elif role == Qt.ForegroundRole:
                return QColor(125, 125, 170)
        else:
            return super().data(column, role)

    def setData(self, column: int, role: int, value: object):
        if column == 0:
            if role == Qt.EditRole:
                newName = replaceSpecialChars(value).strip()
                if self.parent():
                    existingNames = set([ch.name() for ch in self.parent().module.children() if ch is not self.module])
                    newName = findUniqueName(newName, existingNames)

                connections = self._saveConnections(self.module) # rename in connections
                self.module.setName(newName)
                self.treeWidget().resizeColumnToContents(column)
                self._updateConnections(connections)
        else:
            return super().setData(column, role, value)

    def _saveConnections(self, currentModule: "Module"):
        connections = []
        for a in currentModule.attributes():
            connections.append({"attr":a, "module": currentModule, "connections":a.listConnections()})

        for ch in currentModule.children():
            connections += self._saveConnections(ch)
        return connections

    def _updateConnections(self, connections: list[dict[str, object]]):
        for data in connections:
            srcAttr = data["attr"]
            module = data["module"]
            for a in data["connections"]:
                c = module.path().replace(a.module().path(inclusive=False), "") + "/" + srcAttr.name()
                a.setConnect(c) # update connection path
    
    # === UI API METHODS ===
    
    def getLogger(self):
        """Get logger from main window."""
        treeWidget = self.treeWidget()
        if treeWidget and treeWidget.mainWindow:
            return treeWidget.mainWindow.logger        
    
    def validateModule(self):
        """Validate this module and log any errors found. Returns True if valid."""
        hasErrors = False
        module = self.module
        
        # Check module name
        if not re.match(r"^\w+$", module.name()):
            self.getLogger().error(f"Module '{module.name()}': Invalid module name (only alphanumeric characters and underscore allowed)")
            hasErrors = True
        
        # Check for duplicate child names
        childNames = [ch.name() for ch in module.children()]
        duplicates = [name for name in childNames if childNames.count(name) > 1]
        if duplicates:
            self.getLogger().error(f"Module '{module.name()}': Duplicate child module names: {list(set(duplicates))}")
            hasErrors = True
        
        # Check attributes
        for attr in module.attributes():
            if not attr.template():
                self.getLogger().error(f"Module '{module.name()}': Attribute '{attr.name()}' has no template")
                hasErrors = True
            elif attr.template() not in TemplateWidgets:
                self.getLogger().error(f"Module '{module.name()}': Unknown template '{attr.template()}' for attribute '{attr.name()}'")
                hasErrors = True
            
            # Check attribute connections
            if attr.connect():
                try:
                    srcAttr = attr.findConnectionSource()
                    if not srcAttr:
                        self.getLogger().error(f"Module '{module.name()}': Attribute '{attr.name()}' has invalid connection '{attr.connect()}'")
                        hasErrors = True
                except Exception as e:
                    self.getLogger().error(f"Module '{module.name()}': Attribute '{attr.name()}' connection error: {str(e)}")
                    hasErrors = True
        
        return not hasErrors


class TreeWidget(QTreeWidget):
    def __init__(self, *, mainWindow: 'RigBuilderWindow', **kwargs):
        super().__init__(**kwargs)

        self.mainWindow = mainWindow
        self.dragItems = [] # using in drag & drop
        self.clipboard = []  # Module clipboard for copy/paste

        self.setHeaderLabels(["Name", "Path", "Source", "UID"])
        self.setSelectionMode(QAbstractItemView.ExtendedSelection) # ExtendedSelection

        self.header().setSectionResizeMode(QHeaderView.ResizeToContents)

        self.setDragEnabled(True)
        self.setDragDropMode(QAbstractItemView.InternalMove)
        self.setDropIndicatorShown(True)
        self.setAcceptDrops(True)

        self.setIndentation(16)

    def drawRow(self, painter: QPainter, option: QStyleOptionViewItem, index: QModelIndex):
        if self.selectionModel().isSelected(index):
            fullRowRect = QRect(0, option.rect.y(), self.viewport().width(), option.rect.height())
            painter.fillRect(fullRowRect, self.palette().highlight())
            option.palette.setBrush(QPalette.Highlight, QBrush(Qt.transparent, Qt.NoBrush))
        else:
            option.palette.setBrush(QPalette.Highlight, self.palette().highlight())
        super().drawRow(painter, option, index)

    def dragEnterEvent(self, event: QDragEnterEvent):
        super().dragEnterEvent(event)

        if event.mimeData().hasUrls():
            event.accept()            
        elif event.mouseButtons() == Qt.MiddleButton:
            self.dragItems = self.selectedItems()
        else:
            event.ignore()

    def dragMoveEvent(self, event: QDragMoveEvent):
        super().dragMoveEvent(event)

        if event.mimeData().hasUrls():
            event.setDropAction(Qt.CopyAction)

    def dropEvent(self, event: QDropEvent):
        super().dropEvent(event)

        if event.mimeData().hasUrls():
            event.setDropAction(Qt.CopyAction)
            for url in event.mimeData().urls():
                path = url.toLocalFile()

                with captureOutput(self.mainWindow.logWidget):
                    try:
                        m = Module.loadModule(path)
                        self.addTopLevelItem(self.makeItemFromModule(m))

                    except ET.ParseError as e:
                        self.mainWindow.logger.error(f"'{path}': {str(e)} - invalid module")
                        self.mainWindow.showLog()
        else:
            for item in self.dragItems:
                if item.module.parent(): # remove from old parent
                    item.module.parent().removeChild(item.module)

                newParent = item.parent()
                if newParent:
                    if newParent.module.findChild(item.module.name()):
                        existingNames = set([ch.name() for ch in newParent.module.children()])
                        item.module.setName(findUniqueName(item.module.name(), existingNames))

                    idx = newParent.indexOfChild(item)
                    newParent.module.insertChild(idx, item.module)
                    newParent.emitDataChanged()

            self.dragItems = []

    def makeItemFromModule(self, module: 'Module') -> ModuleItem:
        item = ModuleItem(module)

        for ch in module.children():
            item.addChild(self.makeItemFromModule(ch))

        return item

    def replaceModule(self, item: ModuleItem, newModule: 'Module') -> ModuleItem:
        """Replace a tree item with a new one built from newModule, preserving position and expanded state."""
        newItem = self.makeItemFromModule(newModule)
        expanded = item.isExpanded()

        if item.parent():
            parent = item.parent()
            idx = parent.indexOfChild(item)
            parent.removeChild(item)
            parent.insertChild(idx, newItem)

            parent.module.removeChild(item.module)
            parent.module.insertChild(idx, newItem.module)

        else:
            parent = self.invisibleRootItem()
            idx = parent.indexOfChild(item)
            parent.removeChild(item)
            parent.insertChild(idx, newItem)

        newItem.setExpanded(expanded)
        newItem.setSelected(True)
        return newItem

    def contextMenuEvent(self, event: QContextMenuEvent):
        self.mainWindow.menu().popup(event.globalPos())

    def sendModuleToServer(self):
        selectedItems = self.selectedItems()
        if not selectedItems:
            return

        msg = "\n".join([item.module.name() for item in selectedItems])

        if QMessageBox.question(self, "Rig Builder", "Send modules to server?\n"+msg, QMessageBox.Yes and QMessageBox.No, QMessageBox.Yes) != QMessageBox.Yes:
            return

        for item in selectedItems:
            if item.module.loadedFromLocal():
                if sendToServer(item.module):
                    QMessageBox.information(self, "Rig Builder", "Module '{}' has successfully been sent to server".format(item.module.name()))

            else:
                QMessageBox.warning(self, "Rig Builder", "Can't send '{}' to server.\nIt works for local modules only!".format(item.module.name()))

    def insertModule(self):
        m = Module()
        m.setName("module")
        item = self.makeItemFromModule(m)

        sel = self.selectedItems()
        if sel:
            sel[0].addChild(item)
            sel[0].module.addChild(item.module)
        else:
            self.addTopLevelItem(item)

    def importModule(self):
        sceneDir = getLocalModulesPath()
        currentFile = APIRegistry.currentSceneFile()
        if currentFile:
            sceneDir = os.path.dirname(currentFile)

        filePath, _ = QFileDialog.getOpenFileName(mainWindow, "Import", sceneDir, "*.xml")

        if not filePath:
            return

        Module.updateUidsCache()

        try:
            m = Module.loadModule(filePath)
            self.addTopLevelItem(self.makeItemFromModule(m))

        except ET.ParseError:
            self.mainWindow.logger.error(f"'{filePath}': invalid module")
            self.mainWindow.showLog()

    def importScript(self):
        """Import .py file as new module: create empty module named after file, set run code to script content."""
        sceneDir = getLocalModulesPath()
        currentFile = APIRegistry.currentSceneFile()
        if currentFile:
            sceneDir = os.path.dirname(currentFile)

        filePath, _ = QFileDialog.getOpenFileName(
            self.mainWindow, "Import script", sceneDir, "Python (*.py);;All files (*)"
        )
        if not filePath:
            return

        try:
            with open(filePath, "r", encoding="utf-8") as f:
                code = f.read()
        except OSError as e:
            self.mainWindow.logger.error(f"Cannot read '{filePath}': {e}")
            self.mainWindow.showLog()
            return

        name = os.path.splitext(os.path.basename(filePath))[0]
        m = Module()
        m.setName(name)
        m.setRunCode(code)
        item = self.makeItemFromModule(m)

        self.addTopLevelItem(item)
        self.mainWindow.selectModule(item)

    def saveModule(self):
        selectedItems = self.selectedItems()
        if not selectedItems:
            return

        msg = "\n".join(["{} -> {}".format(item.module.name(), item.module.getSavePath() or "N/A") for item in selectedItems])

        if QMessageBox.question(self, "Rig Builder", "Save modules?\n"+msg, QMessageBox.Yes and QMessageBox.No, QMessageBox.Yes) != QMessageBox.Yes:
            return

        shouldCommit, commitMessage = False, ""
        if self.mainWindow.moduleHistoryWidget.isHistoryTrackingEnabled():
            shouldCommit, commitMessage = self.mainWindow.moduleHistoryWidget.showCommitMessageDialog()

        for item in selectedItems:
            outputPath = item.module.getSavePath()

            if not outputPath:
                outputPath, _ = QFileDialog.getSaveFileName(mainWindow, "Save "+item.module.name(), os.path.join(getLocalModulesPath(), item.module.name()), "*.xml")

            if outputPath:
                dirname = os.path.dirname(outputPath)
                if not os.path.exists(dirname):
                    os.makedirs(dirname)

                try:
                    item.module.saveToFile(outputPath)
                except Exception as e:
                    QMessageBox.critical(self, "Rig Builder", "Can't save module '{}': {}".format(item.module.name(), str(e)))
                else:
                    if shouldCommit:
                        if not moduleHistoryBrowser.recordModuleSave(item.module, commitMessage):
                            QMessageBox.critical(self, "Rig Builder", "Can't save history for '{}': {}".format(item.module.name(), str(e)))

                    item.emitDataChanged() # path changed
                    self.mainWindow.attributesTabWidget.updateWidgetStyles()
        self.mainWindow.moduleHistoryWidget.updateModuleHistory()

    def saveAsModule(self):
        selectedItems = self.selectedItems()
        if not selectedItems:
            return

        shouldCommit, commitMessage = False, ""
        if self.mainWindow.moduleHistoryWidget.isHistoryTrackingEnabled():
            shouldCommit, commitMessage = self.mainWindow.moduleHistoryWidget.showCommitMessageDialog()

        for item in selectedItems:
            outputDir = os.path.dirname(item.module.filePath()) or getLocalModulesPath()
            outputPath, _ = QFileDialog.getSaveFileName(mainWindow, "Save as "+item.module.name(), outputDir + "/" +item.module.name(), "*.xml")

            if outputPath:
                try:
                    item.module.saveToFile(outputPath, newUid=True)
                except Exception as e:
                    QMessageBox.critical(self, "Rig Builder", "Can't save module '{}': {}".format(item.module.name(), str(e)))
                else:
                    if shouldCommit:
                        moduleHistoryBrowser.recordModuleSave(item.module, commitMessage)
                        
                    item.emitDataChanged() # path and uid changed
                    self.mainWindow.attributesTabWidget.updateWidgetStyles()

        self.mainWindow.moduleHistoryWidget.updateModuleHistory()

    def embedModule(self):
        selectedItems = self.selectedItems()
        if not selectedItems:
            return

        msg = "\n".join([item.module.name() for item in selectedItems])

        if QMessageBox.question(self, "Rig Builder", "Embed modules?\n"+msg, QMessageBox.Yes and QMessageBox.No, QMessageBox.Yes) != QMessageBox.Yes:
            return

        for item in selectedItems:
            item.module.embed()
            item.emitDataChanged() # path and uid changed

    def updateModule(self):
        selectedItems = self.selectedItems()
        if not selectedItems:
            return

        Module.updateUidsCache()

        msg = "\n".join([item.module.name() for item in selectedItems])
        if QMessageBox.question(self, "Rig Builder", "Update modules?\n"+msg, QMessageBox.Yes and QMessageBox.No, QMessageBox.Yes) != QMessageBox.Yes:
            return

        for item in selectedItems:
            if not item.module.uid():
                QMessageBox.warning(self, "Rig Builder", "Can't update module '{}': no uid".format(item.module.name()))
                continue

            item.module.update()

            self.replaceModule(item, item.module)

    def muteModule(self):
        for item in self.selectedItems():
            if item.module.muted():
                item.module.unmute()
            else:
                item.module.mute()
            item.emitDataChanged()

    def duplicateModule(self):
        newItems = []
        for item in self.selectedItems():
            newItem = self.makeItemFromModule(item.module.copy())
            if item.parent():
                existingNames = set([ch.name() for ch in item.parent().module.children()])
                newItem.module.setName(findUniqueName(item.module.name(), existingNames))

            parent = item.parent()
            if parent:
                parent.addChild(newItem)
                parent.module.addChild(newItem.module)
            else:
                self.addTopLevelItem(newItem)

            newItems.append(newItem)

        self.clearSelection()
        for item in newItems:
            item.setSelected(True)

    def copyModules(self):
        """Copy selected modules to clipboard."""
        selectedItems = self.selectedItems()
        if not selectedItems:
            return
            
        self.clipboard = []
        for item in selectedItems:
            self.clipboard.append(item.module.copy())
        
        self.mainWindow.logger.info(f"Copied {len(self.clipboard)} module(s)")

    def cutModules(self):
        """Cut selected modules to clipboard."""
        selectedItems = self.selectedItems()
        if not selectedItems:
            return
            
        self.clipboard = []
        for item in selectedItems:
            self.clipboard.append(item.module.copy())
        
        self.mainWindow.logger.info(f"Cut {len(self.clipboard)} module(s)")
        
        # Remove the cut modules without confirmation
        self.removeModule(askConfirmation=False)

    def pasteModules(self):
        """Paste modules from clipboard."""
        if not self.clipboard:
            return

        parent = self.mainWindow.currentModule()

        pastedItems = []
        for module in self.clipboard:
            newModule = module.copy()  # Make another copy to avoid reference issues
            
            # Ensure unique names
            if parent:
                existingNames = set([ch.name() for ch in parent.module.children()])
                newModule.setName(findUniqueName(newModule.name(), existingNames))
            
            newItem = self.makeItemFromModule(newModule)
            
            if parent:
                parent.addChild(newItem)
                parent.module.addChild(newModule)
            else:
                self.addTopLevelItem(newItem)
            
            pastedItems.append(newItem)
        
        # Select pasted items
        self.clearSelection()
        for item in pastedItems:
            item.setSelected(True)
            
        self.mainWindow.logger.info(f"Pasted {len(pastedItems)} module(s)")

    def removeModule(self, *, askConfirmation: bool = True):
        selectedItems = self.selectedItems()
        if not selectedItems:
            return

        if askConfirmation:
            msg = "\n".join([item.module.name() for item in selectedItems])
            if QMessageBox.question(self, "Rig Builder", "Remove modules?\n"+msg, QMessageBox.Yes and QMessageBox.No, QMessageBox.Yes) != QMessageBox.Yes:
                return

        for item in selectedItems:
            parent = item.parent()
            if parent:
                parent.removeChild(item)
                parent.module.removeChild(item.module)
                parent.emitDataChanged()
            else:
                self.invisibleRootItem().removeChild(item)

    def addModule(self, module: "Module") -> "ModuleItem":
        item = self.makeItemFromModule(module)
        self.addTopLevelItem(item)
        return item

class TemplateSelectorDialog(QDialog):
    selectedTemplate = Signal(str)

    def __init__(self, **kwargs):
        super().__init__(**kwargs)

        self.setWindowTitle("Template Selector")
        self.setGeometry(0, 0, 700, 500)

        layout = QVBoxLayout()
        self.setLayout(layout)

        scrollWidget = QWidget()
        scrollArea = QScrollArea()
        scrollArea.setWidget(scrollWidget)
        scrollArea.setWidgetResizable(True)

        self.gridLayout = QGridLayout()
        scrollWidget.setLayout(self.gridLayout)

        self.gridLayout.setDefaultPositioning(3, Qt.Horizontal)
        self.gridLayout.setColumnStretch(1, 1)

        layout.addWidget(scrollArea)

        self.refreshTemplates()
        centerWindow(self)

    def selectTemplate(self, t: str):
        self.selectedTemplate.emit(t)
        self.done(0)

    def refreshTemplates(self):
        """Rebuild template grid."""
        clearLayout(self.gridLayout)

        for t in sorted(TemplateWidgets.keys()):
            self.gridLayout.addWidget(QLabel(t))
            w  = TemplateWidgets[t]()
            w.setJsonData(w.getDefaultData())
            self.gridLayout.addWidget(w)

            selectBtn = QPushButton("Select")
            selectBtn.clicked.connect(partial(self.selectTemplate, t))
            self.gridLayout.addWidget(selectBtn)

class EditTemplateWidget(QWidget):
    Clipboard = []
    nameChanged = Signal(str, str)

    def __init__(self, name: str, template: str, **kwargs):
        super().__init__(**kwargs)

        self.template = template
        self.attrConnect = ""
        self.attrExpression = ""
        self.attrModified = False

        layout = QHBoxLayout()
        layout.setContentsMargins(0,0,0,0)
        self.setLayout(layout)

        self.nameWidget = QLabel(name)
        self.nameWidget.setAlignment(Qt.AlignRight)
        self.nameWidget.setFixedWidth(self.fontMetrics().averageCharWidth()*20)
        self.nameWidget.setCursor(Qt.PointingHandCursor)
        self.nameWidget.mouseDoubleClickEvent = self.nameMouseDoubleClickEvent
        self.nameWidget.contextMenuEvent = self.nameContextMenuEvent

        self.templateWidget = TemplateWidgets[template]()

        buttonsLayout = QHBoxLayout()
        buttonsLayout.setContentsMargins(0,0,0,0)
        upBtn = QPushButton("<")
        upBtn.setFixedSize(35, 25)
        upBtn.clicked.connect(self._onUpBtnClicked)

        downBtn = QPushButton(">")
        downBtn.setFixedSize(35, 25)
        downBtn.clicked.connect(self._onDownBtnClicked)

        removeBtn = QPushButton("x")
        removeBtn.setFixedSize(35, 25)
        removeBtn.clicked.connect(self._onRemoveBtnClicked)

        buttonsLayout.addWidget(upBtn)
        buttonsLayout.addWidget(downBtn)
        buttonsLayout.addWidget(removeBtn)

        layout.addWidget(self.nameWidget)
        layout.addWidget(self.templateWidget)
        layout.addLayout(buttonsLayout)

    def nameContextMenuEvent(self, event: QContextMenuEvent):
        menu = QMenu(self)
        titleAction = menu.addAction(self.nameWidget.text())
        titleAction.setEnabled(False)
        font = titleAction.font()
        font.setBold(True)
        titleAction.setFont(font)
        menu.addSeparator()

        menu.addAction("Copy", self.copyTemplate)

        if EditTemplateWidget.Clipboard and EditTemplateWidget.Clipboard[0]["template"] == self.template:
            menu.addAction("Paste", partial(self.templateWidget.setJsonData, EditTemplateWidget.Clipboard[0]["data"]))

        menu.popup(event.globalPos())

    def copyTemplate(self):
        module = {"data": self.templateWidget.getJsonData(),
                  "template": self.template,
                  "name": self.nameWidget.text()}

        EditTemplateWidget.Clipboard = [module]

    def nameMouseDoubleClickEvent(self, event: QMouseEvent):
        oldName = self.nameWidget.text()
        newName, ok = QInputDialog.getText(self, "Rig Builder", "New name", QLineEdit.Normal, oldName)
        if ok:
            newName = replaceSpecialChars(newName)
            self.nameWidget.setText(newName)
            self.nameChanged.emit(oldName, newName)

    def _onRemoveBtnClicked(self):
        if QMessageBox.question(self, "Rig Builder", "Remove '{}' attribute?".format(self.nameWidget.text()), QMessageBox.Yes and QMessageBox.No, QMessageBox.Yes) == QMessageBox.Yes:
            self.copyTemplate()
            self.deleteLater()

    def _onDownBtnClicked(self):
        editAttrsWidget = self.parent()
        idx = editAttrsWidget.attributesLayout.indexOf(self)
        if idx < editAttrsWidget.attributesLayout.count()-1:
            w = editAttrsWidget.insertCustomWidget(self.template, idx+2)
            w.templateWidget.setJsonData(self.templateWidget.getJsonData())
            w.nameWidget.setText(self.nameWidget.text())
            w.attrConnect = self.attrConnect
            w.attrExpression = self.attrExpression
            w.attrModified = self.attrModified
            self.deleteLater()

    def _onUpBtnClicked(self):
        editAttrsWidget = self.parent()
        idx = editAttrsWidget.attributesLayout.indexOf(self)
        if idx > 0:
            w = editAttrsWidget.insertCustomWidget(self.template, idx-1)
            w.templateWidget.setJsonData(self.templateWidget.getJsonData())
            w.nameWidget.setText(self.nameWidget.text())
            w.attrConnect = self.attrConnect
            w.attrExpression = self.attrExpression
            w.attrModified = self.attrModified
            self.deleteLater()

class EditAttributesWidget(QWidget):
    nameChanged = Signal(str, str)
    RecentTemplates = []

    def __init__(self, moduleItem: "ModuleItem", category: str, **kwargs):
        super().__init__(**kwargs)

        self.moduleItem = moduleItem
        self.category = category

        layout = QVBoxLayout()
        self.setLayout(layout)

        self.attributesLayout = QVBoxLayout()
        self.placeholderWidget = QLabel("Right-click to add attributes")
        self.placeholderWidget.setAlignment(Qt.AlignCenter)
        self.placeholderWidget.setStyleSheet("color: gray;")

        for a in self.moduleItem.module.attributes():
            if a.category() == self.category:
                w = self.insertCustomWidget(a.template())
                w.nameWidget.setText(a.name())
                w.templateWidget.setJsonData(a.localData())
                w.attrConnect = a.connect()
                w.attrExpression = a.expression()
                w.attrModified = a.modified()

        layout.addWidget(self.placeholderWidget)
        layout.addLayout(self.attributesLayout)
        layout.addStretch()

    def contextMenuEvent(self, event: QContextMenuEvent):
        menu = QMenu(self)

        menu.addAction("Add", self.addTemplateAttribute)
        menu.addAction("Copy visible", self.copyVisibleAttributes)

        if EditTemplateWidget.Clipboard:
            menu.addAction("Paste", self.pasteAttribute)

        if EditAttributesWidget.RecentTemplates:
            menu.addSeparator()
            titleAction = menu.addAction("Recent")
            titleAction.setEnabled(False)
            font = titleAction.font()
            font.setBold(True)
            titleAction.setFont(font)
            for t in EditAttributesWidget.RecentTemplates:
                menu.addAction("  " + t, partial(self._onTemplateSelected, t))

        menu.popup(event.globalPos())

    def copyVisibleAttributes(self):
        EditTemplateWidget.Clipboard = []

        for k in range(self.attributesLayout.count()):
            w = self.attributesLayout.itemAt(k).widget()
            module = {"data": w.templateWidget.getJsonData(),
                      "name": w.nameWidget.text(),
                      "template": w.template}
            EditTemplateWidget.Clipboard.append(module)

    def pasteAttribute(self):
        for module in EditTemplateWidget.Clipboard:
            w = self.insertCustomWidget(module["template"])
            w.templateWidget.setJsonData(module["data"])
            w.nameWidget.setText(module["name"])

    def _onTemplateSelected(self, template: str):
        if template in EditAttributesWidget.RecentTemplates:
            EditAttributesWidget.RecentTemplates.remove(template)
        EditAttributesWidget.RecentTemplates.insert(0, template)
        EditAttributesWidget.RecentTemplates = EditAttributesWidget.RecentTemplates[:5]
        self.insertCustomWidget(template)

    def addTemplateAttribute(self):
        selector = TemplateSelectorDialog(parent=mainWindow)
        selector.selectedTemplate.connect(self._onTemplateSelected)
        selector.exec()

    def insertCustomWidget(self, template: str, row: Optional[int] = None) -> Optional[EditTemplateWidget]:
        if not TemplateWidgets.get(template):
            return

        row = self.attributesLayout.count() if row is None else row
        w = EditTemplateWidget("attr{}".format(row+1), template)
        w.templateWidget.setJsonData(w.templateWidget.getDefaultData())
        w.nameChanged.connect(self.nameChanged.emit)
        self.attributesLayout.insertWidget(row, w)
        return w

    def resizeNameFields(self):
        fontMetrics = self.fontMetrics()
        maxWidth = max([getFontWidth(fontMetrics, self.attributesLayout.itemAt(k).widget().nameWidget.text()) for k in range(self.attributesLayout.count())])
        for k in range(self.attributesLayout.count()):
            w = self.attributesLayout.itemAt(k).widget()
            w.nameWidget.setFixedWidth(maxWidth)

class EditAttributesTabWidget(QTabWidget):
    def __init__(self, moduleItem: ModuleItem, currentIndex: int = 0, **kwargs):
        super().__init__(**kwargs)

        self.moduleItem = moduleItem
        self.tempRunCode = moduleItem.module.runCode()

        self.setTabBar(QTabBar())
        self.setMovable(True)
        self.setTabsClosable(True)
        self.tabBar().mouseDoubleClickEvent = self.tabBarMouseDoubleClickEvent
        self.tabCloseRequested.connect(self._onTabCloseRequested)

        tabTitlesInOrder = []
        for a in self.moduleItem.module.attributes():
            if a.category() not in tabTitlesInOrder:
                tabTitlesInOrder.append(a.category())

        for t in tabTitlesInOrder:
            self.addTabCategory(t)

        if self.count() == 0:
            self.addTabCategory("General")

        self.setCurrentIndex(currentIndex)

    def addTabCategory(self, category: str):
        w = EditAttributesWidget(self.moduleItem, category)
        w.nameChanged.connect(self._onNameChanged)

        scrollArea = QScrollArea()
        scrollArea.setWidget(w)
        scrollArea.setWidgetResizable(True)
        self.addTab(scrollArea, category)
        self.setCurrentIndex(self.count()-1)

    def _onNameChanged(self, oldName: str, newName: str):
        sameAttrs = []
        for i in range(self.count()): # find other attributes with the same name, if any, then don't rename in code and connections
            attrsLayout = self.widget(i).widget().attributesLayout # tab/scrollArea/EditAttributesWidget

            for k in range(attrsLayout.count()):
                w = attrsLayout.itemAt(k).widget()
                attrName = w.nameWidget.text()
                if attrName == oldName:
                    sameAttrs.append(w)

        if oldName.strip() and not sameAttrs:
            pairs = [("@\\b{}\\b".format(oldName), "@"+newName),
                     ("@\\bset_{}\\b".format(oldName), "@set_"+newName),
                     ("@\\b{}_data\\b".format(oldName), "@"+newName+"_data")]

            self.tempRunCode = replacePairs(pairs, self.tempRunCode)

            # rename in connections
            attr = self.moduleItem.module.findAttribute(oldName)
            if attr:
                for a in attr.listConnections():
                    c = self.moduleItem.module.path().replace(attr.module().path(inclusive=False), "") + "/" + newName # update connection path
                    a.setConnect(c)

    def tabBarMouseDoubleClickEvent(self, event: QMouseEvent):
        super().mouseDoubleClickEvent(event)

        idx = self.currentIndex()
        newName, ok = QInputDialog.getText(self, "Rig Builder", "New name", QLineEdit.Normal, self.tabText(idx))
        if ok:
            self.setTabText(idx, newName)

    def _onTabCloseRequested(self, i: int):
        if QMessageBox.question(self, "Rig Builder", "Remove '{}' tab?".format(self.tabText(i)), QMessageBox.Yes and QMessageBox.No, QMessageBox.Yes) == QMessageBox.Yes:
            self.setCurrentIndex(i-1)
            self.clearTab(i)

    def contextMenuEvent(self, event: QContextMenuEvent):
        menu = QMenu(self)
        menu.addAction("New tab", partial(self.addTabCategory, "Untitled"))
        menu.popup(event.globalPos())

    def clearTab(self, i: int):
        self.widget(i).deleteLater()
        self.removeTab(i)

    def clearTabs(self):
        for _ in range(self.count()):
            self.clearTab(0)
        self.clear()

class EditAttributesDialog(QDialog):
    def __init__(self, moduleItem: ModuleItem, currentIndex: int = 0, **kwargs):
        super().__init__(**kwargs)

        self.moduleItem = moduleItem

        self.setWindowTitle("Edit Attributes - " + self.moduleItem.module.name())
        self.setGeometry(0, 0, 800, 600)

        layout = QVBoxLayout()
        self.setLayout(layout)

        self.tabWidget = EditAttributesTabWidget(self.moduleItem, currentIndex)

        okBtn = QPushButton("Ok")
        okBtn.clicked.connect(self.saveAttributes)
        cancelBtn = QPushButton("Cancel")
        cancelBtn.clicked.connect(self.close)

        hlayout = QHBoxLayout()
        hlayout.addWidget(okBtn)
        hlayout.addWidget(cancelBtn)

        layout.addWidget(self.tabWidget)
        layout.addLayout(hlayout)

        centerWindow(self)

    def saveAttributes(self):
        module = self.moduleItem.module

        def attrMetaEqual(a: Attribute, b: Attribute) -> bool:
            return (a.name() == b.name()
                    and a.category() == b.category()
                    and a.template() == b.template()
                    and a.connect() == b.connect()
                    and a.expression() == b.expression()
                    and a.localData() == b.localData())

        origAttrs = list(module.attributes())
        origByName = {a.name(): a for a in origAttrs if a.name()}
        origModuleModified = module.modified()

        newAttrs = self.buildAttributesFromTabs()
        newRunCode = self.tabWidget.tempRunCode

        module.removeAttributes()

        anythingChanged = len(origAttrs) != len(newAttrs)
        for a in newAttrs:
            module.addAttribute(a)
            if not a.name():
                continue

            orig = origByName.get(a.name())
            if orig is None or not attrMetaEqual(orig, a) or orig.modified():
                a._modified = True
                anythingChanged = True

        if module.runCode() != newRunCode:
            module.setRunCode(newRunCode)
            anythingChanged = True

        if not anythingChanged and not origModuleModified:
            module._modified = False

        self.moduleItem.emitDataChanged()
        self.accept()

    def buildAttributesFromTabs(self) -> List[Attribute]:
        attrs = []
        for i in range(self.tabWidget.count()):
            attrsLayout = self.tabWidget.widget(i).widget().attributesLayout
            category = self.tabWidget.tabText(i)

            for k in range(attrsLayout.count()):
                w = attrsLayout.itemAt(k).widget()

                a = Attribute()
                a._name = w.nameWidget.text()
                a._category = category
                a._template = w.template
                a._connect = w.attrConnect
                a._expression = w.attrExpression
                a._data = copyJson(w.templateWidget.getJsonData())
                attrs.append(a)

        return attrs

class CodeEditorWidget(CodeEditorWithNumbersWidget):
    def __init__(self, moduleItem: Optional[ModuleItem] = None, *, mainWindow: 'RigBuilderWindow', **kwargs):
        super().__init__(**kwargs)

        self.mainWindow = mainWindow
        self.moduleItem = moduleItem
        self._skipSaving = False

        self.editorWidget.textChanged.connect(self._onCodeChanged)

        self.updateState()

    def _onCodeChanged(self):
        if not self.moduleItem or self._skipSaving:
            return

        self.moduleItem.module.setRunCode(self.editorWidget.toPlainText())
        self.moduleItem.emitDataChanged()

    def updateState(self):
        if not self.moduleItem:
            return

        self.editorWidget.ignoreStates = True
        self._skipSaving = True
        self.editorWidget.setText(self.moduleItem.module.runCode())
        self._skipSaving = False
        self.editorWidget.ignoreStates = False

        self.editorWidget.document().clearUndoRedoStacks()
        self.generateCompletionWords()

        self.editorWidget.preset = id(self.moduleItem)
        self.editorWidget.loadState()

    def generateCompletionWords(self):
        if not self.moduleItem:
            return

        words = set(self.moduleItem.module.context().keys())

        for a in self.moduleItem.module.attributes():
            words.add("@" + a.name())
            words.add("@" + a.name() + "_data")
            words.add("@set_" + a.name())

        self.editorWidget.words = words

class LogHighligher(QSyntaxHighlighter):
    def __init__(self, parent: QTextDocument):
        super().__init__(parent)

        self.highlightingRules = []

        warningFormat = QTextCharFormat()
        warningFormat.setForeground(QColor(250, 150, 90))
        self.highlightingRules.append(("(?i)\\b\\w*warning\\b", warningFormat))

        errorFormat = QTextCharFormat()
        errorFormat.setForeground(QColor(250, 90, 90))
        self.highlightingRules.append(("(?i)\\b\\w*error\\b", errorFormat))

    def highlightBlock(self, text: str):
        for pattern, format in self.highlightingRules:
            if not pattern:
                continue

            expression = QRegularExpression(pattern)
            iterator = expression.globalMatch(text)
            while iterator.hasNext():
                match = iterator.next()
                self.setFormat(match.capturedStart(), match.capturedLength(), format)

        self.setCurrentBlockState(0)

class LogWidget(QTextEdit):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)

        self.syntax = LogHighligher(self.document())
        self.setPlaceholderText("Output and errors or warnings...")

    def write(self, txt: str):
        self.insertPlainText(txt)
        self.ensureCursorVisible()
        QApplication.processEvents()

    def flush(self):
        return


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


class DiffViewDialog(QDialog):
    """Modal dialog showing inline unified diff with git-style coloring."""

    def __init__(self, diffText: str, fromDesc: str, toDesc: str, parent: Optional[QWidget] = None):
        super().__init__(parent)

        self.setWindowTitle("Diff: {} vs {}".format(fromDesc, toDesc))
        self.setMinimumSize(700, 450)
        self.resize(900, 550)

        layout = QVBoxLayout(self)
        self.textEdit = QPlainTextEdit()
        self.textEdit.setReadOnly(True)
        self.textEdit.setPlainText(diffText)
        DiffHighlighter(self.textEdit.document())
        layout.addWidget(self.textEdit)

        closeBtn = QPushButton("Close")
        closeBtn.clicked.connect(self.accept)
        layout.addWidget(closeBtn)

        centerWindow(self)


class WideSplitterHandle(QSplitterHandle):
    def __init__(self, orientation: Qt.Orientation, parent: QWidget, **kwargs):
        super().__init__(orientation, parent, **kwargs)

    def paintEvent(self, event: QPaintEvent):
        painter = QPainter()
        if painter.begin(self):
            try:
                brush = QBrush()
                brush.setStyle(Qt.Dense6Pattern)
                brush.setColor(QColor(150, 150, 150))
                painter.fillRect(event.rect(), QBrush(brush))
            finally:
                painter.end()

class WideSplitter(QSplitter):
    def __init__(self, orientation: Qt.Orientation, width: int = 16, **kwargs):
        super().__init__(orientation, **kwargs)
        self.setHandleWidth(width)

    def createHandle(self) -> QSplitterHandle:
        return WideSplitterHandle(self.orientation(), self)

class MyProgressBar(QWidget):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)

        self.queue = []
        self.labelSize = 25

        layout = QHBoxLayout()
        self.setLayout(layout)
        layout.setContentsMargins(0, 0, 0, 0)

        self.labelWidget = QLabel()
        self.progressBarWidget = QProgressBar()
        layout.addWidget(self.labelWidget)
        layout.addWidget(self.progressBarWidget)

    def initialize(self):
        self.queue = []

    def updateWithState(self, state: Dict[str, object]):
        trimText = lambda text, size: "..." + text[-size+3:]  if len(text) > size else " "*(size-len(text)) + text
        self.labelWidget.setText(trimText(state["text"], self.labelSize))
        self.progressBarWidget.setValue(state["value"])
        self.progressBarWidget.setMaximum(state["max"])

    def beginProgress(self, text: str, count: int, updatePercent: float = 0.01):
        q = {"text": text, "max": count, "value": 0, "updatePercent":updatePercent}
        self.queue.append(q)
        self.updateWithState(q)
        self.show()

    def stepProgress(self, value: int, text: Optional[str] = None):
        q = self.queue[-1]
        q["value"] = value

        updateValue = int(clamp(q["max"] * q["updatePercent"], 1, q["max"]))

        if not q["updatePercent"] or value % updateValue == 0:
            if text:
                q["text"] = text
            self.updateWithState(q)
            QApplication.processEvents()

    def endProgress(self):
        self.queue.pop()
        if not self.queue:
            self.hide()
        else:
            q = self.queue[-1] # get latest state
            self.updateWithState(q)


class RigBuilderWindow(QFrame):
    # === API SIGNALS ===
    moduleSelected = Signal(object)  # ModuleItem
    moduleAdded = Signal(object)     # ModuleItem
    moduleRemoved = Signal(object)   # ModuleItem
    moduleChanged = Signal(object)   # ModuleItem
    attributeChanged = Signal(object, object)  # ModuleItem, Attribute
    aboutToRunModule = Signal()

    def __init__(self):
        super().__init__(parent=parentWindow)
        self.modulesAutoReloadWatcher = None

        self.setWindowTitle("Rig Builder {}".format(__version__))
        self.setGeometry(0, 0, 1300, 700)

        self.setWindowFlags(self.windowFlags() | Qt.Window)

        layout = QVBoxLayout()
        self.setLayout(layout)

        self.logWidget = LogWidget()
        self.logWidget.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Ignored)
        
        # Create isolated logger for this window
        self.logger = logging.getLogger(f'rigBuilder_{id(self):0x}')
        self.logger.setLevel(logging.DEBUG)
        
        # Create isolated log handler for this window
        self.logHandler = RigBuilderLogHandler()
        self.logHandler.setLogWidget(self.logWidget)
        self.logHandler.setFormatter(logging.Formatter('%(levelname)s: %(message)s'))
        self.logger.addHandler(self.logHandler)

        self.attributesTabWidget = AttributesTabWidget(None, mainWindow=self)

        self.treeWidget = TreeWidget(mainWindow=self)
        self.treeWidget.itemSelectionChanged.connect(self._onTreeItemSelectionChanged)

        self.codeEditorWidget = CodeEditorWidget(mainWindow=self)
        self.codeEditorWidget.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Ignored)
        self.codeEditorWidget.editorWidget.setPlaceholderText("Your module code...")

        self.vscodeBtn = QPushButton("Edit in VSCode")
        self.vscodeBtn.clicked.connect(self.editInVSCode)
        self.vscodeBtn.setContextMenuPolicy(Qt.CustomContextMenu)
        self.vscodeBtn.customContextMenuRequested.connect(self.onVscodeBtnContextMenu)

        self.codeWidget = QWidget()
        self.codeWidget.setLayout(QVBoxLayout())
        self.codeWidget.layout().addWidget(self.codeEditorWidget)
        self.codeWidget.layout().addWidget(self.vscodeBtn)

        self.runBtn = QPushButton("Run!")
        self.runBtn.setStyleSheet("background-color: #3e4f89")
        self.runBtn.clicked.connect(self.runModule)
        self.runBtn.hide()

        self.moduleHistoryWidget = ModuleHistoryWidget(self)

        self.docBrowser = DocBrowser(mainWindow=self)

        self.rightSplitter = WideSplitter(Qt.Vertical, 4)
        self.rightSplitter.addWidget(self.attributesTabWidget)
        self.rightSplitter.addWidget(self.docBrowser)
        self.rightSplitter.setSizes([400, 100])
        self.rightSplitter.hide()

        rightWidget = QWidget()
        rightWidget.setLayout(QVBoxLayout())
        rightWidgetLayout = rightWidget.layout()
        rightWidgetLayout.setContentsMargins(0, 0, 0, 0)
        rightWidgetLayout.addWidget(self.moduleHistoryWidget)
        rightWidgetLayout.addWidget(self.rightSplitter)
        rightWidgetLayout.addWidget(self.runBtn)

        self.moduleSelectorWidget = ModuleSelectorWidget()

        self.leftSplitter = WideSplitter(Qt.Vertical, 8)
        self.leftSplitter.addWidget(self.treeWidget)
        self.leftSplitter.addWidget(self.moduleSelectorWidget)
        self.leftSplitter.setSizes([300, 200])

        self.mainContentSplitter = WideSplitter(Qt.Horizontal)
        self.mainContentSplitter.addWidget(self.leftSplitter)
        self.mainContentSplitter.addWidget(rightWidget)
        self.mainContentSplitter.setSizes([400, 600])

        self.workspaceSplitter = WideSplitter(Qt.Vertical)
        self.workspaceSplitter.addWidget(self.mainContentSplitter)
        self.workspaceSplitter.addWidget(self.codeWidget)
        self.workspaceSplitter.addWidget(self.logWidget)
        self.workspaceSplitter.setSizes([400, 0, 0])

        self.workspaceSplitter.splitterMoved.connect(self._onCodeSplitterMoved)
        self.codeWidget.setEnabled(False)

        self.progressBarWidget = MyProgressBar()
        self.progressBarWidget.hide()

        self.treeWidget.addActions(getActions(self.menu()))
        setActionsLocalShortcut(self.treeWidget)

        layout.addWidget(self.workspaceSplitter)
        layout.addWidget(self.progressBarWidget)

        centerWindow(self)
        applyStylesheet(self)

    def setupModulesAutoReloadWatcher(self):
        watchRoots = [getServerModulesPath(), getLocalModulesPath()]
        self.modulesAutoReloadWatcher = DirectoryWatcher(
            watchRoots,
            filePatterns=["*.xml"],
            debounceMs=700,
            recursive=True,
            parent=self
        )
        self.modulesAutoReloadWatcher.somethingChanged.connect(self._onModulesReloaded)

    def _onModulesReloaded(self):
        Module.updateUidsCache()
        self.moduleSelectorWidget.applyMask()

    def menu(self):
        menu = QMenu(self)

        menu.addAction("New", self.treeWidget.insertModule, "Insert")
        menu.addAction("Import", self.treeWidget.importModule, "Ctrl+I")
        menu.addAction("Import script", self.treeWidget.importScript)
        menu.addSeparator()
        menu.addAction("Save", self.treeWidget.saveModule, "Ctrl+S")
        menu.addAction("Save as", self.treeWidget.saveAsModule)
        menu.addAction("Send to server", self.treeWidget.sendModuleToServer, "Ctrl+P")
        menu.addSeparator()

        menu.addAction("Locate file", self.locateModuleFile)
        menu.addAction("Copy tool code", self.copyToolCode)
        menu.addAction("View edit history", self.showModuleInHistory, "Ctrl+H")
        menu.addSeparator()
        menu.addAction("Duplicate", self.treeWidget.duplicateModule, "Ctrl+D")
        menu.addSeparator()
        menu.addAction("Copy", self.treeWidget.copyModules, "Ctrl+C")
        menu.addAction("Cut", self.treeWidget.cutModules, "Ctrl+X")
        if self.treeWidget.clipboard:
            menu.addAction("Paste", self.treeWidget.pasteModules, "Ctrl+V")
        menu.addSeparator()

        diffMenu = menu.addMenu("Diff")
        diffMenu.addAction("vs File", self.diffModule, "Alt+D")
        diffMenu.addAction("vs Server", partial(self.diffModule, reference="server"), "Ctrl+Alt+D")

        menu.addAction("Update", self.treeWidget.updateModule, "Ctrl+U")
        menu.addAction("Embed", self.treeWidget.embedModule)

        menu.addSeparator()
        menu.addAction("Mute", self.treeWidget.muteModule, "M")
        menu.addAction("Remove", self.treeWidget.removeModule, "Delete")
        menu.addAction("Remove all", self.removeAllModules)

        menu.addAction("Documentation", self.showDocumenation, "F1")
        menu.addSeparator()
        menu.addAction("API Browser", self.openApiBrowser)
        menu.addAction("Function Browser", self.openFunctionBrowser)

        return menu

    def onVscodeBtnContextMenu(self, pos):
        menu = QMenu(self)
        menu.addAction("Set VSCode command", self.setVscodeCommand)
        menu.exec_(self.vscodeBtn.mapToGlobal(pos))

    def setVscodeCommand(self):
        currentCommand = Settings.get("vscode", "vscode.exe")
        message = "VSCode command."
        command, ok = QInputDialog.getText(self, "Rig Builder", message, QLineEdit.Normal, currentCommand)
        if not ok:
            return

        Settings["vscode"] = command.strip()
        saveSettings()

    def editInVSCode(self):
        def getFunctionDefinition(f: Callable[..., object], *, name: Optional[str] = None) -> str: # f(a,b,c=1) => 'def f(a,b,c=1):pass'
            signature = inspect.signature(f)
            args = []
            for p in signature.parameters.values():
                if p.default == p.empty:
                    args.append(p.name)
                else:
                    args.append("{}={}".format(p.name, p.default))
            return "def {}({}):pass".format(name or f.__name__, ", ".join(args))

        def getVariableValue(v: object) -> Optional[object]:
            if type(v) == str:
                return '"' + v + '"'

            try:
                _ = json.dumps(v) # check if v is JSON serializable
            except:
                return None

            return v

        def onRunCodeFileChanged(filePath: str):
            nonlocal item
            if not item:
                return

            with open(filePath, "r") as f:
                lines = f.read().splitlines()

            code = "\n".join(lines[1:]) # skip first line: import predefined things
            code = replaceAttrPrefixInverse(code)
            item.module.setRunCode(code)
            self.codeEditorWidget.updateState()

        def onModuleFileChanged(filePath: str):
            nonlocal item
            if not item:
                return

            try:
                editedModule = Module.loadFromFile(filePath)
            except Exception:
                QMessageBox.warning(self, "Rig Builder", "Failed to load module file")
                return

            childItems = item.takeChildren()
            item.module.removeChildren()
            editedModule.removeChildren()
            newItem = self.treeWidget.replaceModule(item, editedModule)

            for childItem in childItems:
                newItem.addChild(childItem)
                newItem.module.addChild(childItem.module)

            item = newItem

        def startTrackedFileThread(filePath: str, callback: Callable[..., None]):
            if filePath in trackFileChangesThreads:
                trackFileChangesThreads[filePath].terminate()

            th = TrackFileChangesThread(filePath)
            th.somethingChanged.connect(callback)
            th.start()
            trackFileChangesThreads[filePath] = th

        item = self.currentModule()
        if not item:
            return

        setupVscode()

        module = item.module

        # generate predefined things
        fileName = module.path().replace("/", "__")
        predefinedFile = os.path.join(RigBuilderLocalPath, "vscode", "{}_predef.py".format(fileName))
        runCodeFilePath = os.path.join(RigBuilderLocalPath, "vscode", "{}.py".format(fileName))

        moduleFilePath = runCodeFilePath.replace(".py", MODULE_EXT)
        tmpModule = module.copy()
        tmpModule.setRunCode("") # run code is editable in VSCode with its own file
        tmpModule.removeChildren() # remove children to avoid editing them, module must be self-contained
        tmpModule.saveToFile(moduleFilePath)

        predefinedCode = ["# Use AI_context.md for technical specification."]

        # expose attributes
        for a in module.attributes():
            predefinedCode.append("{}{} = {}".format(ATTR_PREFIX, a.name(), getVariableValue(a.get())))
            predefinedCode.append(getFunctionDefinition(a.set, name="{}set_{}".format(ATTR_PREFIX, a.name())))
            predefinedCode.append("{}{}_data = {}".format(ATTR_PREFIX, a.name(), a.data()))

        # expose API
        env = module.context()

        for k, v in env.items():
            if callable(v):
                predefinedCode.append(getFunctionDefinition(v, name=k))
            else:
                predefinedCode.append("{} = {}".format(k, getVariableValue(v)))

        with open(predefinedFile, "w") as f:
            f.write("\n".join(predefinedCode))

        with open(runCodeFilePath, "w") as f:
            predefinedModule = os.path.splitext(os.path.basename(predefinedFile))[0]
            code = replaceAttrPrefix(module.runCode())
            importLine = "from .{} import * # must be the first line".format(predefinedModule)
            f.write("\n".join([importLine, code]))

        contextFilePath = os.path.join(RigBuilderLocalPath, "vscode", "AI_context.md")
        shutil.copyfile("AI_context.md", contextFilePath)

        startTrackedFileThread(
            runCodeFilePath,
            partial(onRunCodeFileChanged, runCodeFilePath),
        )
        startTrackedFileThread(
            moduleFilePath,
            partial(onModuleFileChanged, moduleFilePath),
        )

        if not shutil.which(Settings["vscode"]):
            msg = "Editor executable not found: {}\n\nPlease install the editor or update the VSCode command from the button context menu.".format(Settings["vscode"])
            QMessageBox.warning(self,"Editor Error", msg)
            return

        try:
            subprocess.Popen([Settings["vscode"], RigBuilderLocalPath+"/vscode", "-g", runCodeFilePath], shell=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        except Exception as e:
            QMessageBox.warning(self, "Editor Error", f"Failed to launch editor: {str(e)}")

    def diffModule(self, *, reference: Optional[str] = None):
        import difflib

        item = self.currentModule()
        if not item:
            return

        module = item.module

        path = module.referenceFile(source=reference) if reference else module.filePath()
        if not path:
            QMessageBox.warning(self, "Rig Builder", "Can't find reference file")
            return

        path = os.path.normpath(path)
        currentXml = module.toXml()
        with open(path, "r") as f:
            originalXml = f.read()

        fromDesc = path
        toDesc = "Current"
        diffLines = difflib.unified_diff(
            originalXml.splitlines(),
            currentXml.splitlines(),
            fromfile=fromDesc,
            tofile=toDesc,
            lineterm="",
        )
        diffText = "\n".join(diffLines)

        dlg = DiffViewDialog(diffText, fromDesc, toDesc, parent=self)
        execFunc(dlg)
                    
    def copyToolCode(self):
        item = self.currentModule()
        if not item:
            return
            
        if item.module.loadedFromLocal() or item.module.loadedFromServer():
            code = '''import rigBuilder.ui;rigBuilder.ui.RigBuilderTool(r"{}").show()'''.format(item.module.relativePath())
            QApplication.clipboard().setText(code)
        else:
            QMessageBox.critical(self, "Rig Builder", "Module must be loaded from local or server!")

    def removeAllModules(self):
        if QMessageBox.question(self, "Rig Builder", "Remove all modules?", QMessageBox.Yes and QMessageBox.No, QMessageBox.Yes) == QMessageBox.Yes:
            self.treeWidget.clear()

    def showDocumenation(self):
        subprocess.Popen(["explorer", "https://github.com/azagoruyko/rigBuilder/wiki/Documentation"])

    def openApiBrowser(self):
        from .apiBrowser import showApiBrowser
        showApiBrowser(parent=self)

    def openFunctionBrowser(self):
        from .functionBrowser import showFunctionBrowser
        showFunctionBrowser(parent=self)

    def locateModuleFile(self):
        for item in self.treeWidget.selectedItems():
            if item and os.path.exists(item.module.filePath()):
                subprocess.call("explorer /select,\"{}\"".format(os.path.normpath(item.module.filePath())))

    def _onTreeItemSelectionChanged(self):
        item = self.currentModule()
        en = item is not None
        self.rightSplitter.setVisible(en)
        self.runBtn.setVisible(en)
        self.moduleHistoryWidget.setVisible(not en)
        self.docBrowser.setVisible(en)
        self.codeWidget.setEnabled(en and not self.isCodeEditorHidden())

        if item:
            self.attributesTabWidget.moduleItem = item
            self.attributesTabWidget.updateTabs()

            if self.codeWidget.isEnabled():
                self.codeEditorWidget.moduleItem = item
                self.codeEditorWidget.updateState()
            
            # Validate module and log errors
            if not item.validateModule():
                # Show log if validation failed
                self.showLog()
            

            # Emit API signal
            self.moduleSelected.emit(item)

        self.docBrowser.updateDoc()

    def showDiffView(self, diffText: str, fromDesc: str, toDesc: str):
        """Show diff in a modal dialog (used by history link handler)."""
        dlg = DiffViewDialog(diffText, fromDesc, toDesc, parent=self)
        execFunc(dlg)

    def isCodeEditorHidden(self) -> bool:
        return self.workspaceSplitter.sizes()[1] == 0 # code section size

    def _onCodeSplitterMoved(self, sz: int, n: int):
        if self.isCodeEditorHidden():
            self.codeWidget.setEnabled(False)

        elif not self.codeWidget.isEnabled():
            item = self.currentModule()
            if item:
                self.codeEditorWidget.moduleItem = item
                self.codeEditorWidget.updateState()
                self.codeWidget.setEnabled(True)

    def showLog(self):
        sizes = self.workspaceSplitter.sizes()
        if sizes[-1] < 10:
            sizes[-1] = 200
            self.workspaceSplitter.setSizes(sizes)
        self.logWidget.ensureCursorVisible()

    def runModule(self, moduleItem: Optional[ModuleItem] = None):
        """Run module with full UI support (progress, undo, logging)."""

        def uiCallback(module: Module):
            self.logger.info(f"{module.path()} is running...")
            self.progressBarWidget.stepProgress(self.progressCounter, module.path())
            self.progressCounter += 1

        def getChildrenCount(item: ModuleItem) -> int:
            count = 0
            for i in range(item.childCount()):
                count += 1
                count += getChildrenCount(item.child(i))
            return count

        self.aboutToRunModule.emit()

        # Determine which module to run
        if moduleItem:
            currentItem = moduleItem
        else:
            currentItem = self.currentModule()
            if not currentItem:
                self.logger.warning("No module selected for execution")
                return

        self.logger.info(f"Running module: {currentItem.module.name()}")

        self.setFocus()

        self.logWidget.clear()
        self.showLog()

        with captureOutput(self.logWidget):
            startTime = time.time()

            self.progressBarWidget.initialize()
            self.progressCounter = 0

            count = getChildrenCount(currentItem)
            self.progressBarWidget.beginProgress(currentItem.module.name(), count+1)

            muted = currentItem.module.muted()
            currentItem.module.unmute()

            APIRegistry.override("beginProgress", self.progressBarWidget.beginProgress) # update UI functions
            APIRegistry.override("stepProgress", self.progressBarWidget.stepProgress)
            APIRegistry.override("endProgress", self.progressBarWidget.endProgress)

            try:
                APIRegistry.openUndoChunk()

                currentItem.module.run(callback=uiCallback)

            except ModuleRuntimeError as e:
                self.logger.error(str(e))
            except Exception as e:
                self.logger.error(f"Unexpected error in module '{currentItem.module.name()}': {str(e)}")
                printErrorStack()
            finally:
                APIRegistry.closeUndoChunk()
                    
                if muted:
                    currentItem.module.mute()

                executionTime = time.time() - startTime
                self.logger.info(f"Execution completed in {executionTime:.2f}s")

        self.progressBarWidget.endProgress()
        self.attributesTabWidget.updateTabs()

    # === API METHODS FOR MODULE MANAGEMENT ===
    
    def addModule(self, moduleOrPath: Union[str, Module], parent: Optional[ModuleItem] = None) -> Optional[ModuleItem]:
        """Add module to the tree. Returns ModuleItem or None if failed."""
        try:
            if isinstance(moduleOrPath, str):
                # Load from file path
                module = Module.loadModule(moduleOrPath)
            else:
                # Assume it's already a Module instance
                module = moduleOrPath
            
            moduleItem = self.treeWidget.makeItemFromModule(module)
            
            if parent:
                parent.addChild(moduleItem)
                parent.module.addChild(module)
            else:
                self.treeWidget.addTopLevelItem(moduleItem)
            
            self.moduleAdded.emit(moduleItem)
            return moduleItem
            
        except Exception as e:
            self.logger.error(f"Adding module: {e}")
            return
    
    def removeModule(self, moduleItem: Optional[ModuleItem]):
        """Remove module from tree."""
        if not moduleItem:
            self.logger.warning("Cannot remove module: moduleItem is None")
            return
            
        parent = moduleItem.parent()
        if parent:
            parent.removeChild(moduleItem)
            parent.module.removeChild(moduleItem.module)
            parent.emitDataChanged()
        else:
            self.treeWidget.invisibleRootItem().removeChild(moduleItem)
        
        self.moduleRemoved.emit(moduleItem)
    
    def showModuleInHistory(self):
        """Put selected module UID into history browser filter and clear selection so user can view history."""
        item = self.currentModule()
        if not item:
            return

        module = item.module
        if not module.uid():
            return
            
        self.moduleHistoryWidget.filterEdit.setText(module.uid())
        self.treeWidget.clearSelection()

    def selectedModules(self) -> List[ModuleItem]:
        """Get list of currently selected ModuleItems."""
        return self.treeWidget.selectedItems()

    def currentModule(self) -> Optional[ModuleItem]:
        """Get currently selected module."""
        selectedItems = self.treeWidget.selectedItems()
        if selectedItems:
            return selectedItems[0]
    
    def selectModule(self, moduleItem: Optional[ModuleItem]):
        """Select specific module in tree."""
        if moduleItem:
            self.treeWidget.clearSelection()
            moduleItem.setSelected(True)
            self.treeWidget.setCurrentItem(moduleItem)
    
    def findModule(self, nameOrPath: str) -> Optional[ModuleItem]:
        """Find module by name or path in tree."""
        iterator = QTreeWidgetItemIterator(self.treeWidget)
        while iterator.value():
            item = iterator.value()
            if isinstance(item, ModuleItem):
                if (item.module.name() == nameOrPath or 
                    item.module.path() == nameOrPath):
                    return item
            iterator += 1
    


    def closeEvent(self, event):
        # Terminate all file tracking threads before closing
        for thread in trackFileChangesThreads.values():
            if thread.isRunning():
                thread.terminate()
                thread.wait(1000)  # Wait up to 1 second for thread to finish
        trackFileChangesThreads.clear()
        
        # Call parent close event
        super().closeEvent(event)

def RigBuilderTool(spec, child=None, *, size=None): # spec can be full path, relative path, uid
    module = Module.loadModule(spec)
    if not module:
        print(f"Cannot load '{spec}' module")
        return

    if child is not None:
        if type(child) == str:
            module = module.findChild(child)

        elif type(child) == int:
            module = module.children()[child]

        if not module:
            print(f"Cannot find '{child}' child")
            return

    w = RigBuilderWindow()
    w.setWindowTitle("Rig Builder Tool - {}".format(module.relativePath()))
    w.treeWidget.addTopLevelItem(w.treeWidget.makeItemFromModule(module))
    w.treeWidget.setCurrentItem(w.treeWidget.topLevelItem(0))

    w.codeWidget.hide()
    w.leftSplitter.hide()

    centerWindow(w)

    if size:
        if type(size) in [int, float]:
            size = [size, size]
        w.resize(size[0], size[1])
    else: # auto size
        w.adjustSize()

    return w

def setupVscode():  # path to .vscode folder
    settings = {
        "python.autoComplete.extraPaths": [],
    }

    folder = os.path.join(RigBuilderLocalPath, "vscode", ".vscode")
    os.makedirs(folder, exist_ok=True)
    settingsFile = os.path.join(folder, "settings.json")

    if os.path.exists(settingsFile):
        with open(settingsFile, "r") as f:
            settings.update(json.load(f))

    # ensure key exists even if missing in existing settings
    settings.setdefault("python.autoComplete.extraPaths", [])

    # add paths
    for path in sys.path:
        if path not in settings["python.autoComplete.extraPaths"]:
            settings["python.autoComplete.extraPaths"].append(path)

    with open(settingsFile, "w") as f:
        json.dump(settings, f, indent=4)

def cleanupVscode():
    vscodeFolder = RigBuilderLocalPath+"/vscode"
    if not os.path.exists(vscodeFolder):
        return
    
    for f in os.listdir(vscodeFolder):
        if f.endswith(".py") or f.endswith(MODULE_EXT): # remove module files
            os.remove(os.path.join(vscodeFolder, f))

def aboutToQuit():
    """Save workspace and settings (on quit)."""
    saveWorkspace(mainWindow)
    saveSettings()


cleanupVscode()

mainWindow = RigBuilderWindow()
loadWorkspace(mainWindow)
mainWindow.aboutToRunModule.connect(partial(saveWorkspace, mainWindow))
QApplication.instance().aboutToQuit.connect(aboutToQuit)
mainWindow.setupModulesAutoReloadWatcher()
