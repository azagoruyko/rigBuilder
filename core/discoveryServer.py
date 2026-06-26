import json
import logging
import threading
import time
import zmq
from .signal import Signal
from rigBuilder.core.settings import REGISTRATION_INTERVAL_SEC

logger = logging.getLogger('rigBuilder')

class DiscoveryServer:
    """Listens for registration messages from host servers on a fixed port."""

    def __init__(self, port: int):
        self.hostDiscovered = Signal()

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

