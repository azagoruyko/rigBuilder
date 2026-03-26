import logging

class LogHandler(logging.Handler):
    """Generic log handler that pipes messages to an external target."""
    def __init__(self):
        super().__init__()
        self._target = None
        self.setFormatter(logging.Formatter('%(levelname)s: %(message)s'))
        
    def setTarget(self, target):
        """Set the target for log messages (must have a 'write' method)."""
        self._target = target
        
    def format(self, record: logging.LogRecord) -> str:
        """Hide level name for INFO messages."""
        if record.levelno == logging.INFO:
            return record.getMessage()
        return super().format(record)

    def emit(self, record: logging.LogRecord):
        if not self._target:
            return
            
        msg = self.format(record)
        self._target.write(msg + '\n')

# Initialize the global logger for the rigBuilder package
logger = logging.getLogger('rigBuilder')
logger.setLevel(logging.DEBUG)

# Create and add the global log handler
logHandler = LogHandler()
logger.addHandler(logHandler)
