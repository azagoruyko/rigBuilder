"""Module execution and code evaluation for the Rig Builder server."""

import io
import traceback

from ..core import Module, APIRegistry
from ..utils import captureOutput, jsonifyContext, getErrorStack, executeWithResult

# Persistent execution contexts for interactive (line-by-line) code execution.
# Keyed by a client-supplied contextKey so variables accumulate across calls.
_interactiveContexts = {}

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


def _emitError(emitFn, runId: str, msg: str, tb: str = "") -> dict:
    """Emit error + finished events and return a failure reply dict."""
    emitFn({"event": "error", "id": runId, "text": msg, "traceback": tb})
    return {"ok": False, "error": msg, "traceback": tb, "id": runId}


def _runWithModuleXml(moduleXml: str, modulePath: str, emitFn, runId: str, contextKey: str, actionFn) -> dict:
    """Parse moduleXml, find the target module, run actionFn(module, extraContext),
    persist the resulting context, serialize the root back to XML, and return a reply dict.

    *actionFn* receives (module, extraContext) and must return the updated context dict.
    """
    overrideAPI(emitFn, runId)

    try:
        root = Module.fromXml(moduleXml)
    except Exception as e:
        return _emitError(emitFn, runId, str(e), getErrorStack())

    module = root.findModuleByPath(modulePath)
    if not module:
        return _emitError(emitFn, runId, f"Module not found at path: {modulePath}")

    extraContext = _interactiveContexts.get(contextKey, {})
    capture = _StreamCapture(emitFn, runId)

    with captureOutput(capture):
        try:
            ctx = actionFn(module, extraContext)
        except Exception as e:
            return _emitError(emitFn, runId, str(e), getErrorStack())

    if contextKey:
        _interactiveContexts[contextKey] = ctx

    try:
        xmlOut = root.toXml()
    except Exception as e:
        return _emitError(emitFn, runId, "Failed to serialize root module to XML", getErrorStack())

    return {"ok": True, "xml": xmlOut, "id": runId}


def runModule(moduleXml: str, modulePath: str, emitFn, runId: str, contextKey: str = "") -> dict:
    """Deserialize the sent payload module XML, find module by modulePath, run it, and return updated XML."""
    def _action(module, extraContext):
        def runCallback(m: Module):
            emitFn({"event": "runCallback", "id": runId, "path": m.path()})
        return module.run(callback=runCallback, context=extraContext)

    return _runWithModuleXml(moduleXml, modulePath, emitFn, runId, contextKey, _action)


def executeModuleCode(moduleXml: str, modulePath: str, code: str, emitFn, runId: str, contextKey: str = "") -> dict:
    """Execute Python snippet within a module found by modulePath in the sent payload XML.
    Returns updated payload XML and any JSON context exposed by the module execution.

    When *contextKey* is non-empty the execution context is stored and reused
    across calls, allowing interactive line-by-line execution with accumulated
    variables.
    """
    def _action(module, extraContext):
        return module.executeCode(code, extraContext, executor=executeWithResult)

    return _runWithModuleXml(moduleXml, modulePath, emitFn, runId, contextKey, _action)


def executeCode(code: str, emitFn, runId: str, contextKey: str = "") -> dict:
    """Execute host-side Python code and return JSON-serializable context."""

    # Retrieve or create the accumulated interactive context.
    context = _interactiveContexts.get(contextKey, {})
    capture = _StreamCapture(emitFn, runId)

    with captureOutput(capture):
        try:
            result = executeWithResult(code, context)
            if result is not None:
                print(repr(result))
        except Exception as e:
            return _emitError(emitFn, runId, str(e), getErrorStack())

    # Store surviving user variables for the next interactive call.
    if contextKey:
        _interactiveContexts[contextKey] = context

    emitFn({"event": "finished", "id": runId})
    return {"ok": True, "context": jsonifyContext(context), "id": runId}
