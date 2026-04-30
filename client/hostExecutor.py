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
        if not self._isRunning:
            QApplication.setOverrideCursor(Qt.WaitCursor)
            self._isRunning = True
        try:
            return func(self, *args, **kwargs)
        finally:
            if self._isRunning:
                QApplication.restoreOverrideCursor()
                self._isRunning = False
    return wrapper

class HostExecutor(QObject):
    onConnectionError = Signal(str)
    onPrint = Signal(str)
    onError = Signal(str, str)
    beginProgress = Signal(str, int)
    stepProgress = Signal(int, str)
    endProgress = Signal()

    def __init__(self):
        super().__init__()
        self._conn = None
        self._isRunning = False
        connectionManager.connectionChanged.connect(self._onConnectionChanged)

    def _onConnectionChanged(self, conn):
        if self._conn:
            self._conn.onPrint.disconnect(self.onPrint)
            self._conn.onError.disconnect(self.onError)
            self._conn.beginProgress.disconnect(self.beginProgress)
            self._conn.stepProgress.disconnect(self.stepProgress)
            self._conn.endProgress.disconnect(self.endProgress)
            self._conn.onConnectionLost.disconnect(self._onConnectionLost)
            if self._isRunning:
                QApplication.restoreOverrideCursor()
                self._isRunning = False

        self._conn = conn

        if conn:
            conn.onPrint.connect(self.onPrint)
            conn.onError.connect(self.onError)
            conn.beginProgress.connect(self.beginProgress)
            conn.stepProgress.connect(self.stepProgress)
            conn.endProgress.connect(self.endProgress)
            conn.onConnectionLost.connect(self._onConnectionLost)

    def _onConnectionLost(self, reason: str):
        if self._isRunning:
            QApplication.restoreOverrideCursor()
            self._isRunning = False

    @executionGate
    def executeCode(self, code: str) -> dict:
        """Execute a Python snippet on the host server with JSON-serializable context."""
        if not self._conn:
            self.onConnectionError.emit("No active connection")
            return {}
        reply = self._conn.executeCode(code, contextKey="global")
        if reply.get("ok"):
            return reply.get("context", {})
        return {}  # error already shown via streaming onError

    @executionGate
    def executeModuleCode(self, module: Module, code: str) -> Optional[Module]:
        """Execute a Python snippet on the host server against a module subtree."""
        if not self._conn:
            self.onConnectionError.emit("No active connection")
            return None
        reply = self._conn.executeModuleCode(module.toXml(), ".", code, contextKey="global")
        if reply.get("ok"):
            try:
                return Module.fromXml(ET.fromstring(reply["xml"]))
            except Exception as e:
                self.onError.emit(f"Failed to sync state from server: {e}", "")
        return None  # error already shown via streaming onError

    @executionGate
    def runModule(self, module: Module) -> Optional[Module]:
        """Run module on the host server."""
        if not self._conn:
            self.onConnectionError.emit("No active connection")
            return None
        reply = self._conn.runModule(module.toXml(), ".", contextKey="global")
        if reply.get("ok"):
            try:
                return Module.fromXml(ET.fromstring(reply["xml"]))
            except Exception as e:
                self.onError.emit(f"Failed to sync state from server: {e}", "")
        return None  # error already shown via streaming onError

hostExecutor = HostExecutor()
