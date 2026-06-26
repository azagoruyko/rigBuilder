import logging
import sys
import os
from logging.handlers import RotatingFileHandler
from .settings import RIG_BUILDER_USER_PATH

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

        # The target (e.g. UI) is now responsible for calling flush() periodically
        # to ensure thread safety and avoid UI hangs.

    def format(self, record: logging.LogRecord) -> str:
        """Hide level name for INFO messages."""
        if record.levelno == logging.INFO:
            return record.getMessage()
        return super().format(record)

    def flush(self):
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
        """Clean up the handler by flushing pending messages."""
        self.flush()
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
        # If the message ends with a newline, it's likely a complete logical unit
        # or a series of lines. We log it all at once to get a single timestamp.
        if "\n" in message:
            self.flush()

    def flush(self):
        if self._buffer.rstrip():
            self.logger.log(self.level, self._buffer.rstrip())
        self._buffer = ""

def customExcepthook(exc_type, exc_value, exc_traceback):
    """Log uncaught exceptions as a single entry with a single timestamp."""
    import traceback
    if issubclass(exc_type, KeyboardInterrupt):
        sys.__excepthook__(exc_type, exc_value, exc_traceback)
        return

    error_msg = "".join(traceback.format_exception(exc_type, exc_value, exc_traceback))
    logger.error(error_msg.rstrip())

def setupExcepthook():
    """Install the custom excepthook."""
    sys.excepthook = customExcepthook

def setupStreamRedirection():
    """Redirect sys.stdout and sys.stderr to the rigBuilder logger."""
    sys.stdout = LoggerStream(logger, logging.INFO)
    sys.stderr = LoggerStream(logger, logging.ERROR)

# Initialize the logger
logger = logging.getLogger('rigBuilder')
logger.setLevel(logging.DEBUG)

# Create and add the UI log handler
logHandler = LogHandler()
logger.addHandler(logHandler)

# Add file logging
logFile = os.path.join(RIG_BUILDER_USER_PATH, "log.txt")
os.makedirs(RIG_BUILDER_USER_PATH, exist_ok=True)

fileHandler = RotatingFileHandler(logFile, maxBytes=5 * 1024 * 1024, backupCount=0, encoding='utf-8')
fileHandler.setFormatter(logging.Formatter('%(asctime)s, %(levelname)s: %(message)s', datefmt='%Y-%m-%d %H:%M:%S'))
logger.addHandler(fileHandler)
