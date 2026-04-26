"""HostServer — ZeroMQ PULL+PUB server base class for host adapters."""

import json
import threading
import queue
import time
import traceback
from typing import Callable

import zmq

from rigBuilder.server.runner import runModule, executeModuleCode, executeCode

AVAILABLE_HOSTS = sorted(["blender", "houdini", "maya", "standalone", "unreal"]) # names MUST match the host files in this folder!

HOST_STARTUP_TEMPLATE = """import sys
RIG_BUILDER_PATH = r"{RIG_BUILDER_PATH}"
if RIG_BUILDER_PATH not in sys.path:
    sys.path.append(RIG_BUILDER_PATH)

from rigBuilder.server.hosts.{host} import {HostClass}
rigBuilderServer = {HostClass}({discoveryPort})
rigBuilderServer.start()"""

MODULE_EXECUTION_TIMEOUT = 86400 # 24 hours
CODE_EXECUTION_TIMEOUT = 60 # 60 seconds
HEARTBEAT_INTERVAL_SEC = 2.0

class HostServer:
    """Base ZeroMQ server. Listens for commands on a PULL socket and
    publishes events (including command replies) on a PUB socket.

    Subclasses override executeOnMainThread() to provide host-specific behaviour.

    Protocol:
        PUSH/PULL — client pushes commands; server pulls them (no state machine)
        PUB       — asynchronous event stream to all clients.
                    Command replies are emitted as {"event": "reply", "id": runId, …}
    """

    def __init__(self, discoveryPort: int = 51605):
        self._pullPort = 0
        self._pubPort = 0
        self._discoveryPort = discoveryPort
        self._ctx = None
        self._running = False
        self._pubQueue = queue.Queue()

    def start(self):
        """Bind sockets and start the command loop on a daemon thread."""
        if self._running:
            return

        self._ctx = zmq.Context()
        self._pull = self._ctx.socket(zmq.PULL)
        self._pub = self._ctx.socket(zmq.PUB)
        
        self._pull.setsockopt(zmq.LINGER, 0)
        self._pub.setsockopt(zmq.LINGER, 0)
        
        self._pull.bind(f"tcp://*:{self._pullPort}")
        self._pub.bind(f"tcp://*:{self._pubPort}")

        # Get actual ports if they were random
        if self._pullPort == 0:
            endpoint = self._pull.getsockopt_string(zmq.LAST_ENDPOINT)
            self._pullPort = int(endpoint.split(":")[-1])
        
        if self._pubPort == 0:
            endpoint = self._pub.getsockopt_string(zmq.LAST_ENDPOINT)
            self._pubPort = int(endpoint.split(":")[-1])

        self._running = True
        
        # Register with discovery server
        self._registerWithDiscovery()

        t = threading.Thread(target=self._loop, daemon=True, name="rigbuilder-server")
        t.start()

        pub_t = threading.Thread(target=self._pubLoop, daemon=True, name="rigbuilder-pub")
        pub_t.start()

        hb = threading.Thread(target=self._heartbeatLoop, daemon=True, name="rigbuilder-heartbeat")
        hb.start()
        
        print(f"[rigBuilder.server] listening — PULL:{self._pullPort}  PUB:{self._pubPort}")

    def stop(self):
        """Stop the server and release ZeroMQ resources."""
        self._running = False
        if self._ctx:
            self._ctx.destroy(linger=0)
            self._ctx = None

    def emit(self, event: dict):
        """Publish a single event dict to all subscribed clients by placing it in the pub queue."""
        if self._running:
            self._pubQueue.put(event)

    def _registerWithDiscovery(self):
        """Announce this server to the discovery server."""
        def task():
            ctx = zmq.Context()
            socket = ctx.socket(zmq.REQ)
            socket.setsockopt(zmq.LINGER, 0)
            socket.setsockopt(zmq.REQ_RELAXED, 1)
            socket.setsockopt(zmq.REQ_CORRELATE, 1)
            try:
                socket.connect(f"tcp://localhost:{self._discoveryPort}")
                identity = self.ping()
                msg = {
                    "cmd": "register",
                    "host": identity.get("host", "unknown"),
                    "name": identity.get("name", "Unknown Host"),
                    "cmdPort": self._pullPort,
                    "eventPort": self._pubPort
                }
                
                while self._running:
                    try:
                        socket.send_string(json.dumps(msg))
                        if socket.poll(timeout=2000):
                            socket.recv_string()
                    except Exception:
                        pass
                    time.sleep(1.0)
            except Exception:
                pass
            finally:
                socket.close()
                ctx.term()

        t = threading.Thread(target=task, daemon=True, name="rigbuilder-registration")
        t.start()

    def _pubLoop(self):
        """Daemon thread to serialize PUB sends ensuring libzmq thread safety."""
        while self._running:
            try:
                event = self._pubQueue.get(timeout=0.2)
                if not self._running:
                    break
                self._pub.send_string(json.dumps(event))
            except queue.Empty:
                continue
            except zmq.ZMQError:
                break
            except Exception:
                pass


    def executeOnMainThread(self, taskFunction: Callable):
        """Dispatch worker to host main-thread execution context."""
        taskFunction()

    def _scheduleHostExecution(self, taskFunction: Callable, *, timeout: float = 30) -> dict:
        """Schedule host task and wait for completion."""
        done = threading.Event()
        result = {}

        def task():
            try:
                result["reply"] = taskFunction()
            except Exception as e:
                result["reply"] = {"ok": False, "error": str(e), "traceback": traceback.format_exc()}

            finally:
                done.set()

        self.executeOnMainThread(task)
        done.wait(timeout=timeout)
        return result.get("reply", {"ok": False, "error": "timeout"})

    # ------------------------------------------------------------------
    # Command loop
    # ------------------------------------------------------------------

    def _loop(self):
        while self._running:
            try:
                raw = self._pull.recv_string()
            except zmq.ZMQError:
                break   # context destroyed → stop cleanly

            try:
                msg = json.loads(raw)
            except ValueError:
                continue  # cannot match a reply without a runId; drop silently

            cmd = msg.get("cmd")
            runId = msg.get("id", "")

            if cmd == "ping":
                reply = self.ping()

            elif cmd == "runModule":
                reply = self.runModule(msg)

            elif cmd == "executeModuleCode":
                reply = self.executeModuleCode(msg)

            elif cmd == "executeCode":
                reply = self.executeCode(msg)

            else:
                reply = {"ok": False, "error": f"unknown command: {cmd!r}"}

            self.emit({**reply, "event": "reply", "id": runId})

    def _heartbeatLoop(self):
        while self._running:
            time.sleep(HEARTBEAT_INTERVAL_SEC)
            if not self._running:
                break
            try:
                self.emit({"event": "heartbeat"})
            except Exception:
                break

    # ------------------------------------------------------------------
    # Public override points for host subclasses
    # ------------------------------------------------------------------

    def ping(self) -> dict:
        """Return server identity. Override to include host name and version."""
        return {"ok": True, "host": "standalone"}

    def runModule(self, msg: dict) -> dict:
        """Execute a module XML payload; return updated XML."""
        return self._scheduleHostExecution(
            lambda: runModule(msg["xml"], msg.get("path", "."), self.emit, msg["id"], msg.get("contextKey", "")),
            timeout=MODULE_EXECUTION_TIMEOUT,
        )

    def executeModuleCode(self, msg: dict) -> dict:
        """Execute snippet against a module XML payload; return JSON context and XML."""
        return self._scheduleHostExecution(
            lambda: executeModuleCode(
                msg["xml"],
                msg.get("path", "."),
                msg["code"],
                self.emit,
                msg["id"],
                msg.get("contextKey", ""),
            ),
            timeout=CODE_EXECUTION_TIMEOUT,
        )

    def executeCode(self, msg: dict) -> dict:
        """Execute host-side code and return a JSON-serializable context."""
        return self._scheduleHostExecution(
            lambda: executeCode(msg["code"], self.emit, msg["id"], msg.get("contextKey", "")),
            timeout=CODE_EXECUTION_TIMEOUT,
        )
        