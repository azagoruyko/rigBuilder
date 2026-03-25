"""Rig Builder client: connects to a host server and streams events via Qt signals."""
import json
import uuid
import threading
import time
import zmq

from ..qt import QObject, Signal, QApplication, QThread, QTimer

DEFAULT_RUN_TIMEOUT = 86400.0  # 24 hours

# Must stay above server HEARTBEAT_INTERVAL_SEC * 3 (see server.hosts.__init__).
# Use a wider window to reduce false disconnects during heavy host workloads.
SUB_STALE_TIMEOUT_SEC = 10.0

class HostClient(QObject):
    """ZeroMQ client that connects to a single host server.

    Uses two sockets:
        REQ  — sends commands (ping, runModule, executeModuleCode, executeCode), receives replies.
        SUB  — receives asynchronous event stream (print, error, progress, …).
    """

    onAnyEvent = Signal(dict)
    onRunCallback = Signal(str)
    onPrint = Signal(str)
    onError = Signal(str, str)
    onConnectionLost = Signal(str)

    beginProgress = Signal(str, int)
    stepProgress = Signal(int, str)
    endProgress = Signal()

    def __init__(self, address: str, rep_port: int, pub_port: int, parent=None):
        super().__init__(parent)
        self._address = address
        self._rep_port = rep_port
        self._pub_port = pub_port
        self._ctx = zmq.Context.instance()

        self._req = self._ctx.socket(zmq.REQ)
        self._sub = self._ctx.socket(zmq.SUB)
        self._req.setsockopt(zmq.RCVTIMEO, 1000)   # 1 s receive timeout
        self._req.connect(f"tcp://{address}:{rep_port}")
        self._sub.connect(f"tcp://{address}:{pub_port}")
        self._sub.setsockopt_string(zmq.SUBSCRIBE, "")   # subscribe to all

        self._lock = threading.Lock()   # serialise REQ sends
        self._subActivityLock = threading.Lock()
        self._connLostLock = threading.Lock()
        self._lastSubActivityMonotonic = time.monotonic()
        self._connectionLostEmitted = False
        self._stopping = False

        self._running = True
        self._listener_thread = threading.Thread(target=self._listen, daemon=True)
        self._listener_thread.start()

        self._staleCheckTimer = QTimer(self)
        self._staleCheckTimer.setInterval(1000)
        self._staleCheckTimer.timeout.connect(self._checkSubStale)
        self._staleCheckTimer.start()

    def stop(self):
        """Stop the listener thread and close the sockets."""
        self._stopping = True
        self._running = False
        self._staleCheckTimer.stop()

        try:
            self._req.close(linger=0)
            self._sub.close(linger=0)
        except Exception:
            pass

    def _touchSubActivity(self):
        with self._subActivityLock:
            self._lastSubActivityMonotonic = time.monotonic()

    def _checkSubStale(self):
        with self._subActivityLock:
            idle = time.monotonic() - self._lastSubActivityMonotonic
        if idle >= SUB_STALE_TIMEOUT_SEC:
            self._emitConnectionLostOnce(
                "No messages from host for too long; the host may have stopped or the network failed.",
            )

    def _emitConnectionLostOnce(self, reason: str):
        with self._connLostLock:
            if self._stopping or self._connectionLostEmitted:
                return
            self._connectionLostEmitted = True

        if QThread.currentThread() is self.thread():
            self._deliverConnectionLost(reason)

        else:
            QTimer.singleShot(0, self, lambda r=reason: self._deliverConnectionLost(r))

    def _deliverConnectionLost(self, reason: str):
        self._staleCheckTimer.stop()
        if self._stopping:
            return

        self.onConnectionLost.emit(reason)

    def _recreateReqSocket(self):
        """Recreate the REQ socket to reset the state machine after a timeout."""
        try:
            self._req.close(linger=0)
        except Exception:
            pass

        self._req = self._ctx.socket(zmq.REQ)
        self._req.setsockopt(zmq.RCVTIMEO, 1000)
        self._req.connect(f"tcp://{self._address}:{self._rep_port}")

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def ping(self) -> dict:
        """Ping the server. Returns {"ok": True, "host": "…", "version": "…"}."""
        return self._send({"cmd": "ping"}, timeout_seconds=1.0)

    def runModule(self, moduleXml: str, modulePath: str) -> dict:
        """Run module XML on the host within the context of moduleXml; blocks until finished.
        Returns {"ok": True, "xml": "…"} or an error dict.
        """
        runId = uuid.uuid4().hex
        return self._send(
            {"cmd": "runModule", "xml": moduleXml, "path": modulePath, "id": runId},
            timeout_seconds=DEFAULT_RUN_TIMEOUT,
        )

    def executeModuleCode(self, moduleXml: str, modulePath: str, code: str) -> dict:
        """Execute a Python snippet against a module found by path in the moduleXml tree on the host.
        Returns {"ok": True, "context": {…}, "xml": "…"} or {"ok": False, "error": "…"}.
        """
        runId = uuid.uuid4().hex
        return self._send({"cmd": "executeModuleCode", "xml": moduleXml, "path": modulePath, "code": code, "id": runId})

    def executeCode(self, code: str) -> dict:
        """Execute host-side Python code and return JSON-serializable context."""
        runId = uuid.uuid4().hex
        return self._send({"cmd": "executeCode", "code": code, "id": runId}, timeout_seconds=DEFAULT_RUN_TIMEOUT)

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _send(self, msg: dict, timeout_seconds: float = 5.0) -> dict:
        with self._lock:
            prev_rcvtimeo = self._req.getsockopt(zmq.RCVTIMEO)
            try:
                self._req.setsockopt(zmq.RCVTIMEO, int(timeout_seconds * 1000))
                self._req.send_string(json.dumps(msg))
                # If we are in the main thread (where QApplication lives),
                # we should poll and process events to keep the UI alive.
                # This allows progress/log signals from the SUB thread to be processed.

                app = QApplication.instance()
                isGuiThread = app and app.thread() == QThread.currentThread()

                if isGuiThread:
                    deadline = time.time() + timeout_seconds
                    while True:
                        if self._req.poll(timeout=100):
                            break

                        if time.time() > deadline:
                            self._recreateReqSocket()
                            self._emitConnectionLostOnce("Server stopped replying (request timed out).")
                            return {"ok": False, "error": "server timeout (poll)"}

                        app.processEvents()

                else:
                    if not self._req.poll(timeout=int(timeout_seconds * 1000)):
                        self._recreateReqSocket()
                        self._emitConnectionLostOnce("Server stopped replying (request timed out).")
                        return {"ok": False, "error": "server timeout (poll)"}

                try:
                    return json.loads(self._req.recv_string())
                except zmq.Again:
                    self._recreateReqSocket()
                    self._emitConnectionLostOnce("Server stopped replying (request timed out).")
                    return {"ok": False, "error": "server timeout"}
            finally:
                self._req.setsockopt(zmq.RCVTIMEO, prev_rcvtimeo)

    def _listen(self):
        """Persistent daemon thread that forwards ALL PUB events as Qt signals."""
        while self._running:
            try:
                if self._sub.poll(timeout=200):    # ms
                    try:
                        ev = json.loads(self._sub.recv_string())
                        self._touchSubActivity()
                        self._dispatchSignal(ev)
                    except Exception:
                        continue
            except zmq.ZMQError:
                if self._running:
                    self._emitConnectionLostOnce("PUB connection error (host closed or network lost).")
                break
            except Exception: # Catch any other exceptions that might occur during poll or processing
                continue

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

        elif event == "heartbeat":
            pass

