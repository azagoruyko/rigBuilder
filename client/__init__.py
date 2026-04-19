"""Rig Builder client: connects to a host server and streams events via Qt signals."""
import json
import uuid
import threading
import time
import zmq
import traceback

from ..qt import QObject, Signal, QApplication, QThread, QTimer

DEFAULT_RUN_TIMEOUT = 86400.0  # 24 hours

# Must stay above server HEARTBEAT_INTERVAL_SEC * 3 (see server.hosts.__init__).
# Use a wider window to reduce false disconnects during heavy host workloads.
SUB_STALE_TIMEOUT_SEC = 10.0

class HostClient(QObject):
    """ZeroMQ client that connects to a single host server.

    Uses two sockets:
        PUSH — sends commands fire-and-forget (no state machine, no lock during wait).
        SUB  — receives asynchronous event stream including command replies.

    Each _send() registers a threading.Event keyed by runId.
    The SUB listener sets it when a matching {"event": "reply", "id": runId} arrives.
    """

    onAnyEvent = Signal(dict)
    onRunCallback = Signal(str)
    onPrint = Signal(str)
    onError = Signal(str, str)
    onConnectionLost = Signal(str)

    beginProgress = Signal(str, int)
    stepProgress = Signal(int, str)
    endProgress = Signal()

    def __init__(self, address: str, cmd_port: int, event_port: int, parent=None):
        super().__init__(parent)
        self._ctx = zmq.Context.instance()

        self._push = self._ctx.socket(zmq.PUSH)
        self._sub = self._ctx.socket(zmq.SUB)
        self._push.connect(f"tcp://{address}:{cmd_port}")
        self._sub.connect(f"tcp://{address}:{event_port}")
        self._sub.setsockopt_string(zmq.SUBSCRIBE, "")   # subscribe to all

        # ZMQ subscriptions are asynchronous: give the SUB a moment to propagate
        # to the PUB before anyone sends a command whose reply travels via PUB/SUB.
        time.sleep(0.1)

        self._lock = threading.Lock()          # serialise PUSH sends
        self._replyLock = threading.Lock()     # protect _pendingReplies
        self._pendingReplies = {}              # runId -> (threading.Event, dict)
        self._subActivityLock = threading.Lock()
        self._connLostLock = threading.Lock()
        self._lastSubActivityMonotonic = time.monotonic()
        self._connectionLostEmitted = False
        self._stopping = False

        self._running = True
        self._listener_thread = threading.Thread(target=self._listen, daemon=True)
        self._listener_thread.start()

    def stop(self):
        """Stop the listener thread and close the sockets."""
        self._stopping = True
        self._running = False

        # Wake any blocked _send() waiters so they don't hang.
        with self._replyLock:
            for event_obj, _ in self._pendingReplies.values():
                event_obj.set()

        try:
            with self._lock:
                self._push.close(linger=0)
        except Exception:
            pass

    def _touchSubActivity(self):
        with self._subActivityLock:
            self._lastSubActivityMonotonic = time.monotonic()

    def _emitConnectionLostOnce(self, reason: str):
        with self._connLostLock:
            if self._stopping or self._connectionLostEmitted:
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
        """Execute a Python snippet against a module in the moduleXml tree on the host.
        When *contextKey* is non-empty the server accumulates execution context across calls.
        """
        return self._send({"cmd": "executeModuleCode", "xml": moduleXml, "path": modulePath, "code": code, "contextKey": contextKey})

    def executeCode(self, code: str, contextKey: str = "") -> dict:
        """Execute host-side Python code and return JSON-serializable context."""
        return self._send({"cmd": "executeCode", "code": code, "contextKey": contextKey})

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _send(self, msg: dict, timeout_seconds: float = DEFAULT_RUN_TIMEOUT) -> dict:
        """Push *msg* to the server and block until a matching reply arrives on the SUB socket.

        The lock is held only for the brief PUSH send, never during the wait,
        so processEvents() cannot cause a deadlock even when called from the GUI thread.
        """
        runId = uuid.uuid4().hex
        msg = {**msg, "id": runId}

        event_obj = threading.Event()
        result = {}

        with self._replyLock:
            self._pendingReplies[runId] = (event_obj, result)

        # Send — hold the lock only for the push itself.
        with self._lock:
            if self._stopping or self._push.closed:
                with self._replyLock:
                    self._pendingReplies.pop(runId, None)
                return {"ok": False, "error": "connection stopping"}
            try:
                self._push.send_string(json.dumps(msg))
            except zmq.ZMQError:
                with self._replyLock:
                    self._pendingReplies.pop(runId, None)
                return {"ok": False, "error": "socket error during send"}

        # Wait for the SUB listener to deliver the reply.
        app = QApplication.instance()
        isGuiThread = app and app.thread() == QThread.currentThread()

        if isGuiThread:
            deadline = time.time() + timeout_seconds
            while not event_obj.is_set():
                if self._stopping:
                    break
                if time.time() > deadline:
                    with self._replyLock:
                        self._pendingReplies.pop(runId, None)
                    self._emitConnectionLostOnce("Server stopped replying (request timed out).")
                    return {"ok": False, "error": "server timeout"}
                event_obj.wait(timeout=0.05)   # 50 ms poll; gives Qt time to process signals
                app.processEvents()
        else:
            event_obj.wait(timeout=timeout_seconds)

        with self._replyLock:
            self._pendingReplies.pop(runId, None)

        if not result:
            if not self._stopping:
                self._emitConnectionLostOnce("Server stopped replying (request timed out).")
            return {"ok": False, "error": "server timeout"}

        return result.get("reply", {"ok": False, "error": "empty reply"})

    def _listen(self):
        """Persistent daemon thread that forwards ALL PUB events as Qt signals."""
        try:
            while self._running:
                try:
                    if self._sub.poll(timeout=200):    # ms
                        try:
                            ev = json.loads(self._sub.recv_string())
                            self._touchSubActivity()
                            self._dispatchSignal(ev)
                        except Exception as e:
                            self.onError.emit(f"Error processing PUB event: {e}", traceback.format_exc())
                            continue
                    else:
                        with self._subActivityLock:
                            idle = time.monotonic() - self._lastSubActivityMonotonic
                        if idle >= SUB_STALE_TIMEOUT_SEC:
                            self._emitConnectionLostOnce(
                                "No messages from host for too long; the host may have stopped or the network failed."
                            )
                            continue
                except zmq.ZMQError:
                    if self._running:
                        self._emitConnectionLostOnce("PUB connection error (host closed or network lost).")
                    break
                except Exception as e: # Catch any other exceptions that might occur during poll or processing
                    self.onError.emit(f"Unexpected error in client SUB listener: {e}", traceback.format_exc())
                    continue
        finally:
            try:
                self._sub.close(linger=0)
            except Exception:
                pass

    def _dispatchSignal(self, ev: dict):
        """Emit the appropriate Qt signal for the incoming event."""
        event = ev.get("event")
        self.onAnyEvent.emit(ev)

        if event == "runCallback":
            path = ev.get("path", "")
            self.onRunCallback.emit(path)

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
                    entry = self._pendingReplies.get(runId)
                if entry:
                    event_obj, result = entry
                    result["reply"] = ev
                    event_obj.set()

        elif event == "heartbeat":
            pass

