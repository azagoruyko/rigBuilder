import sys
import os
import re
import json
import io
import ast
import stat
import shutil
from contextlib import contextmanager, redirect_stdout, redirect_stderr
from datetime import datetime, timedelta
from typing import List, Any

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
        return json.loads(str(x))
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

def jsonifyContext(context: dict) -> dict:
    """Filter dictionary to include only JSON-serializable values."""
    safe = {}
    for k, v in context.items():
        if k.startswith("__") or callable(v):
            continue

        try:
            # Check if value is JSON-serializable using copyJson
            copyJson(v)
            safe[k] = v
        except (TypeError, Exception):
            continue

    return safe
    
@contextmanager
def captureOutput(stream: io.TextIOBase):
    """Context manager to capture stdout/stderr to a stream."""
    with redirect_stdout(stream), redirect_stderr(stream):
        yield stream

def getErrorStack() -> str:
    """Get formatted error stack trace, skipping internal runner frames."""
    _, _, tb = sys.exc_info()
    if not tb:
        return ""

    out = []
    skip = True
    indent = 0
    while tb:
        f_code = tb.tb_frame.f_code
        filename = f_code.co_filename
        
        # Once we find a non-existent file (usually '<string>' from exec), 
        # we start including frames. No need to check exists() after that.
        if skip and not os.path.exists(filename):
            skip = False

        if not skip:
            out.append(f"{'  ' * indent}{filename}, {f_code.co_name}, in line {tb.tb_lineno},")
            indent += 1
            
        tb = tb.tb_next
    
    if not out:
        return ""
        
    return "\n".join(out)

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

def getRelativeTimeString(mtime: float) -> str:
    """Return a relative time string (e.g. '1 minute ago', '1 week ago') or date."""
    now = datetime.now()
    dt = datetime.fromtimestamp(mtime)
    diff = now - dt
    
    seconds = diff.total_seconds()
    if seconds < 0:
        return dt.strftime("%Y/%m/%d")
        
    minutes = int(seconds // 60)
    hours = int(seconds // 3600)
    days = diff.days
    
    if minutes < 60:
        if minutes < 1:
            return "1 minute ago"
        return "{} minute{} ago".format(minutes, "s" if minutes > 1 else "")
        
    if hours < 24:
        return "{} hour{} ago".format(hours, "s" if hours > 1 else "")
        
    if days < 7:
        if days < 1:
            return "{} hour{} ago".format(hours, "s" if hours > 1 else "")
        return "{} day{} ago".format(days, "s" if days > 1 else "")
        
    return dt.strftime("%Y/%m/%d")

def loadJson(path: str) -> dict:
    """Read a JSON file and return its content as a dictionary."""
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)

def saveJson(path: str, data: dict):
    """Write a dictionary to a JSON file (UTF-8)."""
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)

def executeWithResult(code: str, globalsDict: dict, localsDict: dict = None) -> Any:
    """Execute Python code and return the value of the last expression if it's an ast.Expr."""
    if not code.strip():
        return None

    try:
        tree = ast.parse(code)
    except Exception:
        # Fallback to standard exec if parsing fails (e.g. syntax error that exec will also catch)
        exec(code, globalsDict, localsDict)
        return None

    if not tree.body:
        return None

    lastNode = tree.body[-1]
    if isinstance(lastNode, ast.Expr):
        # Execute everything except the last expression
        if len(tree.body) > 1:
            execTree = ast.Module(body=tree.body[:-1], type_ignores=[])
            exec(compile(execTree, "<string>", "exec"), globalsDict, localsDict)

        # Evaluate the last expression
        evalTree = ast.Expression(body=lastNode.value)
        ast.fix_missing_locations(evalTree)
        return eval(compile(evalTree, "<string>", "eval"), globalsDict, localsDict)
    else:
        # Execute the entire block
        exec(compile(tree, "<string>", "exec"), globalsDict, localsDict)
        return None

def forceRemove(path: str) -> None:
    """Force remove a directory or file, handling read-only flags on Windows."""
    if not os.path.exists(path):
        return

    def onerror(func, p, _excinfo):
        """Clear read-only flag and retry the operation."""
        os.chmod(p, stat.S_IWRITE)
        func(p)

    if os.path.isdir(path):
        shutil.rmtree(path, onerror=onerror)
    else:
        try:
            os.remove(path)
        except OSError:
            os.chmod(path, stat.S_IWRITE)
            os.remove(path)