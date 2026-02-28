"""Headless inference utilities for Rig Builder function-to-module mapping.

This module keeps parsing and inference logic independent from UI code so it
can be reused by Function Browser and MCP server tools.
"""

from __future__ import annotations

import ast
import enum
import inspect
import typing

from .core import Attribute
from .core import Module


def signatureTextFromNode(functionNode):
    """Return textual function signature from an AST function node."""
    try:
        argsText = ast.unparse(functionNode.args)
    except Exception:
        argsText = "..."
    return "({})".format(argsText)


def _safeLiteralEval(node):
    if node is None:
        return False, None
    try:
        return True, ast.literal_eval(node)
    except Exception:
        return False, None


def parametersFromFunctionNode(functionNode):
    """Extract ordered parameter metadata from an AST function node."""
    argsObj = functionNode.args
    parameters = []

    def parameterSpec(argName, kind, annotationNode=None, defaultNode=None):
        hasLiteralDefault, literalDefaultValue = _safeLiteralEval(defaultNode)
        return {
            "name": argName,
            "kind": kind,
            "annotationText": ast.unparse(annotationNode) if annotationNode else "",
            "hasDefault": defaultNode is not None,
            "defaultText": ast.unparse(defaultNode) if defaultNode is not None else "",
            "defaultValue": literalDefaultValue if hasLiteralDefault else None,
            "hasLiteralDefault": hasLiteralDefault,
        }

    positionalNodes = list(argsObj.posonlyargs) + list(argsObj.args)
    defaults = list(argsObj.defaults)
    firstDefaultIndex = len(positionalNodes) - len(defaults)

    for index, argNode in enumerate(positionalNodes):
        defaultNode = None
        if index >= firstDefaultIndex and defaults:
            defaultNode = defaults[index - firstDefaultIndex]
        kind = (
            inspect.Parameter.POSITIONAL_ONLY
            if index < len(argsObj.posonlyargs)
            else inspect.Parameter.POSITIONAL_OR_KEYWORD
        )
        parameters.append(parameterSpec(argNode.arg, kind, argNode.annotation, defaultNode))

    if argsObj.vararg:
        parameters.append(
            parameterSpec(
                argsObj.vararg.arg,
                inspect.Parameter.VAR_POSITIONAL,
                argsObj.vararg.annotation,
                None,
            )
        )

    for kwIndex, kwArgNode in enumerate(argsObj.kwonlyargs):
        defaultNode = argsObj.kw_defaults[kwIndex]
        parameters.append(
            parameterSpec(
                kwArgNode.arg,
                inspect.Parameter.KEYWORD_ONLY,
                kwArgNode.annotation,
                defaultNode,
            )
        )

    if argsObj.kwarg:
        parameters.append(
            parameterSpec(
                argsObj.kwarg.arg,
                inspect.Parameter.VAR_KEYWORD,
                argsObj.kwarg.annotation,
                None,
            )
        )

    return parameters


def functionSpecFromNode(functionNode):
    """Create function spec dict from AST FunctionDef/AsyncFunctionDef node."""
    return {
        "functionName": functionNode.name,
        "signatureText": signatureTextFromNode(functionNode),
        "parameters": parametersFromFunctionNode(functionNode),
        "docString": ast.get_docstring(functionNode) or "",
        "isAsync": isinstance(functionNode, ast.AsyncFunctionDef),
    }


def parseFunctionsFromSource(sourceCode, *, includePrivate=False, filePath="<string>"):
    """Parse top-level function specs from Python source code."""
    moduleNode = ast.parse(sourceCode, filename=filePath)
    functionSpecs = []
    for node in moduleNode.body:
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        if not includePrivate and node.name.startswith("_"):
            continue
        functionSpecs.append(functionSpecFromNode(node))
    return functionSpecs


def parseFunctionsFromFile(filePath, *, includePrivate=False):
    """Parse top-level function specs from a Python file."""
    with open(filePath, "r", encoding="utf-8") as fileObj:
        sourceCode = fileObj.read()
    return parseFunctionsFromSource(sourceCode, includePrivate=includePrivate, filePath=filePath)


def _lineEditAndButtonData(value):
    return {
        "value": value,
        "buttonCommand": "",
        "buttonLabel": "<",
        "buttonEnabled": False,
        "default": "value",
    }


def _listBoxData(items):
    return {"items": list(items), "selected": [], "default": "items"}


def _jsonData(value):
    return {"data": value, "height": 160, "readonly": False, "default": "data"}


def _annotationFromRuntime(annotation):
    if annotation is inspect._empty:
        return annotation
    if isinstance(annotation, str):
        lookup = {
            "bool": bool,
            "int": int,
            "float": float,
            "str": str,
            "list": list,
            "dict": dict,
            "tuple": tuple,
            "set": set,
        }
        lowered = annotation.strip().lower()
        return lookup.get(lowered, annotation)

    scalarAnnotations = {"bool": bool, "int": int, "float": float, "str": str}
    if annotation not in scalarAnnotations.values():
        annotationName = getattr(annotation, "__name__", "")
        annotation = scalarAnnotations.get(annotationName, annotation)
    return annotation


def inferTemplateDataFromParameter(parameter):
    """Infer Rig Builder template + data from inspect.Parameter."""
    annotation = _annotationFromRuntime(parameter.annotation)
    defaultValue = None if parameter.default is inspect._empty else parameter.default
    hasDefault = parameter.default is not inspect._empty

    if parameter.kind == inspect.Parameter.VAR_POSITIONAL:
        return "listBox", _listBoxData([] if not hasDefault else defaultValue)
    if parameter.kind == inspect.Parameter.VAR_KEYWORD:
        return "json", _jsonData({} if not hasDefault else dict(defaultValue))

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

    if annotation is list:
        currentValue = defaultValue if hasDefault else []
        return "listBox", _listBoxData(currentValue)

    if annotation is dict:
        currentValue = defaultValue if hasDefault else {}
        return "json", _jsonData(currentValue)

    if annotation in (tuple, set):
        currentValue = list(defaultValue) if hasDefault else []
        return "listBox", _listBoxData(currentValue)

    if annotation in (int, float):
        currentValue = defaultValue if hasDefault else 0
        return "lineEditAndButton", _lineEditAndButtonData(currentValue)

    if annotation is str:
        currentValue = defaultValue if hasDefault else ""
        return "lineEditAndButton", _lineEditAndButtonData(currentValue)

    if annotation is inspect._empty and hasDefault and isinstance(defaultValue, bool):
        return "checkBox", {"checked": defaultValue, "default": "checked"}
    if annotation is inspect._empty and hasDefault and isinstance(defaultValue, list):
        return "listBox", _listBoxData(defaultValue)
    if annotation is inspect._empty and hasDefault and isinstance(defaultValue, dict):
        return "json", _jsonData(defaultValue)
    if annotation is inspect._empty and hasDefault and isinstance(defaultValue, (tuple, set)):
        return "listBox", _listBoxData(list(defaultValue))

    currentValue = defaultValue if hasDefault else ""
    return "lineEditAndButton", _lineEditAndButtonData(currentValue)


def _literalItemsFromAnnotationText(annotationText):
    try:
        node = ast.parse(annotationText, mode="eval").body
    except Exception:
        return []

    if not isinstance(node, ast.Subscript):
        return []

    targetName = ""
    if isinstance(node.value, ast.Name):
        targetName = node.value.id
    elif isinstance(node.value, ast.Attribute):
        targetName = node.value.attr
    if targetName != "Literal":
        return []

    sliceNode = node.slice
    tupleNode = sliceNode if isinstance(sliceNode, ast.Tuple) else ast.Tuple(elts=[sliceNode], ctx=ast.Load())
    items = []
    for itemNode in tupleNode.elts:
        ok, value = _safeLiteralEval(itemNode)
        if ok:
            items.append(value)
    return items


def _annotationTypeFromText(annotationText):
    if not annotationText:
        return ""
    compact = annotationText.replace(" ", "")
    lowered = compact.lower()

    if lowered in ("bool", "builtins.bool"):
        return "bool"
    if lowered in ("int", "builtins.int"):
        return "int"
    if lowered in ("float", "builtins.float"):
        return "float"
    if lowered in ("str", "builtins.str"):
        return "str"
    if lowered.startswith(("list[", "typing.list[")) or lowered in ("list", "typing.list"):
        return "list"
    if lowered.startswith(("dict[", "typing.dict[")) or lowered in ("dict", "typing.dict"):
        return "dict"
    if lowered.startswith(("tuple[", "typing.tuple[")) or lowered in ("tuple", "typing.tuple"):
        return "tuple"
    if lowered.startswith(("set[", "typing.set[")) or lowered in ("set", "typing.set"):
        return "set"
    if "literal[" in lowered:
        return "literal"
    return ""


def inferTemplateDataFromParameterSpec(parameterSpec):
    """Infer Rig Builder template + data from AST parameter spec."""
    kind = parameterSpec["kind"]
    hasDefault = parameterSpec.get("hasLiteralDefault", False)
    defaultValue = parameterSpec.get("defaultValue")
    annotationText = parameterSpec.get("annotationText", "")
    annotationType = _annotationTypeFromText(annotationText)

    if kind == inspect.Parameter.VAR_POSITIONAL:
        return "listBox", _listBoxData([] if not hasDefault else defaultValue)
    if kind == inspect.Parameter.VAR_KEYWORD:
        return "json", _jsonData({} if not hasDefault else defaultValue)

    if annotationType == "literal":
        items = _literalItemsFromAnnotationText(annotationText)
        if items:
            currentValue = defaultValue if hasDefault and defaultValue in items else items[0]
            return "comboBox", {"items": items, "current": currentValue, "default": "current"}

    if annotationType == "bool":
        currentValue = bool(defaultValue) if hasDefault else False
        return "checkBox", {"checked": currentValue, "default": "checked"}

    if annotationType == "list":
        currentValue = defaultValue if hasDefault and isinstance(defaultValue, list) else []
        return "listBox", _listBoxData(currentValue)

    if annotationType == "dict":
        currentValue = defaultValue if hasDefault and isinstance(defaultValue, dict) else {}
        return "json", _jsonData(currentValue)

    if annotationType in ("tuple", "set"):
        currentValue = list(defaultValue) if hasDefault and isinstance(defaultValue, (tuple, set, list)) else []
        return "listBox", _listBoxData(currentValue)

    if annotationType in ("int", "float"):
        currentValue = defaultValue if hasDefault else 0
        return "lineEditAndButton", _lineEditAndButtonData(currentValue)

    if annotationType == "str":
        currentValue = defaultValue if hasDefault else ""
        return "lineEditAndButton", _lineEditAndButtonData(currentValue)

    if hasDefault and isinstance(defaultValue, bool):
        return "checkBox", {"checked": defaultValue, "default": "checked"}
    if hasDefault and isinstance(defaultValue, list):
        return "listBox", _listBoxData(defaultValue)
    if hasDefault and isinstance(defaultValue, dict):
        return "json", _jsonData(defaultValue)
    if hasDefault and isinstance(defaultValue, (tuple, set)):
        return "listBox", _listBoxData(list(defaultValue))

    return "lineEditAndButton", _lineEditAndButtonData(defaultValue if hasDefault else "")


def attributeFromParameter(parameter, *, category="General"):
    """Build Attribute instance from inspect.Parameter."""
    templateName, data = inferTemplateDataFromParameter(parameter)
    attr = Attribute()
    attr.setName(parameter.name)
    attr.setTemplate(templateName)
    attr.setCategory(category)
    attr.setData(data)
    return attr


def attributeFromParameterSpec(parameterSpec, *, category="General"):
    """Build Attribute instance from AST-derived parameter spec."""
    templateName, data = inferTemplateDataFromParameterSpec(parameterSpec)
    attr = Attribute()
    attr.setName(parameterSpec["name"])
    attr.setTemplate(templateName)
    attr.setCategory(category)
    attr.setData(data)

    annotationText = parameterSpec.get("annotationText", "")
    if annotationText:
        localData = attr.localData()
        localData["annotation"] = annotationText
        attr.setLocalData(localData)
    return attr


def buildModuleFromFunction(functionObj, *, functionSpec=None, category="General"):
    """Create a Rig Builder Module from runtime callable signature."""
    moduleObj = Module()
    moduleObj.setName(getattr(functionObj, "__name__", "callable"))

    signature = inspect.signature(functionObj)
    astParametersByName = {p["name"]: p for p in (functionSpec or {}).get("parameters", [])}
    for parameter in signature.parameters.values():
        attr = attributeFromParameter(parameter, category=category)
        astParam = astParametersByName.get(parameter.name)
        if astParam:
            annotationText = astParam.get("annotationText", "")
            if annotationText and parameter.annotation is inspect._empty:
                localData = attr.localData()
                localData["annotation"] = annotationText
                attr.setLocalData(localData)
        moduleObj.addAttribute(attr)
    return moduleObj


def buildModuleFromFunctionSpec(functionSpec, *, category="General"):
    """Create a Rig Builder Module from AST-derived function spec."""
    moduleObj = Module()
    moduleObj.setName(functionSpec.get("functionName", "callable"))
    for parameterSpec in functionSpec.get("parameters", []):
        moduleObj.addAttribute(attributeFromParameterSpec(parameterSpec, category=category))
    return moduleObj


def buildModuleFromSource(sourceCode, functionName, *, includePrivate=False, category="General", filePath="<string>"):
    """Parse source code and create module for target function name."""
    functionSpecs = parseFunctionsFromSource(sourceCode, includePrivate=includePrivate, filePath=filePath)
    for functionSpec in functionSpecs:
        if functionSpec.get("functionName") == functionName:
            return buildModuleFromFunctionSpec(functionSpec, category=category), functionSpec
    raise ValueError("Function '{}' was not found in provided source".format(functionName))


__all__ = [
    "attributeFromParameter",
    "attributeFromParameterSpec",
    "buildModuleFromFunction",
    "buildModuleFromFunctionSpec",
    "buildModuleFromSource",
    "functionSpecFromNode",
    "inferTemplateDataFromParameter",
    "inferTemplateDataFromParameterSpec",
    "parametersFromFunctionNode",
    "parseFunctionsFromFile",
    "parseFunctionsFromSource",
    "signatureTextFromNode",
]
