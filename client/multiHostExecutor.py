from xml.etree import ElementTree as ET
from typing import Optional

from ..qt import QObject, Signal
from ..core import Module
from .connectionManager import connectionManager


class PipelineError(Exception):
    def __init__(self, server: str, path: str, message: str):
        location = f" '{path}'" if path else ""
        super().__init__(f"[{server}]{location}: {message}")
        self.server = server
        self.path = path


class MultiHostExecutor(QObject):
    onConnectionError = Signal(str)
    onPrint = Signal(str)
    onError = Signal(str, str)
    beginProgress = Signal(str, int)
    stepProgress = Signal(int, str)
    endProgress = Signal()

    def __init__(self):
        super().__init__()
        self._wiredClients: list = []
        self._pipelineHosts: list[str] = []
        self._stepCounter = 0

    def setPipelineHosts(self, serverNames: list[str]):
        self._pipelineHosts = list(serverNames)

    def executeModuleCode(self, module: Module, code: str) -> Optional[Module]:
        """Execute code against a module on its target host."""
        hostType = module.effectiveHost()
        if hostType:
            serverName = self._findServerName(hostType)
            if not serverName:
                self.onConnectionError.emit(f"No '{hostType}' server connected")
                return None
            conn = connectionManager.getOrConnect(serverName)
        else:
            conn = connectionManager.activeConnection()

        if not conn:
            self.onConnectionError.emit("No server connected")
            return None

        self._wireSignals(conn)
        try:
            reply = conn.executeModuleCode(module.toXml(), ".", code, contextKey="global")
        finally:
            self._unwireSignals()

        if reply and reply.get("ok"):
            try:
                return Module.fromXml(ET.fromstring(reply["xml"]))
            except Exception as e:
                self.onError.emit(f"Failed to sync state from server: {e}", "")
        return None

    def run(self, rootModule: Module) -> Module:
        """Execute rootModule's pipeline across multiple hosts.

        Flattens the module tree in DFS order, groups consecutive same-host modules
        into segments, then runs each segment as a single request via runModuleList.
        """
        workingRoot = rootModule.copy()
        segments = self._buildSegments(workingRoot)

        # Pre-connect all explicit-host servers and wire signals
        for hostType, _ in segments:
            if not hostType:
                continue
            serverName = self._findServerName(hostType)
            if not serverName:
                raise PipelineError(hostType, "", f"No pipeline host found for host type '{hostType}'")
            conn = connectionManager.getOrConnect(serverName)
            self._wireSignals(conn)

        count = self._countNonMuted(rootModule)
        self.beginProgress.emit(rootModule.name(), count)
        self._stepCounter = 0

        try:
            for hostType, modules in segments:
                serverName = self._findServerName(hostType) if hostType else connectionManager.activeServerName()
                if not serverName:
                    raise PipelineError(hostType or "?", "", "No server available for this segment")
                conn = connectionManager.getOrConnect(serverName)

                for module in modules:
                    self.stepProgress.emit(self._stepCounter, module.path())
                    self._stepCounter += 1

                paths = [m.path() for m in modules]
                reply = conn.runModuleList(workingRoot.toXml(), paths, contextKey="global")
                if not reply or not reply.get("ok"):
                    path = paths[0] if paths else "."
                    raise PipelineError(serverName, path, reply.get("error", "unknown error") if reply else "no reply")

                workingRoot = Module.fromXml(ET.fromstring(reply["xml"]))
        finally:
            self.endProgress.emit()
            self._unwireSignals()

        return workingRoot

    # ------------------------------------------------------------------
    # Segment planning
    # ------------------------------------------------------------------

    def _buildSegments(self, root: Module) -> list[tuple[str, list[Module]]]:
        """Flatten tree DFS, group consecutive same-host modules into segments."""
        segments: list[tuple[str, list[Module]]] = []
        for module in self._flatten(root):
            host = module.effectiveHost()
            if not segments or segments[-1][0] != host:
                segments.append((host, [module]))
            else:
                segments[-1][1].append(module)
        return segments

    def _flatten(self, module: Module) -> list[Module]:
        """DFS-ordered flat list of non-muted modules."""
        if module.muted():
            return []
        result = [module]
        for child in module.children():
            result.extend(self._flatten(child))
        return result

    # ------------------------------------------------------------------
    # Server resolution
    # ------------------------------------------------------------------

    def _findServerName(self, hostType: str) -> Optional[str]:
        """Resolve a host type to a server name using the pipeline host list."""
        candidates = []
        allServers = connectionManager.servers()

        if self._pipelineHosts:
            for name in self._pipelineHosts:
                entry = allServers.get(name)
                if entry and entry.get("host") == hostType:
                    candidates.append(name)
        else:
            for name, entry in allServers.items():
                if entry.get("host") == hostType:
                    candidates.append(name)
                    break

        if len(candidates) == 1:
            return candidates[0]
        if len(candidates) > 1:
            raise PipelineError(hostType, "", f"Multiple pipeline hosts of type '{hostType}' — uncheck all but one")
        return None

    # ------------------------------------------------------------------
    # Utilities
    # ------------------------------------------------------------------

    def _countNonMuted(self, module: Module) -> int:
        count = 0 if module.muted() else 1
        for child in module.children():
            count += self._countNonMuted(child)
        return count

    def _wireSignals(self, conn):
        if conn in self._wiredClients:
            return
        # The active connection is already forwarded by hostExecutor — skip to avoid doubling
        if conn is connectionManager.activeConnection():
            return
        conn.onPrint.connect(self.onPrint)
        conn.onError.connect(self.onError)
        conn.beginProgress.connect(self.beginProgress)
        conn.stepProgress.connect(self.stepProgress)
        conn.endProgress.connect(self.endProgress)
        self._wiredClients.append(conn)

    def _unwireSignals(self):
        for conn in self._wiredClients:
            try:
                conn.onPrint.disconnect(self.onPrint)
                conn.onError.disconnect(self.onError)
                conn.beginProgress.disconnect(self.beginProgress)
                conn.stepProgress.disconnect(self.stepProgress)
                conn.endProgress.disconnect(self.endProgress)
            except Exception:
                pass
        self._wiredClients.clear()


multiHostExecutor = MultiHostExecutor()
