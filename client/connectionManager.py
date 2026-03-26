"""Rig Builder client: connection manager for saved host servers."""

import json
import os
from typing import Optional

from ..core import RigBuilderPrivatePath
from . import HostClient
from ..server.hosts.standalone import StandaloneServer

HOSTS_FILE = os.path.join(RigBuilderPrivatePath, "hosts.json")

class ConnectionManager:
    """Manages the list of saved host servers and the currently active connection."""

    def __init__(self):
        self._active = None
        self._active_name = ""
        self._active_host = ""

    # ------------------------------------------------------------------
    # Server list persistence
    # ------------------------------------------------------------------

    def servers(self) -> dict:
        """Return all saved server entries as a dictionary."""
        if not os.path.exists(HOSTS_FILE):
            return {}
            
        with open(HOSTS_FILE, "r") as f:
            return json.load(f)

    def saveServers(self, entries: dict):
        """Persist the full server dictionary."""
        with open(HOSTS_FILE, "w") as f:
            json.dump(entries, f, indent=2)

    def addServer(self, name: str, host: str, address: str, rep_port: int, pub_port: int):
        """Add a new server entry. Replaces an existing entry with the same name."""
        if os.path.exists(HOSTS_FILE):
            with open(HOSTS_FILE, "r") as f:
                data = json.load(f)
        else:
            data = {}

        data[name] = {
            "host": host,
            "address": address, "rep_port": rep_port, "pub_port": pub_port,
        }
        self.saveServers(data)

    def removeServer(self, name: str):
        """Remove a server entry by name."""
        if not os.path.exists(HOSTS_FILE):
            return
            
        with open(HOSTS_FILE, "r") as f:
            data = json.load(f)
        
        if name in data:
            del data[name]
            self.saveServers(data)

    def findServer(self, name: str) -> dict | None:
        """Return a server entry dict by name, or None if not found."""
        if not os.path.exists(HOSTS_FILE):
            return None
            
        with open(HOSTS_FILE, "r") as f:
            data = json.load(f)
            
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

        conn = HostClient(entry["address"], entry["rep_port"], entry["pub_port"], parent)
        reply = conn.ping()
        if not reply.get("ok"):
            err = reply.get("error")
            conn.stop()
            raise ConnectionError(f"Could not connect to {name!r}: {err}")

        self._active = conn
        self._active_name = name
        self._active_host = entry.get("host", "")
        return conn

    def disconnect(self):
        """Disconnect the active server (does not destroy the ZMQ context)."""
        if self._active:
            self._active.stop()
        self._active = None
        self._active_name = ""
        self._active_host = ""

    def activeConnection(self) -> Optional[HostClient]:
        """Return the active HostClient, or None if not connected."""
        return self._active

    def activeServerName(self) -> str:
        """Return the name of the active server, or empty string."""
        return self._active_name

    def activeHost(self) -> str:
        """Return the host name of the active connection: i.e. maya, blender, houdini, etc.
        Returns an empty string if not connected.
        """
        return self._active_host

connectionManager = ConnectionManager()

# Make default standalone server

defaultServer = connectionManager.findServer("Default")
if not defaultServer:
    connectionManager.addServer("Default", "standalone", "127.0.0.1", 7000, 7001)
    defaultServer = connectionManager.findServer("Default")

defaultStandaloneServer = StandaloneServer(defaultServer["rep_port"], defaultServer["pub_port"])
defaultStandaloneServer.start()
