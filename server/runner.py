"""Module execution and code evaluation for the Rig Builder server."""

import io
import traceback
import xml.etree.ElementTree as ET

from ..core import Module, APIRegistry
from ..utils import captureOutput, jsonifyContext, getErrorStack


class _StreamCapture(io.TextIOBase):
    """Captures stdout/stderr produced during module run or code execution
    and converts each line into a 'print' PUB event."""

    def __init__(self, emitFn, runId: str):
        self._emitFn = emitFn
        self._id = runId

    def write(self, text: str) -> int:
        if text.strip():
            self._emitFn({"event": "print", "id": self._id, "text": text.rstrip()})
        return len(text)

    def flush(self):
        pass


def overrideAPI(emitFn, runId):
    # Override progress functions to emit events via ZMQ
    def _beginProgress(text, count, updatePercent=0.01):
        emitFn({"event": "beginProgress", "id": runId, "text": text, "count": count})

    def _stepProgress(value, text=None):
        emitFn({"event": "stepProgress", "id": runId, "value": value, "text": text})

    def _endProgress():
        emitFn({"event": "endProgress", "id": runId})

    APIRegistry.override("beginProgress", _beginProgress)
    APIRegistry.override("stepProgress", _stepProgress)
    APIRegistry.override("endProgress", _endProgress)    


def runModule(moduleXml: str, modulePath: str, emitFn, runId: str) -> dict:
    """Deserialize the sent payload module XML, find module by modulePath, run it, and return updated XML."""
    
    overrideAPI(emitFn, runId)
    xmlOut = moduleXml

    try:
        root = Module.fromXml(ET.fromstring(moduleXml))  # payload root (sent by the client)
    except Exception as e:
        msg = str(e)
        tb = getErrorStack()
        emitFn({"event": "error", "id": runId, "text": msg, "traceback": tb})
        emitFn({"event": "finished", "id": runId})
        return {"ok": False, "error": msg, "traceback": tb, "id": runId}

    module = root.findModuleByPath(modulePath)
    if not module:
        msg = f"Module not found at path: {modulePath}"
        tb = ""
        emitFn({"event": "error", "id": runId, "text": msg, "traceback": tb})
        emitFn({"event": "finished", "id": runId})
        return {"ok": False, "error": msg, "traceback": tb, "id": runId}

    capture = _StreamCapture(emitFn, runId)

    with captureOutput(capture):
        def runCallback(m: Module):
            emitFn({"event": "runCallback", "id": runId, "path": m.path()})

        try:
            module.run(callback=runCallback)
        except Exception as e:
            msg = str(e)
            tb = getErrorStack()
            emitFn({"event": "error", "id": runId, "text": msg, "traceback": tb})
            emitFn({"event": "finished", "id": runId})
            return {"ok": False, "error": msg, "traceback": tb, "id": runId}

    try:
        xmlOut = root.toXml()
    except Exception as e:
        msg = "Failed to serialize root module to XML"
        tb = getErrorStack()
        emitFn({"event": "error", "id": runId, "text": msg, "traceback": tb})
        emitFn({"event": "finished", "id": runId})
        return {"ok": False, "error": msg, "traceback": tb, "id": runId}

    emitFn({"event": "finished", "id": runId})
    return {"ok": True, "xml": xmlOut, "id": runId}


def executeModuleCode(moduleXml: str, modulePath: str, code: str, emitFn, runId: str) -> dict:
    """Execute Python snippet within a module found by modulePath in the sent payload XML.
    Returns updated payload XML and (for executeCode) any JSON context exposed by the module execution.
    """

    overrideAPI(emitFn, runId)
    xmlOut = moduleXml

    try:
        root = Module.fromXml(ET.fromstring(moduleXml))
    except Exception as e:
        msg = str(e)
        tb = getErrorStack()
        emitFn({"event": "error", "id": runId, "text": msg, "traceback": tb})
        emitFn({"event": "finished", "id": runId})
        return {"ok": False, "error": msg, "traceback": tb, "id": runId}

    module = root.findModuleByPath(modulePath)
    if not module:
        msg = f"Module not found at path: {modulePath}"
        tb = ""
        emitFn({"event": "error", "id": runId, "text": msg, "traceback": tb})
        emitFn({"event": "finished", "id": runId})
        return {"ok": False, "error": msg, "traceback": tb, "id": runId}

    capture = _StreamCapture(emitFn, runId)

    with captureOutput(capture):
        try:
            module.executeCode(code)
        except Exception as e:
            msg = str(e)
            tb = getErrorStack()
            emitFn({"event": "error", "id": runId, "text": msg, "traceback": tb})
            emitFn({"event": "finished", "id": runId})
            return {"ok": False, "error": msg, "traceback": tb, "id": runId}

    try:
        xmlOut = root.toXml()
    except Exception as e:
        msg = "Failed to serialize root module to XML"
        tb = getErrorStack()
        emitFn({"event": "error", "id": runId, "text": msg, "traceback": tb})
        emitFn({"event": "finished", "id": runId})
        return {"ok": False, "error": msg, "traceback": tb, "id": runId}

    emitFn({"event": "finished", "id": runId})
    return {"ok": True, "xml": xmlOut, "id": runId}


def executeCode(code: str, emitFn, runId: str) -> dict:
    """Execute host-side Python code and return JSON-serializable context."""

    context = {}
    capture = _StreamCapture(emitFn, runId)

    with captureOutput(capture):
        try:
            exec(code, context)
        except Exception as e:
            msg = str(e)
            tb = getErrorStack()
            emitFn({"event": "error", "id": runId, "text": msg, "traceback": tb})
            emitFn({"event": "finished", "id": runId})
            return {"ok": False, "error": msg, "traceback": tb, "id": runId}

    emitFn({"event": "finished", "id": runId})
    return {"ok": True, "context": jsonifyContext(context), "id": runId}
