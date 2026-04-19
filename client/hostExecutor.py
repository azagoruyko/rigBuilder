from ..client.connectionManager import connectionManager
from typing import Optional
from ..qt import QObject, Signal, QApplication, Qt
from ..core import Module
from xml.etree import ElementTree as ET
import functools

def executionGate(func):
    """Decorator to ensure cursor is always restored after execution."""
    @functools.wraps(func)
    def wrapper(self, *args, **kwargs):
        # Start Run (Latching)
        if not self._isRunning:
            QApplication.setOverrideCursor(Qt.WaitCursor)
            self._isRunning = True
        
        try:
            return func(self, *args, **kwargs)
        finally:
            # Stop Run (Latching)
            if self._isRunning:
                QApplication.restoreOverrideCursor()
                self._isRunning = False
    return wrapper

class HostExecutor(QObject):
    onConnectionError = Signal(str)
    onPrint = Signal(str)
    onError = Signal(str, str)
    onRunCallback = Signal(str)
    beginProgress = Signal(str, int)
    stepProgress = Signal(int, str)
    endProgress = Signal()

    def __init__(self):
        super().__init__()
        self._boundConnection = None
        self._isRunning = False

    def _ensureBoundConnection(self, conn):
        if self._boundConnection is conn:
            return

        if self._boundConnection:
            try:
                self._boundConnection.onPrint.disconnect(self._handlePrint)
                self._boundConnection.onRunCallback.disconnect(self._handleRunCallback)
                self._boundConnection.beginProgress.disconnect(self._handleBeginProgress)
                self._boundConnection.stepProgress.disconnect(self._handleStepProgress)
                self._boundConnection.endProgress.disconnect(self._handleEndProgress)
                self._boundConnection.onConnectionLost.disconnect(self._handleConnectionLost)
            except (RuntimeError, TypeError):
                pass

        self._boundConnection = conn
        conn.onPrint.connect(self._handlePrint)
        conn.onRunCallback.connect(self._handleRunCallback)
        conn.beginProgress.connect(self._handleBeginProgress)
        conn.stepProgress.connect(self._handleStepProgress)
        conn.endProgress.connect(self._handleEndProgress)
        conn.onConnectionLost.connect(self._handleConnectionLost)

    def _handlePrint(self, text: str):
        self.onPrint.emit(text)

    def _handleRunCallback(self, path: str):
        self.onRunCallback.emit(path)

    def _handleBeginProgress(self, text: str, count: int):
        self.beginProgress.emit(text, count)

    def _handleStepProgress(self, value: int, text: str):
        self.stepProgress.emit(value, text)

    def _handleEndProgress(self):
        self.endProgress.emit()

    def _handleConnectionLost(self, reason: str):
        if self._isRunning:
            QApplication.restoreOverrideCursor()
            self._isRunning = False

    @executionGate
    def executeCode(self, code: str) -> dict:
        """Execute a Python snippet on the host server with JSON-serializable context."""
        conn = connectionManager.activeConnection()
        if not conn:
            self.onConnectionError.emit("No active connection")
            return {}

        contextKey = "global"

        self._ensureBoundConnection(conn)
        reply = conn.executeCode(code, contextKey=contextKey)

        if reply:
            if reply.get("ok"):
                return reply.get("context", {})
            else:
                self.onError.emit(reply.get("error", "Error executing code"), reply.get("traceback", ""))
        else:
            self.onError.emit("Error executing code: empty response", "")
        
        return {}

    @executionGate
    def executeModuleCode(self, module: Module, code: str) -> Optional[Module]:
        """Execute a Python snippet on the host server against a module subtree."""
        conn = connectionManager.activeConnection()
        if not conn:
            self.onConnectionError.emit("No active connection")
            return

        self._ensureBoundConnection(conn)
        
        moduleXml = module.toXml()
        contextKey = "global"

        reply = conn.executeModuleCode(moduleXml, ".", code, contextKey=contextKey)

        if reply:
            if reply.get("ok"):
                xmlOut = reply["xml"]
                try:
                    return Module.fromXml(ET.fromstring(xmlOut))
                except Exception as e:
                    self.onError.emit(f"Failed to sync state from server: {e}", "")
            else:
                self.onError.emit(reply.get("error", "Error executing module code"), reply.get("traceback", ""))
        else:
            self.onError.emit("Error executing module code: empty response", "")

    @executionGate
    def runModule(self, module: Module) -> Optional[Module]:
        """Run module on the host server."""
        conn = connectionManager.activeConnection()
        if not conn:
            self.onConnectionError.emit("No active connection")
            return

        contextKey = "global"

        self._ensureBoundConnection(conn)
        moduleXml = module.toXml()
        reply = conn.runModule(moduleXml, ".", contextKey=contextKey)

        if reply:
            if reply.get("ok"):
                xmlOut = reply.get("xml")
                if xmlOut:
                    try:
                        return Module.fromXml(ET.fromstring(xmlOut))
                    except Exception as e:
                        self.onError.emit(f"Failed to sync state from server: {e}", "")
                else:
                    self.onError.emit("Failed to sync state from server: empty response", "")
            else:
                self.onError.emit(reply.get("error", "Error running module"), reply.get("traceback", ""))

hostExecutor = HostExecutor()
