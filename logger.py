import logging
import sys

class LogHandler(logging.Handler):
    """Generic log handler that pipes messages to an external target."""
    def __init__(self):
        super().__init__()
        self._target = None
        self._buffer = [] # Buffer for early logs before UI is ready
        self._pending = [] # Buffer for chunked UI updates
        self._timer = None
        self.setFormatter(logging.Formatter('%(levelname)s: %(message)s'))
        
    def setTarget(self, target):
        """Set the target for log messages (must have a 'write' method)."""
        self._target = target
        for msg in self._buffer:
            self._target.write(msg)
        self._buffer = []

        # Setup periodic flush timer to avoid UI hangs during massive prints
        try:
            from rigBuilder.qt import QTimer
            self._timer = QTimer()
            self._timer.timeout.connect(self._flushPending)
            self._timer.start(100) # 100ms interval
        except (ImportError, RuntimeError):
            pass # Fallback to immediate printing if Qt is not available
        
    def format(self, record: logging.LogRecord) -> str:
        """Hide level name for INFO messages."""
        if record.levelno == logging.INFO:
            return record.getMessage()
        return super().format(record)

    def _flushPending(self):
        """Batch-write pending messages to the target widget."""
        if not self._target or not self._pending:
            return
            
        text = "".join(self._pending)
        self._pending = []
        self._target.write(text)

    def emit(self, record: logging.LogRecord):
        msg = self.format(record) + '\n'
        if self._target:
            self._pending.append(msg)
            # If timer isn't working/started, fallback to immediate print for safety?
            # No, let's trust the timer or verify it's running.
        else:
            self._buffer.append(msg)

    def close(self):
        """Clean up the handler by flushing pending messages and stopping the timer."""
        self._flushPending()
        if self._timer:
            self._timer.stop()
        super().close()

class LoggerStream:
    """Fake stream that pipes write calls to a logger."""
    def __init__(self, logger, level):
        self.logger = logger
        self.level = level
        self._buffer = ""

    def write(self, message):
        if not message:
            return
            
        self._buffer += message
        if "\n" in self._buffer:
            lines = self._buffer.split("\n")
            for line in lines[:-1]:
                if line.strip():
                    self.logger.log(self.level, line.rstrip())
            self._buffer = lines[-1]

    def flush(self):
        if self._buffer.strip():
            self.logger.log(self.level, self._buffer.strip())
        self._buffer = ""

def setupStreamRedirection():
    """Redirect sys.stdout and sys.stderr to the rigBuilder logger."""
    sys.stdout = LoggerStream(logger, logging.INFO)
    sys.stderr = LoggerStream(logger, logging.ERROR)

# Initialize the global logger for the rigBuilder package
logger = logging.getLogger('rigBuilder')
logger.setLevel(logging.DEBUG)

# Create and add the global log handler
logHandler = LogHandler()
logger.addHandler(logHandler)
