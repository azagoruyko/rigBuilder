import json
import os
import logging
import threading
import time
import zmq
from typing import Optional

from ..core import settings
from ..core.settings import RIG_BUILDER_USER_PATH
from . import HostClient
from ..core.utils import loadJson, saveJson
from ..host.servers.standalone import StandaloneServer
from ..host.servers import REGISTRATION_INTERVAL_SEC
from ..ui.qt import QObject, Signal

HOSTS_FILE = os.path.join(RIG_BUILDER_USER_PATH, "hosts.json")
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
        self._discoveredHosts = {} # cmdPort -> entry

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
                        name = msg.get("name", host.capitalize())

                        if cmdPort in self._discoveredHosts:
                            self._discoveredHosts[cmdPort].update({"lastSeen": time.time()})
                        else: # when new server is discovered
                            count = 0
                            for entry in self._discoveredHosts.values():
                                if entry["name"].startswith(name):
                                    count += 1

                            nameSuffix = f" ({count})" if count > 0 else ""

                            entry = {
                                "host": host,
                                "cmdPort": cmdPort,
                                "eventPort": eventPort,
                                "name": name + nameSuffix,
                                "lastSeen": time.time()
                            }

                            self._discoveredHosts[cmdPort] = entry
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

    def connect(self, name: str, parent=None) -> HostClient:
        """Connect to the named server. Raises if the server is not reachable."""
        self.disconnect()

        entry = self.findServer(name)
        if entry is None:
            raise ValueError(f"Server {name!r} not found or not active")

        conn = HostClient("localhost", entry["cmdPort"], entry["eventPort"], parent)
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

# Default standalone server handling
standaloneServer = StandaloneServer(connectionManager.discoveryPort)
standaloneServer.start()
