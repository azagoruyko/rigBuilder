import sys
import re
import json
from contextlib import contextmanager

def clamp(val: float, low: float, high: float) -> float:
    """Clamp value between low and high bounds."""
    return max(low, min(high, val))

def replaceSpecialChars(text: str) -> str:
    """Replace special characters with underscores."""
    return re.sub("[^a-zA-Z0-9_]", "_", text)

def findUniqueName(name: str, existingNames: list[str]) -> str:
    """Find unique name by appending numbers if needed."""
    nameNoNum = re.sub(r"\d+$", "", name)  # remove trailing numbers
    newName = name
    i = 1
    while newName in existingNames:
        newName = nameNoNum + str(i)
        i += 1
    return newName
    
def replacePairs(pairs: list[tuple[str, str]], text: str) -> str:
    """Replace text using pairs of (pattern, replacement)."""
    for k, v in pairs:
        text = re.sub(k, v, text)
    return text

def smartConversion(x: str):
    """Try to parse string as JSON, fallback to string."""
    try:
        return json.loads(x)
    except ValueError:
        return str(x)

def fromSmartConversion(x) -> str:
    """Convert value to string, using JSON for non-strings."""
    return json.dumps(x) if not isinstance(x, str) else x
    
def copyJson(data):
    """Create deep copy of JSON-compatible data structures."""
    if data is None:
        return None

    elif type(data) in [list, tuple]:
        return [copyJson(x) for x in data]

    elif type(data) == dict:
        return {k: copyJson(data[k]) for k in data}

    elif type(data) in [int, float, bool, str]:
        return data

    else:
        raise TypeError("Data of '{}' type is not JSON compatible: {}".format(type(data), str(data)))
    
@contextmanager
def captureOutput(stream):
    """Context manager to capture stdout/stderr to a stream."""
    default_stdout = sys.stdout
    default_stderr = sys.stderr

    sys.stdout = stream
    sys.stderr = stream
    yield
    sys.stdout = default_stdout
    sys.stderr = default_stderr

def printErrorStack():
    """Print formatted error stack trace."""
    exc_type, exc_value, exc_traceback = sys.exc_info()

    tbs = []
    tb = exc_traceback
    while tb:
        tbs.append(tb)
        tb = tb.tb_next

    skip = True
    indent = "  "
    for tb in tbs:
        if tb.tb_frame.f_code.co_filename == "<string>":
            skip = False

        if not skip:
            print("{}{}, {}, in line {},".format(indent, tb.tb_frame.f_code.co_filename, tb.tb_frame.f_code.co_name, tb.tb_lineno))
            indent += "  "
    print("Error: {}".format(exc_value))

def findOpeningBracketPosition(text: str, offset: int, brackets: str = "{(["):
    """Find position of opening bracket matching the bracket at offset."""
    openingBrackets = "{(["
    closingBrackets = "})]"
    stack = [0 for i in range(len(openingBrackets))]

    if offset < 0 or offset >= len(text):
        return None

    if text[offset] in closingBrackets:
        offset -= 1

    for i in range(offset, -1, -1):
        c = text[i]

        if c in brackets and c in openingBrackets and stack[openingBrackets.index(c)] == 0:
            return i

        elif c in openingBrackets:
            stack[openingBrackets.index(c)] += 1

        elif c in closingBrackets:
            stack[closingBrackets.index(c)] -= 1

def findClosingBracketPosition(text: str, offset: int, brackets: str = "})]"):
    """Find position of closing bracket matching the bracket at offset."""
    openingBrackets = "{(["
    closingBrackets = "})]"
    stack = [0 for _ in range(len(openingBrackets))]

    if offset < 0 or offset >= len(text):
        return None

    if text[offset] in openingBrackets:
        offset += 1

    for i in range(offset, len(text)):
        c = text[i]

        if c in brackets and c in closingBrackets and stack[closingBrackets.index(c)] == 0:
            return i

        elif c in openingBrackets:
            stack[openingBrackets.index(c)] += 1

        elif c in closingBrackets:
            stack[closingBrackets.index(c)] -= 1

def findBracketSpans(text: str, offset: int):
    """Find opening and closing bracket positions around offset."""
    s = findOpeningBracketPosition(text, offset, "{([")
    if s is not None:
        matchingClosingBracket = {"{": "}", "(": ")", "[": "]"}[text[s]]
        e = findClosingBracketPosition(text, offset, matchingClosingBracket)
    else:
        e = findClosingBracketPosition(text, offset, "})]")
    return (s, e)

class SimpleUndo:
    """Simple undo system for tracking operations."""
    
    def __init__(self):
        self.undoEnabled = True
        
        self._undoStack = []
        self._undoTempStack = []
        self._tempEditBlockName = ""
        self._undoOrder = 0  # undo inc/dec this

    def isEmpty(self) -> bool:
        return not self._undoStack

    def flush(self):
        """Clear all undo history."""
        self._undoStack = []
        self._undoTempStack = []

    def isInEditBlock(self) -> bool:        
        return self._undoOrder > 0
    
    def beginEditBlock(self, name: str = "temp"):
        """Start grouping operations into single undo block."""
        self._tempEditBlockName = name
        self._undoOrder += 1

    def endEditBlock(self):
        """End edit block and commit grouped operations."""
        self._undoOrder -= 1

        # append all temporary operations as a single undo function
        if self._undoTempStack and not self.isInEditBlock():
            def f(stack=self._undoTempStack):
                for _, func in stack:
                    func()

            self.push(self._tempEditBlockName, f)
            self._undoTempStack = []

    def getLastOperationName(self):
        """Get name of last operation."""
        if not self._undoStack:
            return
        cmd = self._undoStack[-1][0] 
        return re.match(r"(.+)\s+#", cmd).group(1)

    def push(self, name: str, undoFunc, operationId=None):
        """Push new operation to undo stack."""
        def _getLastOperation():
            if self.isInEditBlock():
                return self._undoTempStack[-1] if self._undoTempStack else None
            else:
                return self._undoStack[-1] if self._undoStack else None

        if not self.undoEnabled:
            return

        lastOp = _getLastOperation()

        cmd = "{} #{}".format(name, operationId)  # generate unique command name
        if operationId is not None and lastOp and lastOp[0] == cmd:  # the same operation, do not add
            pass
        else:
            if self.isInEditBlock():
                self._undoTempStack.append((cmd, undoFunc))
            else:
                self._undoStack.append((cmd, undoFunc))

    def undo(self):
        """Execute last undo operation."""
        if not self._undoStack:
            print("Nothing to undo")
        else:
            self.undoEnabled = False  # prevent undoing while undoing

            while True and self._undoStack:
                _, undoFunc = self._undoStack.pop()

                if callable(undoFunc):
                    undoFunc()
                    break

            self.undoEnabled = True