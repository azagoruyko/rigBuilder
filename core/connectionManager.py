import json
import os
import logging
import threading
import time
import zmq
from typing import Optional

from ..core.settings import RIG_BUILDER_USER_PATH, HOSTS_FILE, DEFAULT_DISCOVERY_PORT
from .hostClient import HostClient
from .discoveryServer import DiscoveryServer
from ..core.utils import loadJson, saveJson
from .signal import Signal

logger = logging.getLogger('rigBuilder')

class ConnectionManager:
    """Manages the list of active discovered hosts and the current connection."""

    def __init__(self):
        self.connectionChanged = Signal()  # emits HostClient on connect, None on disconnect

        self._active = None
        self._activeName = ""
        self._activeHost = ""
        
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
        return {entry["name"]: entry for entry in self.discoveryServer.discoveredHosts().values()}

    def findServer(self, name: str) -> Optional[dict]:
        """Return a server entry dict by name, or None if not found."""
        for entry in self.discoveryServer.discoveredHosts().values():
            if entry["name"] == name:
                return entry
        return None

    def connect(self, name: str) -> HostClient:
        """Connect to the named server. Raises if the server is not reachable."""
        self.disconnect()

        entry = self.findServer(name)
        if entry is None:
            raise ValueError(f"Server {name!r} not found or not active")

        conn = HostClient("localhost", entry["cmdPort"], entry["eventPort"])
        reply = conn.ping()
        if not reply.get("ok"):
            err = reply.get("error")
            conn.stop()
            raise ConnectionError(f"Could not connect to {name!r}: {err}")

        self._active = conn
        self._activeName = name
        self._activeHost = entry.get("host", "")
        self.connectionChanged.emit(conn)
        return conn

    def disconnect(self):
        """Disconnect the active server."""
        conn = self._active
        self._active = None
        self._activeName = ""
        self._activeHost = ""
        if conn:
            conn.stop()
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
