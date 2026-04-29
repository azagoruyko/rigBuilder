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
REGISTRATION_INTERVAL_SEC = 5.0  # how often to re-announce to the discovery server


class HostServer:
    """Base ZeroMQ server. Listens for commands on a PULL socket and
    publishes events (including command replies) on a PUB socket.

    Subclasses override executeOnMainThread() to provide host-specific behaviour.

    Protocol:
        PUSH/PULL — client pushes commands; server pulls them (no state machine)
        PUB       — asynchronous event stream to all clients.
                    Command replies are emitted as {"event": "reply", "id": runId, …}

    Thread model:
        rigbuilder-server      — blocking PULL recv + command dispatch
        rigbuilder-pub         — serializes all PUB sends (zmq sockets are not thread-safe)
        rigbuilder-heartbeat   — periodic heartbeat events
        rigbuilder-registration — re-registers with the discovery server periodically
    """

    def __init__(self, discoveryPort=51605):
        self._pullPort = 0
        self._pubPort = 0
        self._discoveryPort = discoveryPort
        self._ctx = None
        self._running = False
        # _pubQueue carries event dicts; _pubLoop is the only thread that calls send_string.
        self._pubQueue = queue.Queue()

    def start(self):
        """Bind sockets and start all daemon threads."""
        if self._running:
            return

        self._ctx = zmq.Context()
        self._pull = self._ctx.socket(zmq.PULL)
        self._pub = self._ctx.socket(zmq.PUB)
        
        self._pull.setsockopt(zmq.LINGER, 0)
        self._pub.setsockopt(zmq.LINGER, 0)
        
        self._pull.bind(f"tcp://*:{self._pullPort}")
        self._pub.bind(f"tcp://*:{self._pubPort}")

        # Resolve the actual OS-assigned ports when 0 was requested.
        if self._pullPort == 0:
            endpoint = self._pull.getsockopt_string(zmq.LAST_ENDPOINT)
            self._pullPort = int(endpoint.split(":")[-1])
        
        if self._pubPort == 0:
            endpoint = self._pub.getsockopt_string(zmq.LAST_ENDPOINT)
            self._pubPort = int(endpoint.split(":")[-1])

        self._running = True

        threading.Thread(target=self._pubLoop, daemon=True, name="rigbuilder-pub").start()
        threading.Thread(target=self._loop, daemon=True, name="rigbuilder-server").start()
        threading.Thread(target=self._heartbeatLoop, daemon=True, name="rigbuilder-heartbeat").start()
        threading.Thread(target=self._registerWithDiscovery, daemon=True, name="rigbuilder-registration").start()

        print(f"[rigBuilder.server] listening — PULL:{self._pullPort}  PUB:{self._pubPort}")

    def stop(self):
        """Stop the server and release ZeroMQ resources."""
        self._running = False
        # Unblock _pubLoop's queue.get so it can exit promptly.
        self._pubQueue.put(None)
        if self._ctx:
            self._ctx.destroy(linger=0)
            self._ctx = None

    def emit(self, event):
        """Enqueue an event dict to be published to all subscribed clients.

        Thread-safe: any thread can call emit(); only _pubLoop touches the socket.
        """
        if self._running:
            self._pubQueue.put(event)

    # ------------------------------------------------------------------
    # Internal threads
    # ------------------------------------------------------------------

    def _pubLoop(self):
        """Serialize PUB sends onto a single thread (zmq sockets are not thread-safe).

        None is used as a sentinel to unblock the queue when stop() is called.
        task_done() is always called so that _loop's join() can unblock safely
        even if a ZMQError occurs mid-send.
        """
        while self._running:
            try:
                event = self._pubQueue.get(timeout=0.2)
            except queue.Empty:
                continue

            if event is None:
                # Sentinel: server is stopping; drain remaining items without sending.
                self._pubQueue.task_done()
                break

            try:
                self._pub.send_string(json.dumps(event))
            except zmq.ZMQError as e:
                # Context destroyed — stop the loop; remaining items stay in queue.
                print(f"[rigBuilder.server] _pubLoop ZMQError: {e}")
                break
            finally:
                self._pubQueue.task_done()

    def _loop(self):
        """Block on the PULL socket, dispatch commands, and emit replies.

        All PUB events produced during command execution are flushed
        (via _pubQueue.join()) before the final 'reply' event so clients
        always receive prints/progress before the result.
        """
        while self._running:
            try:
                raw = self._pull.recv_string()
            except zmq.ZMQError:
                # Context destroyed — exit cleanly.
                break

            try:
                msg = json.loads(raw)
            except ValueError:
                # Malformed message — no runId to reply to, drop silently.
                continue

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
                reply = {"ok": False, "error": f"unknown command: {cmd}"}

            # Wait for every enqueued event to be sent before the reply.
            # join() is safe because task_done() is always called in _pubLoop,
            # even on ZMQError, so this cannot deadlock.
            self._pubQueue.join()

            self.emit({**reply, "event": "reply", "id": runId})

    def _heartbeatLoop(self):
        """Emit a heartbeat event at a regular interval."""
        while self._running:
            time.sleep(HEARTBEAT_INTERVAL_SEC)
            if not self._running:
                break
            try:
                self.emit({"event": "heartbeat"})
            except zmq.ZMQError as e:
                print(f"[rigBuilder.server] _heartbeatLoop ZMQError: {e}")
                break

    def _registerWithDiscovery(self):
        """Periodically re-announce this server to the discovery server.

        Uses a PUSH socket (fire-and-forget) instead of REQ/REP to avoid
        the strict alternation requirement of REQ, which could deadlock when
        the discovery server is slow or unavailable.
        """
        ctx = zmq.Context()
        sock = ctx.socket(zmq.PUSH)
        sock.setsockopt(zmq.LINGER, 0)
        sock.setsockopt(zmq.SNDHWM, 1)  # drop old announcements if not delivered

        identity = self.ping()
        msg = json.dumps({
            "cmd": "register",
            "host": identity.get("host", "unknown"),
            "name": identity.get("name", "Unknown Host"),
            "cmdPort": self._pullPort,
            "eventPort": self._pubPort,
        })

        try:
            sock.connect(f"tcp://localhost:{self._discoveryPort}")
            while self._running:
                try:
                    sock.send_string(msg, zmq.NOBLOCK)
                except zmq.Again:
                    pass  # HWM reached — discovery server not consuming; skip this tick
                except zmq.ZMQError as e:
                    print(f"[rigBuilder.server] registration ZMQError: {e}")
                    break
                time.sleep(REGISTRATION_INTERVAL_SEC)
        finally:
            sock.close()
            ctx.term()

    # ------------------------------------------------------------------
    # Host-thread execution helpers
    # ------------------------------------------------------------------

    def executeOnMainThread(self, taskFunction):
        """Dispatch a callable to the host main-thread execution context.

        The base implementation runs it synchronously (suitable for standalone).
        Subclasses must override this for hosts that require main-thread execution
        (e.g. Maya, Blender).
        """
        taskFunction()

    def _scheduleHostExecution(self, taskFunction, timeout=30):
        """Schedule *taskFunction* on the host main thread and block until done.

        Returns the dict produced by taskFunction, or a timeout/error dict.
        """
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
        