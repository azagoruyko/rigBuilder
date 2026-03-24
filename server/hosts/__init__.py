"""HostServer — ZeroMQ REP+PUB server base class for host adapters."""

import json
import threading
import os
import time
import traceback
from typing import Callable

import zmq

from rigBuilder.server.runner import runModule, executeModuleCode, executeCode


AVAILABLE_HOSTS = sorted(["blender", "houdini", "maya", "standalone", "unreal"])

HOST_STARTUP_TEMPLATE = """import sys
rigBuilderPath = r"{rigBuilderPath}"
if rigBuilderPath not in sys.path:
    sys.path.append(rigBuilderPath)

from rigBuilder.server.hosts.{host} import {HostClass}
rigBuilderServer = {HostClass}(rep_port={rep_port}, pub_port={pub_port})
rigBuilderServer.start()"""

MODULE_EXECUTION_TIMEOUT = 86400 # 24 hours
CODE_EXECUTION_TIMEOUT = 60 # 60 seconds
HEARTBEAT_INTERVAL_SEC = 2.0

class HostServer:
    """Base ZeroMQ server. Listens for commands on a REP socket and
    publishes events on a PUB socket.

    Subclasses override executeOnMainThread() to provide host-specific behaviour.

    Protocol:
        REQ/REP  — synchronous command/reply
        PUB      — asynchronous event stream to all connected clients
    """

    def __init__(self, rep_port: int, pub_port: int):
        self._rep_port = rep_port
        self._pub_port = pub_port
        self._ctx = None
        self._running = False

    def start(self):
        """Bind sockets and start the command loop on a daemon thread."""
        if self._running:
            return

        self._ctx = zmq.Context()
        self._rep = self._ctx.socket(zmq.REP)
        self._pub = self._ctx.socket(zmq.PUB)
        self._rep.bind(f"tcp://*:{self._rep_port}")
        self._pub.bind(f"tcp://*:{self._pub_port}")
        self._running = True
        t = threading.Thread(target=self._loop, daemon=True, name="rigbuilder-server")
        t.start()

        hb = threading.Thread(target=self._heartbeatLoop, daemon=True, name="rigbuilder-heartbeat")
        hb.start()
        
        print(f"[rigBuilder.server] listening — REP:{self._rep_port}  PUB:{self._pub_port}")

    def stop(self):
        """Stop the server and release ZeroMQ resources."""
        self._running = False
        if self._ctx:
            self._ctx.destroy(linger=0)
            self._ctx = None

    def emit(self, event: dict):
        """Publish a single event dict to all subscribed clients."""
        self._pub.send_string(json.dumps(event))

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
                raw = self._rep.recv_string()
            except zmq.ZMQError:
                break   # context destroyed → stop cleanly

            try:
                msg = json.loads(raw)
            except ValueError:
                self._rep.send_string(json.dumps({"ok": False, "error": "invalid JSON"}))
                continue

            cmd = msg.get("cmd")
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

            self._rep.send_string(json.dumps(reply))

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
            lambda: runModule(msg["xml"], msg.get("path", "."), self.emit, msg["id"]),
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
            ),
            timeout=CODE_EXECUTION_TIMEOUT,
        )

    def executeCode(self, msg: dict) -> dict:
        """Execute host-side code and return a JSON-serializable context."""
        return self._scheduleHostExecution(
            lambda: executeCode(msg["code"], self.emit, msg["id"]),
            timeout=CODE_EXECUTION_TIMEOUT,
        )
        