from ..client.connectionManager import connectionManager
from typing import Optional
from ..qt import QObject, Signal
from ..core import Module
from xml.etree import ElementTree as ET


class HostExecutor(QObject):
    onConnectionError = Signal(str)
    onPrint = Signal(str)
    onError = Signal(str, str)
    onFinished = Signal()
    onRunCallback = Signal(str)
    beginProgress = Signal(str, int)
    stepProgress = Signal(int, str)
    endProgress = Signal()

    def __init__(self):
        super().__init__()

    def executeCode(self, code: str) -> dict:
        """Execute a Python snippet on the host server with JSON-serializable context."""

        conn = connectionManager.activeConnection()
        if not conn:
            self.onConnectionError.emit("No active connection")
            return {}

        def onFinished():
            try:
                conn.onPrint.disconnect(self.onPrint.emit)
                conn.onError.disconnect(self.onError.emit)
                conn.onFinished.disconnect(onFinished)
            except (RuntimeError, TypeError):
                pass
            self.onFinished.emit()

        conn.onPrint.connect(self.onPrint.emit)
        conn.onError.connect(self.onError.emit)
        conn.onFinished.connect(onFinished)
        
        reply = conn.executeCode(code)
        return reply.get("context", {}) if reply and reply.get("ok") else {}

    def executeModuleCode(self, module: Module, code: str) -> Optional[Module]:
        """Execute a Python snippet on the host server against a module subtree."""

        conn = connectionManager.activeConnection()
        if not conn:
            self.onConnectionError.emit("No active connection")
            return

        def onFinished():
            try:
                conn.onPrint.disconnect(self.onPrint.emit)
                conn.onError.disconnect(self.onError.emit)
                conn.onFinished.disconnect(onFinished)
            except (RuntimeError, TypeError):
                pass

            self.onFinished.emit()

        conn.onPrint.connect(self.onPrint.emit)
        conn.onError.connect(self.onError.emit)
        conn.onFinished.connect(onFinished)

        moduleXml = module.toXml()
        modulePath = "."

        reply = conn.executeModuleCode(moduleXml, modulePath, code)
        
        if reply and reply.get("ok"):
            xmlOut = reply["xml"]
            try:
                return Module.fromXml(ET.fromstring(xmlOut))
            except Exception as e:
                self.onError.emit(f"Failed to sync state from server: {e}", "")

    def runModule(self, module: Module) -> Optional[Module]:
        """Run module on the host server."""
        conn = connectionManager.activeConnection()
        if not conn:
            self.onConnectionError.emit("No active connection")
            return

        def onFinished():
            try:
                conn.onError.disconnect(self.onError.emit)
                conn.onPrint.disconnect(self.onPrint.emit)
                conn.onRunCallback.disconnect(self.onRunCallback.emit)
                conn.beginProgress.disconnect(self.beginProgress.emit)
                conn.stepProgress.disconnect(self.stepProgress.emit)
                conn.endProgress.disconnect(self.endProgress.emit)
                conn.onFinished.disconnect(onFinished)
            except (RuntimeError, TypeError):
                pass

            self.onFinished.emit()

        conn.onError.connect(self.onError.emit)
        conn.onPrint.connect(self.onPrint.emit)
        conn.onRunCallback.connect(self.onRunCallback.emit)
        conn.beginProgress.connect(self.beginProgress.emit)
        conn.stepProgress.connect(self.stepProgress.emit)
        conn.endProgress.connect(self.endProgress.emit)
        conn.onFinished.connect(onFinished)

        moduleXml = module.toXml()
        
        reply = conn.runModule(moduleXml, ".")

        if reply and reply.get("ok"):
            xmlOut = reply.get("xml")
            if xmlOut:
                try:
                    return Module.fromXml(ET.fromstring(xmlOut))
                except Exception as e:
                    self.onError.emit(f"Could not sync module state: {e}", "")

hostExecutor = HostExecutor()

