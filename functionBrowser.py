"""Live Python function browser using Rig Builder attribute widgets.

This module scans a folder with Python files, discovers local functions,
maps function signatures to transient Rig Builder modules, and lets users
edit arguments before execution.
"""

from __future__ import annotations

import ast
import enum
import html
import importlib
import inspect
import logging
import os
import sys
import typing

from .qt import *
from .core import Attribute
from .core import Module
from .ui import AttributesWidget
from . import ui as rigBuilderUi


class _LogTextEdit(QTextEdit):
    """QTextEdit stream adapter for stdout/stderr style writes."""

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.setReadOnly(True)
        self.setContextMenuPolicy(Qt.CustomContextMenu)
        self.customContextMenuRequested.connect(self._showContextMenu)

    def write(self, text):
        if not text:
            return
        self.moveCursor(QTextCursor.End)
        self.insertPlainText(str(text))
        self.moveCursor(QTextCursor.End)

    def flush(self):
        pass

    def _showContextMenu(self, pos):
        menu = self.createStandardContextMenu()
        menu.addSeparator()
        menu.addAction("Clear log", self.clear)
        menu.exec_(self.mapToGlobal(pos))


class _MainWindowProxy:
    """Minimal proxy required by rigBuilder.ui.AttributesWidget."""

    def __init__(self, logWidget):
        self.logWidget = logWidget
        self.logger = logging.getLogger("rigBuilder.functionBrowser")
        if not self.logger.handlers:
            self.logger.addHandler(logging.StreamHandler(stream=sys.stdout))
        self.logger.setLevel(logging.INFO)

    def showLog(self):
        return


class _ModuleItemProxy:
    """Minimal module-item wrapper required by AttributesWidget."""

    def __init__(self, module):
        self.module = module

    def parent(self):
        return None


class FunctionBrowserWindow(QWidget):
    """Browse loaded modules/functions and execute with Rig Builder controls."""

    windowInstance = None

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.setWindowFlags(Qt.Window | Qt.WindowCloseButtonHint | Qt.WindowMinMaxButtonsHint)
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setAutoFillBackground(True)
        self.setWindowTitle("Rig Builder Function Browser")
        self.setMinimumSize(1200, 700)

        self.modulesByFunctionKey = {}
        self.functionSpecsByKey = {}
        self.runtimeFunctionsByKey = {}
        self.scanRootPath = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

        self.currentFunctionKey = None
        self.currentAttributesWidget = None

        self._buildUi()
        self.refreshTree()

    def _buildUi(self):
        rootLayout = QVBoxLayout()
        self.setLayout(rootLayout)

        folderLayout = QHBoxLayout()
        rootLayout.addLayout(folderLayout)

        self.folderEdit = QLineEdit(self.scanRootPath)
        self.folderEdit.setPlaceholderText("Folder to scan for python functions...")
        self.browseFolderButton = QPushButton("Browse...")

        folderLayout.addWidget(QLabel("Folder:"))
        folderLayout.addWidget(self.folderEdit, 1)
        folderLayout.addWidget(self.browseFolderButton)

        toolLayout = QHBoxLayout()
        rootLayout.addLayout(toolLayout)

        self.filterEdit = QLineEdit()
        self.filterEdit.setPlaceholderText("Filter modules/functions...")

        self.refreshButton = QPushButton("Refresh")

        toolLayout.addWidget(QLabel("Search:"))
        toolLayout.addWidget(self.filterEdit, 1)

        splitWidget = QSplitter(Qt.Horizontal)
        rootLayout.addWidget(splitWidget, 1)

        leftPane = QWidget()
        leftLayout = QVBoxLayout()
        leftLayout.setContentsMargins(0, 0, 0, 0)
        leftPane.setLayout(leftLayout)

        self.treeWidget = QTreeWidget()
        self.treeWidget.setHeaderLabels(["Module / Function"])
        self.treeWidget.setAlternatingRowColors(True)
        self.treeWidget.setUniformRowHeights(True)
        self.treeWidget.setSelectionMode(QAbstractItemView.SingleSelection)
        leftLayout.addWidget(self.treeWidget, 1)
        leftLayout.addWidget(self.refreshButton)
        splitWidget.addWidget(leftPane)

        rightPane = QWidget()
        splitWidget.addWidget(rightPane)
        splitWidget.setStretchFactor(1, 1)

        rightLayout = QVBoxLayout()
        rightPane.setLayout(rightLayout)

        self.functionInfoLabel = QLabel("Select a function to edit arguments.")
        self.functionInfoLabel.setWordWrap(True)
        rightLayout.addWidget(self.functionInfoLabel)

        rightSplitter = QSplitter(Qt.Vertical)
        rightLayout.addWidget(rightSplitter, 1)

        attrsPane = QWidget()
        attrsLayout = QVBoxLayout()
        attrsLayout.setContentsMargins(0, 0, 0, 0)
        attrsPane.setLayout(attrsLayout)

        self.attrsScrollArea = QScrollArea()
        self.attrsScrollArea.setWidgetResizable(True)
        attrsLayout.addWidget(self.attrsScrollArea, 1)

        self.runButton = QPushButton("Run function")
        attrsLayout.addWidget(self.runButton)
        rightSplitter.addWidget(attrsPane)

        logPane = QWidget()
        logLayout = QVBoxLayout()
        logLayout.setContentsMargins(0, 0, 0, 0)
        logPane.setLayout(logLayout)

        self.logWidget = _LogTextEdit()
        self.logWidget.setMinimumHeight(120)
        logLayout.addWidget(QLabel("Output"))
        logLayout.addWidget(self.logWidget)
        rightSplitter.addWidget(logPane)
        rightSplitter.setSizes([520, 180])

        self.mainWindowProxy = _MainWindowProxy(self.logWidget)
        self.browseFolderButton.clicked.connect(self._browseFolder)
        self.refreshButton.clicked.connect(self.refreshTree)
        self.filterEdit.textChanged.connect(self.refreshTree)
        self.treeWidget.itemSelectionChanged.connect(self._onTreeSelectionChanged)
        self.runButton.clicked.connect(self.runSelectedFunction)

    def _browseFolder(self):
        currentPath = self.folderEdit.text().strip() or self.scanRootPath
        selectedPath = QFileDialog.getExistingDirectory(self, "Select scripts folder", currentPath)
        if selectedPath:
            self.folderEdit.setText(selectedPath)
            self.refreshTree()

    def _writeLog(self, text):
        self.logWidget.write(text)

    def _setFunctionInfoLabel(self, functionSpec, *, qualName=None, docString=None, notRunnableMessage=None):
        functionName = functionSpec.get("functionName", "callable")
        resolvedQualName = qualName or functionName
        titleText = "{} . {}{}".format(
            functionSpec.get("moduleName", "<unknown>"),
            resolvedQualName,
            functionSpec.get("signatureText", "()"),
        )
        resolvedDocString = docString if docString is not None else functionSpec.get("docString", "")

        lines = [
            "<b>{}</b>".format(html.escape(titleText)),
        ]
        if resolvedDocString:
            lines.append(html.escape(resolvedDocString).replace("\n", "<br>"))
        if notRunnableMessage:
            lines.extend(["", "Not runnable: {}".format(html.escape(notRunnableMessage))])
        self.functionInfoLabel.setText("<br>".join(lines))

    def _getOrLoadRuntimeFunction(self, functionSpec):
        functionKey = self.currentFunctionKey
        functionObj = self.runtimeFunctionsByKey.get(functionKey)
        if functionObj is not None:
            return functionObj

        functionObj = self._loadRuntimeFunction(functionSpec)
        self.runtimeFunctionsByKey[functionKey] = functionObj
        return functionObj

    def _normalizedRootPath(self):
        return os.path.normpath(self.folderEdit.text().strip() or self.scanRootPath)

    def _rememberExpandedModules(self):
        expandedModulePaths = set()

        def walk(item, pathParts):
            for i in range(item.childCount()):
                child = item.child(i)
                functionKey = child.data(0, Qt.UserRole)
                if functionKey:
                    continue

                childPath = pathParts + (child.text(0),)
                if child.isExpanded():
                    expandedModulePaths.add(childPath)
                walk(child, childPath)

        walk(self.treeWidget.invisibleRootItem(), tuple())
        return expandedModulePaths

    def _filterFunctionItems(self, moduleName, functionSpecs, filterText):
        if not filterText:
            return functionSpecs
        if filterText in moduleName.lower():
            return functionSpecs

        return [
            functionSpec
            for functionSpec in functionSpecs
            if filterText in functionSpec["functionName"].lower() or filterText in functionSpec["signatureText"].lower()
        ]

    def _pruneCachedUiModules(self, discoveredKeys):
        self.modulesByFunctionKey = {
            key: value
            for key, value in self.modulesByFunctionKey.items()
            if key in discoveredKeys
        }

    def _iterPythonFiles(self, rootPath):
        if not os.path.isdir(rootPath):
            return

        for dirPath, dirNames, fileNames in os.walk(rootPath):
            dirNames[:] = [name for name in dirNames if name != "__pycache__" and not name.startswith(".")]
            for fileName in sorted(fileNames):
                if fileName.endswith(".py") and not fileName.startswith("."):
                    yield os.path.join(dirPath, fileName)

    def _moduleNamesFromPath(self, filePath, rootPath):
        relativePath = os.path.relpath(filePath, rootPath).replace("\\", "/")
        if relativePath == "__init__.py":
            return "<root>", None
        if relativePath.endswith("/__init__.py"):
            displayName = relativePath[: -len("/__init__.py")].replace("/", ".")
            return displayName, displayName
        displayName = relativePath[:-3].replace("/", ".")
        return displayName, displayName

    def _signatureTextFromNode(self, functionNode):
        try:
            argsText = ast.unparse(functionNode.args)
        except Exception:
            argsText = "..."
        return "({})".format(argsText)

    def _parametersFromFunctionNode(self, functionNode):
        argsObj = functionNode.args
        parameters = []

        for i, argNode in enumerate(argsObj.posonlyargs):
            parameters.append({
                "name": argNode.arg,
                "kind": inspect.Parameter.POSITIONAL_ONLY,
                "annotationText": ast.unparse(argNode.annotation) if argNode.annotation else "",
            })

        for argNode in argsObj.args:
            parameters.append({
                "name": argNode.arg,
                "kind": inspect.Parameter.POSITIONAL_OR_KEYWORD,
                "annotationText": ast.unparse(argNode.annotation) if argNode.annotation else "",
            })

        if argsObj.vararg:
            parameters.append({
                "name": argsObj.vararg.arg,
                "kind": inspect.Parameter.VAR_POSITIONAL,
                "annotationText": ast.unparse(argsObj.vararg.annotation) if argsObj.vararg.annotation else "",
            })

        for kwArgNode in argsObj.kwonlyargs:
            parameters.append({
                "name": kwArgNode.arg,
                "kind": inspect.Parameter.KEYWORD_ONLY,
                "annotationText": ast.unparse(kwArgNode.annotation) if kwArgNode.annotation else "",
            })

        if argsObj.kwarg:
            parameters.append({
                "name": argsObj.kwarg.arg,
                "kind": inspect.Parameter.VAR_KEYWORD,
                "annotationText": ast.unparse(argsObj.kwarg.annotation) if argsObj.kwarg.annotation else "",
            })

        return parameters

    def _iterAstFunctions(self, filePath):
        with open(filePath, "r", encoding="utf-8") as fileObj:
            sourceCode = fileObj.read()
        moduleNode = ast.parse(sourceCode, filename=filePath)

        for node in moduleNode.body:
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            if node.name.startswith("_"):
                continue

            yield {
                "functionName": node.name,
                "signatureText": self._signatureTextFromNode(node),
                "parameters": self._parametersFromFunctionNode(node),
                "docString": ast.get_docstring(node) or "",
            }

    def _iterModuleFunctions(self):
        rootPath = self._normalizedRootPath()
        for filePath in self._iterPythonFiles(rootPath):
            try:
                moduleDisplayName, moduleImportName = self._moduleNamesFromPath(filePath, rootPath)
                functionSpecs = list(self._iterAstFunctions(filePath))
            except Exception as exc:
                self._writeLog("Skipped '{}': {}\n".format(filePath, str(exc)))
                continue

            if functionSpecs:
                yield moduleDisplayName, moduleImportName, filePath, sorted(functionSpecs, key=lambda x: x["functionName"].lower())

    def refreshTree(self):
        selectedKey = self.currentFunctionKey
        self.functionSpecsByKey = {}
        self.runtimeFunctionsByKey = {}
        discoveredKeys = set()
        expandedModules = self._rememberExpandedModules()
        moduleItemsByPath = {}

        filterText = self.filterEdit.text().strip().lower()
        self.treeWidget.clear()

        for moduleName, importName, filePath, functionSpecs in self._iterModuleFunctions():
            functionSpecs = self._filterFunctionItems(moduleName, functionSpecs, filterText)

            if not functionSpecs:
                continue

            moduleParts = [] if moduleName == "<root>" else moduleName.split(".")
            parentItem = self.treeWidget.invisibleRootItem()
            modulePath = []
            for part in moduleParts:
                modulePath.append(part)
                modulePathTuple = tuple(modulePath)
                moduleItem = moduleItemsByPath.get(modulePathTuple)
                if moduleItem is None:
                    moduleItem = QTreeWidgetItem([part, ""])
                    parentItem.addChild(moduleItem)
                    moduleItemsByPath[modulePathTuple] = moduleItem
                    if modulePathTuple in expandedModules:
                        moduleItem.setExpanded(True)
                parentItem = moduleItem

            for functionSpec in functionSpecs:
                functionKey = self._functionKey(filePath, functionSpec["functionName"])
                functionSpec["moduleName"] = moduleName
                functionSpec["moduleImportName"] = importName
                functionSpec["filePath"] = filePath
                self.functionSpecsByKey[functionKey] = functionSpec
                discoveredKeys.add(functionKey)

                fnItem = QTreeWidgetItem([functionSpec["functionName"]])
                fnItem.setData(0, Qt.UserRole, functionKey)
                parentItem.addChild(fnItem)

                if functionKey == selectedKey:
                    self.treeWidget.setCurrentItem(fnItem)

        self.treeWidget.resizeColumnToContents(0)
        self._pruneCachedUiModules(discoveredKeys)

    def _functionKey(self, filePath, functionName):
        return "{}::{}".format(os.path.normpath(filePath), functionName)

    def _loadRuntimeFunction(self, functionSpec):
        moduleImportName = functionSpec["moduleImportName"]
        if not moduleImportName:
            raise ImportError("Root '__init__.py' functions cannot be imported as a package module")

        rootPath = self._normalizedRootPath()
        if rootPath not in sys.path:
            sys.path.insert(0, rootPath)

        moduleObj = importlib.import_module(moduleImportName)
        functionObj = getattr(moduleObj, functionSpec["functionName"], None)
        if not callable(functionObj):
            raise AttributeError("Cannot find callable '{}' in module '{}'".format(functionSpec["functionName"], moduleImportName))
        return functionObj

    def _onTreeSelectionChanged(self):
        selectedItems = self.treeWidget.selectedItems()
        if not selectedItems:
            return

        item = selectedItems[0]
        functionKey = item.data(0, Qt.UserRole)
        if not functionKey:
            return

        self.currentFunctionKey = functionKey
        functionSpec = self.functionSpecsByKey.get(self.currentFunctionKey)
        if not functionSpec:
            return

        try:
            functionObj = self._getOrLoadRuntimeFunction(functionSpec)
        except Exception as exc:
            self._writeLog("Cannot load '{}': {}\n".format(functionSpec["functionName"], str(exc)))
            self._setFunctionInfoLabel(
                functionSpec,
                qualName=functionSpec.get("functionName", "callable"),
                notRunnableMessage=str(exc),
            )
            return

        moduleObj = self.modulesByFunctionKey.get(functionKey)
        if not moduleObj:
            moduleObj = self._buildModuleFromFunction(functionObj, functionSpec)
            self.modulesByFunctionKey[functionKey] = moduleObj

        self._showModule(functionObj, moduleObj, functionSpec)

    def _showModule(self, functionObj, moduleObj, functionSpec):
        qualName = getattr(functionObj, "__qualname__", getattr(functionObj, "__name__", "callable"))
        runtimeDocString = inspect.getdoc(functionObj) or functionSpec.get("docString", "")
        self._setFunctionInfoLabel(functionSpec, qualName=qualName, docString=runtimeDocString)

        moduleItem = _ModuleItemProxy(moduleObj)
        attrsWidget = AttributesWidget(
            moduleItem,
            moduleObj.attributes(),
            mainWindow=self.mainWindowProxy,
        )
        self.currentAttributesWidget = attrsWidget
        self.attrsScrollArea.setWidget(attrsWidget)

    def _buildModuleFromFunction(self, functionObj, functionSpec):
        moduleObj = Module()
        functionName = getattr(functionObj, "__name__", "callable")
        moduleObj.setName(functionName)

        signature = inspect.signature(functionObj)
        astParametersByName = {p["name"]: p for p in functionSpec.get("parameters", [])}
        for parameter in signature.parameters.values():
            attr = self._attributeFromParameter(parameter)
            astParam = astParametersByName.get(parameter.name)
            if astParam:
                annotationText = astParam.get("annotationText", "")
                if annotationText and parameter.annotation is inspect._empty:
                    data = attr.localData()
                    data["annotation"] = annotationText
                    attr.setLocalData(data)
            moduleObj.addAttribute(attr)
        return moduleObj

    def _attributeFromParameter(self, parameter):
        templateName, data = self._templateDataFromParameter(parameter)

        attr = Attribute()
        attr.setName(parameter.name)
        attr.setTemplate(templateName)
        attr.setCategory("General")
        attr.setData(data)
        return attr

    def _templateDataFromParameter(self, parameter):
        def genericLineEditAndButtonData(value):
            return {
                "value": value,
                "buttonCommand": "value = value",
                "buttonLabel": "(empty)",
                "default": "value",
            }

        annotation = parameter.annotation
        scalarAnnotations = {"bool": bool, "int": int, "float": float, "str": str}
        if annotation not in scalarAnnotations.values():
            annotationName = getattr(annotation, "__name__", "")
            annotation = scalarAnnotations.get(annotationName, annotation)

        defaultValue = None if parameter.default is inspect._empty else parameter.default
        hasDefault = parameter.default is not inspect._empty

        if parameter.kind == inspect.Parameter.VAR_POSITIONAL:
            return "json", {"data": [] if not hasDefault else list(defaultValue), "height": 140, "readonly": False, "default": "data"}
        if parameter.kind == inspect.Parameter.VAR_KEYWORD:
            return "json", {"data": {} if not hasDefault else dict(defaultValue), "height": 140, "readonly": False, "default": "data"}

        origin = typing.get_origin(annotation)
        args = typing.get_args(annotation)

        if inspect.isclass(annotation) and issubclass(annotation, enum.Enum):
            enumItems = [member.name for member in annotation]
            currentValue = defaultValue.name if isinstance(defaultValue, enum.Enum) else enumItems[0]
            return "comboBox", {"items": enumItems, "current": currentValue, "default": "current"}

        if origin is typing.Literal and args:
            items = list(args)
            currentValue = defaultValue if hasDefault else items[0]
            return "comboBox", {"items": items, "current": currentValue, "default": "current"}

        if annotation is bool:
            currentValue = bool(defaultValue) if hasDefault else False
            return "checkBox", {"checked": currentValue, "default": "checked"}

        if annotation in (list, dict):
            currentValue = defaultValue if hasDefault else ([] if annotation is list else {})
            return "json", {"data": currentValue, "height": 160, "readonly": False, "default": "data"}

        if annotation in (tuple, set):
            currentValue = list(defaultValue) if hasDefault else []
            return "json", {"data": currentValue, "height": 160, "readonly": False, "default": "data"}

        if annotation in (int, float):
            currentValue = defaultValue if hasDefault else 0
            return "lineEditAndButton", genericLineEditAndButtonData(currentValue)

        if annotation is str:
            currentValue = defaultValue if hasDefault else ""
            return "lineEditAndButton", genericLineEditAndButtonData(currentValue)

        if annotation is inspect._empty and hasDefault and isinstance(defaultValue, bool):
            return "checkBox", {"checked": defaultValue, "default": "checked"}
        if annotation is inspect._empty and hasDefault and isinstance(defaultValue, (dict, list)):
            return "json", {"data": defaultValue, "height": 160, "readonly": False, "default": "data"}

        currentValue = defaultValue if hasDefault else ""
        return "lineEditAndButton", genericLineEditAndButtonData(currentValue)

    def _coerceValue(self, value, parameter):
        annotation = parameter.annotation
        if annotation is inspect._empty:
            return value

        if value is None:
            return None

        origin = typing.get_origin(annotation)
        args = typing.get_args(annotation)

        if origin is typing.Union:
            for arg in args:
                if arg is type(None) and value is None:
                    return None
                try:
                    return self._coerceByType(value, arg)
                except Exception:
                    continue
            return value

        if origin is typing.Literal:
            if value in args:
                return value
            raise ValueError("Value '{}' is not in Literal{}".format(value, args))

        return self._coerceByType(value, annotation)

    def _coerceByType(self, value, annotation):
        if inspect.isclass(annotation) and issubclass(annotation, enum.Enum):
            if isinstance(value, annotation):
                return value
            return annotation[str(value)]

        if annotation is bool:
            return bool(value)
        if annotation is int:
            return int(value)
        if annotation is float:
            return float(value)
        if annotation is str:
            return str(value)
        if annotation is list:
            return list(value) if not isinstance(value, list) else value
        if annotation is tuple:
            return tuple(value)
        if annotation is set:
            return set(value)
        if annotation is dict:
            return dict(value) if not isinstance(value, dict) else value
        return value

    def _argsAndKwargsFromModule(self, functionObj, moduleObj):
        signature = inspect.signature(functionObj)
        attrByName = {attr.name(): attr for attr in moduleObj.attributes()}

        args = []
        kwargs = {}

        for parameter in signature.parameters.values():
            attr = attrByName.get(parameter.name)
            if not attr:
                continue

            rawValue = attr.get()
            value = self._coerceValue(rawValue, parameter)

            if parameter.kind in (inspect.Parameter.POSITIONAL_ONLY, inspect.Parameter.POSITIONAL_OR_KEYWORD):
                args.append(value)
            elif parameter.kind == inspect.Parameter.KEYWORD_ONLY:
                kwargs[parameter.name] = value
            elif parameter.kind == inspect.Parameter.VAR_POSITIONAL:
                args.extend(value)
            elif parameter.kind == inspect.Parameter.VAR_KEYWORD:
                kwargs.update(value)

        return args, kwargs

    def runSelectedFunction(self):
        if not self.currentFunctionKey:
            self._writeLog("No function selected.\n")
            return

        functionSpec = self.functionSpecsByKey.get(self.currentFunctionKey)
        functionObj = None
        if functionSpec:
            try:
                functionObj = self._getOrLoadRuntimeFunction(functionSpec)
            except Exception as exc:
                self._writeLog("Cannot run '{}': {}\n".format(functionSpec["functionName"], str(exc)))
                return

        moduleObj = self.modulesByFunctionKey.get(self.currentFunctionKey)
        if not functionObj or not moduleObj:
            self._writeLog("Selected function is unavailable.\n")
            return

        try:
            args, kwargs = self._argsAndKwargsFromModule(functionObj, moduleObj)
            result = functionObj(*args, **kwargs)
            signature = inspect.signature(functionObj)
            boundArgs = signature.bind_partial(*args, **kwargs)
            callArgs = []
            for parameterName, parameter in signature.parameters.items():
                if parameter.kind == inspect.Parameter.VAR_POSITIONAL:
                    for value in boundArgs.arguments.get(parameterName, ()):
                        callArgs.append(repr(value))
                    continue

                if parameter.kind == inspect.Parameter.VAR_KEYWORD:
                    extraKwargs = boundArgs.arguments.get(parameterName, {})
                    for key, value in extraKwargs.items():
                        callArgs.append("{}={}".format(key, repr(value)))
                    continue

                if parameterName not in boundArgs.arguments:
                    continue

                value = boundArgs.arguments[parameterName]
                shouldShowNamed = (
                    parameter.default is not inspect._empty
                    or parameter.kind == inspect.Parameter.KEYWORD_ONLY
                )
                if shouldShowNamed:
                    callArgs.append("{}={}".format(parameterName, repr(value)))
                else:
                    callArgs.append(repr(value))

            callText = "{}({})".format(functionObj.__name__, ", ".join(callArgs))
            self._writeLog("\n>>> {}\n".format(callText))
            self._writeLog("Result: {}\n".format(repr(result)))
        except Exception as exc:
            self._writeLog("\nERROR: {}\n".format(str(exc)))


def showFunctionBrowser():
    """Show singleton function-browser window."""
    existing = FunctionBrowserWindow.windowInstance
    if existing and existing.isVisible():
        existing.raise_()
        existing.activateWindow()
        return existing

    window = FunctionBrowserWindow(parent=rigBuilderUi.ParentWindow)
    FunctionBrowserWindow.windowInstance = window
    window.show()
    return window

