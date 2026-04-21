"""Rig Builder client: connection manager for saved host servers."""

import json
import os
import logging
from typing import Optional

from .. import settings
from . import HostClient
from ..utils import loadJson, saveJson
from ..server.hosts.standalone import StandaloneServer

HOSTS_FILE = os.path.join(settings.RIG_BUILDER_USER_PATH, "hosts.json")

logger = logging.getLogger('rigBuilder')

def migrateServers():
    """Migrate servers from old format to new format."""
    if os.path.exists(HOSTS_FILE):
        try:
            data = loadJson(HOSTS_FILE)
            for entry in data.values(): # add default values for backward compatibility
                if entry.get("cmdPort"): # if the file already has the new format, return
                    return

                entry["cmdPort"] = entry.get("rep_port", 51602)
                entry["eventPort"] = entry.get("pub_port", 51603)
                entry["host"] = entry.get("host", "Standalone")
                entry["address"] = entry.get("address", "localhost")

                del entry["rep_port"]
                del entry["pub_port"]
                
            saveJson(HOSTS_FILE, data)
        except Exception as e:
            logger.error(f"Failed to migrate servers from {HOSTS_FILE}: {e}")

class ConnectionManager:
    """Manages the list of saved host servers and the currently active connection."""

    def __init__(self):
        self._active = None
        self._activeName = ""
        self._activeHost = ""
        migrateServers()

    # ------------------------------------------------------------------
    # Server list persistence
    # ------------------------------------------------------------------

    def servers(self) -> dict:
        """Return all saved server entries as a dictionary."""
        if os.path.exists(HOSTS_FILE):
            try:
                return loadJson(HOSTS_FILE)

            except Exception as e:
                logger.error(f"Failed to load servers from {HOSTS_FILE}: {e}")
        return {}

    def saveServers(self, entries: dict):
        """Persist the full server dictionary."""
        os.makedirs(os.path.dirname(HOSTS_FILE), exist_ok=True)
        try:
            saveJson(HOSTS_FILE, entries)
        except Exception as e:
            logger.error(f"Failed to save servers to {HOSTS_FILE}: {e}")

    def addServer(self, name: str, host: str, address: str, cmdPort: int, eventPort: int):
        """Add a new server entry. Replaces an existing entry with the same name."""
        try:
            data = loadJson(HOSTS_FILE) if os.path.exists(HOSTS_FILE) else {}
        except Exception as e:
            logger.error(f"Failed to load servers from {HOSTS_FILE}: {e}")
            data = {}

        data[name] = {"host": host, "address": address, "cmdPort": cmdPort, "eventPort": eventPort}
        self.saveServers(data)

    def removeServer(self, name: str):
        """Remove a server entry by name."""
        try:
            data = loadJson(HOSTS_FILE) if os.path.exists(HOSTS_FILE) else {}
        except Exception as e:
            logger.error(f"Failed to load servers from {HOSTS_FILE}: {e}")
            return

        if name in data:
            del data[name]
            self.saveServers(data)

    def findServer(self, name: str) -> dict | None:
        """Return a server entry dict by name, or None if not found."""
        try:
            data = loadJson(HOSTS_FILE) if os.path.exists(HOSTS_FILE) else {}
        except Exception as e:
            logger.error(f"Failed to load servers from {HOSTS_FILE}: {e}")
            return None

        entry = data.get(name)
        if entry:
            result = entry.copy()            
            result["name"] = name
            return result
        return None

    # ------------------------------------------------------------------
    # Connection management
    # ------------------------------------------------------------------

    def connect(self, name: str, parent=None) -> HostClient:
        """Connect to the named server. Raises if the server is not reachable.

        Args:
            name:   server name as stored in hosts.json
            parent: optional Qt parent for the HostClient QObject

        Returns:
            The connected HostClient, also set as the active connection.
        """
        self.disconnect()  # Ensure previous connection is fully stopped

        entry = self.findServer(name)
        if entry is None:
            raise ValueError(f"Server {name!r} not found in {HOSTS_FILE}")

        conn = HostClient(entry["address"], entry["cmdPort"], entry["eventPort"], parent)
        reply = conn.ping()
        if not reply.get("ok"):
            err = reply.get("error")
            conn.stop()
            raise ConnectionError(f"Could not connect to {name!r}: {err}")

        self._active = conn
        self._activeName = name
        self._activeHost = entry.get("host", "")
        return conn

    def disconnect(self):
        """Disconnect the active server (does not destroy the ZMQ context)."""
        if self._active:
            self._active.stop()
        self._active = None
        self._activeName = ""
        self._activeHost = ""

    def activeConnection(self) -> Optional[HostClient]:
        """Return the active HostClient, or None if not connected."""
        return self._active

    def activeServerName(self) -> str:
        """Return the name of the active server, or empty string."""
        return self._activeName

    def activeHost(self) -> str:
        """Return the host name of the active connection: i.e. maya, blender, houdini, etc.
        Returns an empty string if not connected.
        """
        return self._activeHost

connectionManager = ConnectionManager()

# Make default standalone server

if not connectionManager.findServer("Default"):
    connectionManager.addServer("Default", "standalone", "localhost", 51600, 51601)

defaultServer = connectionManager.findServer("Default")

defaultStandaloneServer = StandaloneServer(defaultServer["cmdPort"], defaultServer["eventPort"])
defaultStandaloneServer.start()
