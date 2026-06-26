"""Rig Builder client: connects to a host server and streams events via signals."""
import json
import queue
import uuid
import threading
import time
import zmq
import traceback

from .signal import Signal

DEFAULT_RUN_TIMEOUT = 86400.0  # 24 hours

# Must stay above server HEARTBEAT_INTERVAL_SEC * 3 (see server.hosts.__init__).
# Use a wider window to reduce false disconnects during heavy host workloads.
SUB_STALE_TIMEOUT_SEC = 10.0

class HostClient:
    """ZeroMQ client that connects to a single host server.

    Uses two sockets:
        PUSH — sends commands fire-and-forget (no state machine, no lock during wait).
        SUB  — receives asynchronous event stream including command replies.

    Each _send() registers a queue.Queue(maxsize=1) keyed by runId.
    The SUB listener puts the reply into it when {"event": "reply", "id": runId} arrives.
    """

    def __init__(self, address: str, cmd_port: int, event_port: int):
        self.onAnyEvent = Signal()
        self.onRunCallback = Signal()
        self.onPrint = Signal()
        self.onError = Signal()
        self.onConnectionLost = Signal()

        self.beginProgress = Signal()
        self.stepProgress = Signal()
        self.endProgress = Signal()
        
        self.idleCallback = None

        self._ctx = zmq.Context.instance()

        self._push = self._ctx.socket(zmq.PUSH)
        self._sub = self._ctx.socket(zmq.SUB)
        self._push.connect(f"tcp://{address}:{cmd_port}")
        self._sub.connect(f"tcp://{address}:{event_port}")
        self._sub.setsockopt_string(zmq.SUBSCRIBE, "")

        # ZMQ subscriptions are asynchronous: give the SUB a moment to propagate
        # to the PUB before anyone sends a command whose reply travels via PUB/SUB.
        time.sleep(0.1)

        self._lock = threading.Lock()      # serialise PUSH sends
        self._replyLock = threading.Lock() # protect _pendingReplies
        self._pendingReplies = {}          # runId -> queue.Queue(maxsize=1)

        self._subActivityLock = threading.Lock()
        self._connLostLock = threading.Lock()
        self._lastSubActivityMonotonic = time.monotonic()
        self._connectionLostEmitted = False

        self._running = True
        self._listener_thread = threading.Thread(target=self._listen, daemon=True)
        self._listener_thread.start()

    def stop(self):
        """Stop the listener thread and close the sockets."""
        self._running = False

        # Wake any blocked _send() waiters so they don't hang.
        with self._replyLock:
            for q in self._pendingReplies.values():
                try:
                    q.put_nowait({"ok": False, "error": "connection stopping"})
                except queue.Full:
                    pass  # a real reply already arrived

        try:
            with self._lock:
                self._push.close(linger=0)
        except zmq.ZMQError:
            pass

    def _touchSubActivity(self):
        with self._subActivityLock:
            self._lastSubActivityMonotonic = time.monotonic()

    def _emitConnectionLostOnce(self, reason: str):
        with self._connLostLock:
            if not self._running or self._connectionLostEmitted:
                return
            self._connectionLostEmitted = True
        self.onConnectionLost.emit(reason)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def ping(self) -> dict:
        """Ping the server. Returns {"ok": True, "host": "…"}."""
        return self._send({"cmd": "ping"}, timeout_seconds=1.0)

    def runModule(self, moduleXml: str, modulePath: str, contextKey: str = "") -> dict:
        """Run module XML on the host; blocks until the server finishes."""
        return self._send({"cmd": "runModule", "xml": moduleXml, "path": modulePath, "contextKey": contextKey})

    def executeModuleCode(self, moduleXml: str, modulePath: str, code: str, contextKey: str = "") -> dict:
        """Execute a Python snippet against a module in the moduleXml tree on the host."""
        return self._send({"cmd": "executeModuleCode", "xml": moduleXml, "path": modulePath, "code": code, "contextKey": contextKey})

    def executeCode(self, code: str, contextKey: str = "") -> dict:
        """Execute host-side Python code and return JSON-serializable context."""
        return self._send({"cmd": "executeCode", "code": code, "contextKey": contextKey})

    def switchWorkspace(self, name: str) -> dict:
        """Switch workspace on the host."""
        return self._send({"cmd": "switchWorkspace", "name": name})

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _send(self, msg: dict, timeout_seconds: float = DEFAULT_RUN_TIMEOUT) -> dict:
        """Push *msg* to the server and block until a matching reply arrives on the SUB socket.

        The lock is held only for the brief PUSH send, never during the wait,
        so processEvents() cannot cause a deadlock even when called from the GUI thread.
        """
        runId = uuid.uuid4().hex
        msg["id"] = runId

        reply_queue = queue.Queue(maxsize=1)
        with self._replyLock:
            self._pendingReplies[runId] = reply_queue

        try:
            # --- 1. Push the command to the server ---
            with self._lock:
                if not self._running or self._push.closed:
                    return {"ok": False, "error": "connection stopping"}
                
                try:
                    self._push.send_string(json.dumps(msg))
                except zmq.ZMQError:
                    return {"ok": False, "error": "socket error during send"}

            # --- 2. Wait for the asynchronous reply ---
            if self.idleCallback:
                # GUI thread: poll the queue so we can process UI events (prevents freezing)
                deadline = time.time() + timeout_seconds
                while time.time() < deadline:
                    try:
                        reply = reply_queue.get_nowait()
                        self.idleCallback()
                        return reply
                    except queue.Empty:
                        if not self._running:
                            return {"ok": False, "error": "connection stopping"}
                        self.idleCallback()
                        time.sleep(0.05)
            else:
                # Background thread: efficiently block until the reply arrives
                try:
                    return reply_queue.get(timeout=timeout_seconds)
                except queue.Empty:
                    pass

            # --- 3. Handle Timed Out Requests ---
            if self._running:
                self._emitConnectionLostOnce("Server stopped replying (request timed out).")
            return {"ok": False, "error": "server timeout"}

        finally:
            # --- 4. Cleanup ---
            with self._replyLock:
                self._pendingReplies.pop(runId, None)

    def _listen(self):
        """Persistent daemon thread that forwards all PUB events as signals."""
        try:
            while self._running:
                try:
                    if not self._sub.poll(timeout=200):
                        with self._subActivityLock:
                            idle = time.monotonic() - self._lastSubActivityMonotonic
                        if idle >= SUB_STALE_TIMEOUT_SEC:
                            self._emitConnectionLostOnce(
                                "No messages from host for too long; the host may have stopped or the network failed."
                            )
                            break
                        continue

                    ev = json.loads(self._sub.recv_string())
                    self._touchSubActivity()
                    self._dispatchSignal(ev)
                except zmq.ZMQError:
                    if self._running:
                        self._emitConnectionLostOnce("PUB connection error (host closed or network lost).")
                    break
                except Exception as e:
                    self.onError.emit(f"Error processing PUB event: {e}", traceback.format_exc())
        finally:
            try:
                self._sub.close(linger=0)
            except zmq.ZMQError:
                pass

    def _dispatchSignal(self, ev: dict):
        """Emit the appropriate signal for the incoming event."""
        event = ev.get("event")
        self.onAnyEvent.emit(ev)

        if event == "runCallback":
            self.onRunCallback.emit(ev.get("path", ""))

        elif event == "print":
            self.onPrint.emit(ev.get("text", ""))

        elif event == "error":
            self.onError.emit(ev.get("text", ""), ev.get("traceback", ""))

        elif event == "beginProgress":
            self.beginProgress.emit(ev.get("text", ""), ev.get("count", 0))

        elif event == "stepProgress":
            self.stepProgress.emit(ev.get("value", 0), ev.get("text", ""))

        elif event == "endProgress":
            self.endProgress.emit()

        elif event == "reply":
            runId = ev.get("id")
            if runId:
                with self._replyLock:
                    q = self._pendingReplies.get(runId)
                if q is not None:
                    try:
                        q.put_nowait(ev)
                    except queue.Full:
                        pass  # stop() already filled the queue
