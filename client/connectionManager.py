import json
import os
import logging
import threading
import time
import zmq
from typing import Optional

from .. import settings
from . import HostClient
from ..utils import loadJson, saveJson
from ..server.hosts.standalone import StandaloneServer
from ..server.hosts import REGISTRATION_INTERVAL_SEC
from ..qt import QObject, Signal

HOSTS_FILE = os.path.join(settings.RIG_BUILDER_USER_PATH, "hosts.json")
DEFAULT_DISCOVERY_PORT = 51605

logger = logging.getLogger('rigBuilder')

class DiscoveryServer(QObject):
    """Listens for registration messages from host servers on a fixed port."""
    hostDiscovered = Signal()

    def __init__(self, port: int, parent=None):
        super().__init__(parent)
        self._port = port
        self._running = False
        self._thread = None
        self._discoveredHosts = {} # (address, cmdPort) -> entry

    def start(self):
        if self._running:
            return
        self._running = True
        self._thread = threading.Thread(target=self._loop, daemon=True, name="DiscoveryServer")
        self._thread.start()

    def stop(self):
        self._running = False
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=2.0)
        # The thread will exit on next receive or context destroy

    def discoveredHosts(self) -> dict:
        return self._discoveredHosts

    def _loop(self):
        # PULL socket — hosts fire-and-forget via PUSH; no reply needed.
        # This avoids the strict alternation constraint of REQ/REP.
        ctx = zmq.Context.instance()
        socket = ctx.socket(zmq.PULL)
        socket.setsockopt(zmq.LINGER, 0)
        try:
            socket.bind(f"tcp://*:{self._port}")
            logger.info(f"Discovery server listening on port {self._port}")
        except Exception as e:
            logger.error(f"Failed to bind discovery server to port {self._port}: {e}")
            self._running = False
            socket.close(linger=0)
            return

        lastHeartbeat = time.time()

        while self._running:
            if socket.poll(timeout=500):
                try:
                    msg = json.loads(socket.recv_string())
                    cmd = msg.get("cmd")
                    if cmd == "register":
                        host = msg.get("host", "unknown")
                        cmdPort = msg.get("cmdPort")
                        eventPort = msg.get("eventPort")
                        name = msg.get("name", f"{host.capitalize()}")

                        entry = {
                            "host": host,
                            "cmdPort": cmdPort,
                            "eventPort": eventPort,
                            "name": name,
                            "discovered": True,
                            "lastSeen": time.time()
                        }
                        
                        key = cmdPort
                        isNew = key not in self._discoveredHosts
                        self._discoveredHosts[key] = entry

                        if isNew:
                            self.hostDiscovered.emit()
                    else:
                        logger.warning(f"Discovery: unknown command {cmd!r}")
                except Exception as e:
                    logger.error(f"Error in discovery server: {e}")
            
            # Heartbeat check every 2 seconds
            now = time.time()
            if now - lastHeartbeat > 2.0:
                lastHeartbeat = now
                self._checkHeartbeat()
        
        socket.close(linger=0)

    def _checkHeartbeat(self):
        if not self._discoveredHosts:
            return
            
        now = time.time()
        deadHosts = []
        
        # Hosts re-register every REGISTRATION_INTERVAL_SEC. Mark as dead after 3 missed intervals.
        timeout = REGISTRATION_INTERVAL_SEC * 3
        
        for key, entry in list(self._discoveredHosts.items()):
            elapsed = now - entry.get("lastSeen", 0)
            if elapsed > timeout:
                deadHosts.append((key, elapsed))
                
        if deadHosts:
            for key, elapsed in deadHosts:
                entry = self._discoveredHosts.pop(key)
                logger.info(f"Host disconnected (no registration for {elapsed:.1f}s): {entry['name']}")
            self.hostDiscovered.emit()  # Notify UI to refresh

class ConnectionManager(QObject):
    """Manages the list of active discovered hosts and the current connection."""

    connectionChanged = Signal(object)  # emits HostClient on connect, None on disconnect

    def __init__(self, parent=None):
        super().__init__(parent)
        self._active = None
        self._activeName = ""
        self._activeHost = ""
        self._connections: dict[str, HostClient] = {}  # server name -> HostClient

        # Load discovery port from hosts.json if it exists
        data = loadJson(HOSTS_FILE) if os.path.exists(HOSTS_FILE) else {}
        self.discoveryPort = data.get("discoveryPort", DEFAULT_DISCOVERY_PORT)

        self.discoveryServer = DiscoveryServer(self.discoveryPort)
        self.discoveryServer.start()

    def setDiscoveryPort(self, port: int):
        self.discoveryPort = port
        saveJson(HOSTS_FILE, {"discoveryPort": port})

        # Restart discovery server
        self.discoveryServer.stop()
        self.discoveryServer = DiscoveryServer(port)
        self.discoveryServer.start()

    def servers(self) -> dict:
        """Return all currently discovered hosts."""
        result = {}
        for entry in self.discoveryServer.discoveredHosts().values():
            result[entry["name"]] = entry
        return result

    def findServer(self, name: str) -> dict | None:
        """Return a server entry dict by name, or None if not found."""
        for entry in self.discoveryServer.discoveredHosts().values():
            if entry["name"] == name:
                return entry
        return None

    def connectHost(self, name: str) -> HostClient:
        """Connect to a server by name and store it. Does not change the active connection."""
        if name in self._connections:
            return self._connections[name]

        entry = self.findServer(name)
        if entry is None:
            raise ValueError(f"Server {name!r} not found or not active")

        conn = HostClient("localhost", entry["cmdPort"], entry["eventPort"])
        reply = conn.ping()
        if not reply.get("ok"):
            err = reply.get("error")
            conn.stop()
            raise ConnectionError(f"Could not connect to {name!r}: {err}")

        self._connections[name] = conn
        return conn

    def getConnection(self, name: str) -> Optional[HostClient]:
        """Return an existing connection by server name, or None."""
        return self._connections.get(name)

    def getOrConnect(self, name: str) -> HostClient:
        """Return existing connection or establish a new one."""
        return self._connections.get(name) or self.connectHost(name)

    def allConnections(self) -> dict[str, HostClient]:
        """Return all currently open connections."""
        return dict(self._connections)

    def connect(self, name: str, parent=None) -> HostClient:
        """Connect to the named server and set it as the active connection."""
        self.disconnect()

        conn = self.connectHost(name)
        self._active = conn
        self._activeName = name
        entry = self.findServer(name)
        self._activeHost = entry.get("host", "") if entry else ""
        self.connectionChanged.emit(conn)
        return conn

    def disconnect(self, name: str = None):
        """Disconnect a named server, or the active server if name is None."""
        if name is not None:
            conn = self._connections.pop(name, None)
            if conn:
                conn.stop()
            if name == self._activeName:
                self._active = None
                self._activeName = ""
                self._activeHost = ""
                self.connectionChanged.emit(None)
        else:
            # Disconnect active and stop all connections
            for conn in self._connections.values():
                conn.stop()
            self._connections.clear()
            self._active = None
            self._activeName = ""
            self._activeHost = ""
            self.connectionChanged.emit(None)

    def activeConnection(self) -> Optional[HostClient]:
        return self._active

    def activeServerName(self) -> str:
        return self._activeName

    def activeHost(self) -> str:
        return self._activeHost

    def isActive(self) -> bool:
        """Return True if there is an active host connection."""
        return self._active is not None

connectionManager = ConnectionManager()

# Default standalone server handling
standaloneServer = StandaloneServer(connectionManager.discoveryPort)
standaloneServer.start()
