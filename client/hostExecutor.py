from ..client.connectionManager import connectionManager
from typing import Optional
from ..qt import QObject, Signal
from ..core import Module
from xml.etree import ElementTree as ET


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

    def executeCode(self, code: str) -> dict:
        """Execute a Python snippet on the host server with JSON-serializable context."""

        conn = connectionManager.activeConnection()
        if not conn:
            self.onConnectionError.emit("No active connection")
            return {}

        def onError(text: str, tb: str):
            self.onError.emit(text, tb)            

        conn.onPrint.connect(self.onPrint.emit)
        conn.onError.connect(onError)
        
        try:
            reply = conn.executeCode(code)
            return reply.get("context", {}) if reply and reply.get("ok") else {}
        finally:
            try:
                conn.onPrint.disconnect(self.onPrint.emit)
                conn.onError.disconnect(onError)
            except (RuntimeError, TypeError):
                pass

    def executeModuleCode(self, module: Module, code: str) -> Optional[Module]:
        """Execute a Python snippet on the host server against a module subtree."""

        conn = connectionManager.activeConnection()
        if not conn:
            self.onConnectionError.emit("No active connection")
            return

        def onError(text: str, tb: str):
            self.onError.emit(text, tb)            

        conn.onPrint.connect(self.onPrint.emit)
        conn.onError.connect(onError)

        # Send only the selected module subtree so modules stay independent.
        # On the host, modulePath="." refers to the payload root.
        moduleXml = module.toXml()
        modulePath = "."

        try:
            reply = conn.executeModuleCode(moduleXml, modulePath, code)
            
            if reply and reply.get("ok"):
                xmlOut = reply["xml"]
                try:
                    return Module.fromXml(ET.fromstring(xmlOut))
                except Exception as e:
                    self.onError.emit(f"Failed to sync state from server: {e}", "")
        finally:
            try:
                conn.onPrint.disconnect(self.onPrint.emit)
                conn.onError.disconnect(onError)
            except (RuntimeError, TypeError):
                pass

    def runModule(self, module: Module) -> Optional[Module]:
        """Run module on the host server."""
        conn = connectionManager.activeConnection()
        if not conn:
            self.onConnectionError.emit("No active connection")
            return

        def onError(text: str, tb: str):
            self.onError.emit(text, tb)

        conn.onError.connect(onError)
        conn.onPrint.connect(self.onPrint.emit)
        conn.onRunCallback.connect(self.onRunCallback.emit)
        conn.beginProgress.connect(self.beginProgress.emit)
        conn.stepProgress.connect(self.stepProgress.emit)
        conn.endProgress.connect(self.endProgress.emit)

        # Send only the selected module subtree so modules stay independent.
        # On the host, modulePath="." refers to the payload root.
        moduleXml = module.toXml()
        
        try:
            reply = conn.runModule(moduleXml, ".")

            if reply and reply.get("ok"):
                xmlOut = reply.get("xml")
                if xmlOut:
                    try:
                        return Module.fromXml(ET.fromstring(xmlOut))
                    except Exception as e:
                        self.onError.emit(f"Could not sync module state: {e}", "")
        finally:
            try:
                conn.onError.disconnect(onError)
                conn.onPrint.disconnect(self.onPrint.emit)
                conn.onRunCallback.disconnect(self.onRunCallback.emit)
                conn.beginProgress.disconnect(self.beginProgress.emit)
                conn.stepProgress.disconnect(self.stepProgress.emit)
                conn.endProgress.disconnect(self.endProgress.emit)
            except (RuntimeError, TypeError):
                pass

hostExecutor = HostExecutor()

