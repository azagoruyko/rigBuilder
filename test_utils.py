import io
import ast
import pytest
import tempfile
import os

from rigBuilder.utils import (
    clamp,
    replaceSpecialChars,
    findUniqueName,
    replacePairs,
    smartConversion,
    fromSmartConversion,
    copyJson,
    jsonifyContext,
    captureOutput,
    findOpeningBracketPosition,
    findClosingBracketPosition,
    findBracketSpans,
    SimpleUndo,
    getRelativeTimeString,
    loadJson,
    saveJson,
    executeWithResult,
    forceRemove,
    detectHostByCode,
    relativePath,
    displayPath,
)


# ============================================================================
# SCALAR UTILITIES
# ============================================================================

class TestClamp:
    """Tests for clamp()."""

    def testWithinBounds(self):
        """Value inside range is returned unchanged."""
        assert clamp(5.0, 0.0, 10.0) == 5.0

    def testAtLow(self):
        """Value equal to low bound is returned as-is."""
        assert clamp(0.0, 0.0, 10.0) == 0.0

    def testAtHigh(self):
        """Value equal to high bound is returned as-is."""
        assert clamp(10.0, 0.0, 10.0) == 10.0

    def testBelowLow(self):
        """Value below low is clamped to low."""
        assert clamp(-5.0, 0.0, 10.0) == 0.0

    def testAboveHigh(self):
        """Value above high is clamped to high."""
        assert clamp(99.0, 0.0, 10.0) == 10.0


class TestReplaceSpecialChars:
    """Tests for replaceSpecialChars()."""

    def testAlphanumericUnchanged(self):
        """Plain alphanumeric strings pass through unchanged."""
        assert replaceSpecialChars("hello_World123") == "hello_World123"

    def testSpaceReplaced(self):
        """Spaces are replaced with underscores."""
        assert replaceSpecialChars("hello world") == "hello_world"

    def testSymbolsReplaced(self):
        """Punctuation and symbols are replaced with underscores."""
        assert replaceSpecialChars("a.b-c/d") == "a_b_c_d"

    def testEmptyString(self):
        """Empty string returns empty string."""
        assert replaceSpecialChars("") == ""


class TestFindUniqueName:
    """Tests for findUniqueName()."""

    def testNoConflict(self):
        """Name with no conflict is returned unchanged."""
        assert findUniqueName("arm", ["leg", "spine"]) == "arm"

    def testSimpleConflict(self):
        """Conflicting name gets a numeric suffix."""
        assert findUniqueName("arm", ["arm"]) == "arm1"

    def testMultipleConflicts(self):
        """Multiple conflicts increment suffix correctly."""
        result = findUniqueName("arm", ["arm", "arm1", "arm2"])
        assert result == "arm3"

    def testNameWithTrailingNumber(self):
        """Trailing number is stripped before searching for a unique name."""
        # "arm2" strips to "arm", then finds arm, arm1 occupied → returns arm2 (first free)
        result = findUniqueName("arm2", ["arm", "arm1"])
        assert result == "arm2"

    def testEmptyExistingNames(self):
        """No existing names: name is returned as-is."""
        assert findUniqueName("arm", []) == "arm"


class TestReplacePairs:
    """Tests for replacePairs()."""

    def testSinglePair(self):
        """Single regex replacement pair works correctly."""
        assert replacePairs([("a", "b")], "aaa") == "bbb"

    def testMultiplePairs(self):
        """Multiple pairs applied sequentially."""
        result = replacePairs([("foo", "bar"), ("baz", "qux")], "foo baz")
        assert result == "bar qux"

    def testNoPairs(self):
        """Empty pairs list returns text unchanged."""
        assert replacePairs([], "hello") == "hello"


# ============================================================================
# JSON UTILITIES
# ============================================================================

class TestSmartConversion:
    """Tests for smartConversion() and fromSmartConversion()."""

    def testJsonInt(self):
        """Integer string parsed to int."""
        assert smartConversion("42") == 42

    def testJsonList(self):
        """JSON list string parsed to list."""
        assert smartConversion("[1, 2, 3]") == [1, 2, 3]

    def testFallbackToString(self):
        """Non-JSON string returned as-is."""
        assert smartConversion("hello world") == "hello world"

    def testFromSmartConversionString(self):
        """String value returned without JSON encoding."""
        assert fromSmartConversion("hello") == "hello"

    def testFromSmartConversionNonString(self):
        """Non-string value is JSON-encoded."""
        assert fromSmartConversion([1, 2]) == "[1, 2]"
        assert fromSmartConversion(42) == "42"


class TestCopyJson:
    """Tests for copyJson()."""

    def testCopiesDict(self):
        """Dict is deep-copied."""
        data = {"a": [1, 2], "b": {"c": 3}}
        copy = copyJson(data)
        copy["a"].append(99)
        assert data["a"] == [1, 2]

    def testCopiesList(self):
        """List is deep-copied."""
        data = [1, [2, 3]]
        copy = copyJson(data)
        copy[1].append(99)
        assert data[1] == [2, 3]

    def testPrimitivesPassThrough(self):
        """Primitive types are returned as-is."""
        assert copyJson(1) == 1
        assert copyJson(3.14) == 3.14
        assert copyJson(True) is True
        assert copyJson("hello") == "hello"

    def testNoneReturnsNone(self):
        """None returns None."""
        assert copyJson(None) is None

    def testIncompatibleTypeRaisesTypeError(self):
        """Non-JSON-compatible types raise TypeError."""
        with pytest.raises(TypeError):
            copyJson(lambda: None)


class TestJsonifyContext:
    """Tests for jsonifyContext()."""

    def testFiltersCallables(self):
        """Callable values are excluded."""
        ctx = {"a": 1, "fn": lambda: None}
        result = jsonifyContext(ctx)
        assert "fn" not in result
        assert result["a"] == 1

    def testFiltersDunderKeys(self):
        """Keys starting with __ are excluded."""
        ctx = {"__builtins__": {}, "x": 2}
        result = jsonifyContext(ctx)
        assert "__builtins__" not in result
        assert result["x"] == 2

    def testFiltersNonJsonValues(self):
        """Non-JSON-serializable values are excluded."""
        ctx = {"good": [1, 2], "bad": object()}
        result = jsonifyContext(ctx)
        assert "good" in result
        assert "bad" not in result


# ============================================================================
# BRACKET SEARCH
# ============================================================================

class TestBracketSearch:
    """Tests for findOpeningBracketPosition / findClosingBracketPosition / findBracketSpans."""

    def testFindOpeningBracket(self):
        """Finds correct opening bracket position."""
        text = "fn(a, b)"
        # offset is at ')' → finds '(' at index 2
        pos = findOpeningBracketPosition(text, 7)
        assert pos == 2

    def testFindClosingBracket(self):
        """Finds correct closing bracket position."""
        text = "fn(a, b)"
        # offset is at '(' → finds ')' at index 7
        pos = findClosingBracketPosition(text, 2)
        assert pos == 7

    def testFindBracketSpansRoundTrip(self):
        """findBracketSpans returns matching pair of positions."""
        text = "{key: [1, 2]}"
        s, e = findBracketSpans(text, 6)  # offset inside [ ]
        assert text[s] == "["
        assert text[e] == "]"

    def testOpeningBracketOutOfRange(self):
        """Out-of-range offset returns None."""
        text = "(abc)"
        assert findOpeningBracketPosition(text, -1) is None
        assert findOpeningBracketPosition(text, 100) is None

    def testClosingBracketOutOfRange(self):
        """Out-of-range offset returns None."""
        text = "(abc)"
        assert findClosingBracketPosition(text, -1) is None
        assert findClosingBracketPosition(text, 100) is None

    def testNestedBrackets(self):
        """Correctly handles nested brackets."""
        text = "((a + b) * c)"
        # cursor at final ')' at index 12 → matching '(' is at index 0
        pos = findOpeningBracketPosition(text, 12)
        assert pos == 0


# ============================================================================
# SIMPLE UNDO
# ============================================================================

class TestSimpleUndo:
    """Tests for SimpleUndo."""

    def testPushAndUndo(self):
        """Push an operation and undo it."""
        state = {"value": 10}
        undo = SimpleUndo()
        undo.push("set value", lambda: state.update({"value": 10}))
        state["value"] = 99
        undo.undo()
        assert state["value"] == 10

    def testIsEmpty(self):
        """isEmpty() reflects whether there are pending undos."""
        undo = SimpleUndo()
        assert undo.isEmpty() is True
        undo.push("op", lambda: None)
        assert undo.isEmpty() is False

    def testFlush(self):
        """flush() clears all history."""
        undo = SimpleUndo()
        undo.push("op", lambda: None)
        undo.flush()
        assert undo.isEmpty() is True

    def testEditBlock(self):
        """Operations inside an edit block are grouped into one undo step."""
        calls = []
        undo = SimpleUndo()

        undo.beginEditBlock("grouped")
        undo.push("step1", lambda: calls.append("undo1"))
        undo.push("step2", lambda: calls.append("undo2"))
        undo.endEditBlock()

        assert len(undo._undoStack) == 1  # single grouped entry

        undo.undo()
        assert "undo1" in calls
        assert "undo2" in calls

    def testSameOperationIdNotDuplicated(self):
        """Pushing the same operationId twice doesn't create duplicate entries."""
        undo = SimpleUndo()
        undo.push("op", lambda: None, operationId="same")
        undo.push("op", lambda: None, operationId="same")
        assert len(undo._undoStack) == 1

    def testUndoWhenDisabled(self):
        """Operations pushed while undoEnabled=False are silently dropped."""
        undo = SimpleUndo()
        undo.undoEnabled = False
        undo.push("op", lambda: None)
        assert undo.isEmpty() is True

    def testGetLastOperationName(self):
        """getLastOperationName() returns the name portion without the #id suffix."""
        undo = SimpleUndo()
        undo.push("myOperation", lambda: None, operationId=42)
        assert undo.getLastOperationName() == "myOperation"

    def testUndoOnEmptyStack(self, capsys):
        """Calling undo() on empty stack prints a message without crashing."""
        undo = SimpleUndo()
        undo.undo()
        captured = capsys.readouterr()
        assert "Nothing to undo" in captured.out

    def testNestedEditBlocks(self):
        """Nested beginEditBlock/endEditBlock: only the outer close commits."""
        calls = []
        undo = SimpleUndo()

        undo.beginEditBlock("outer")
        undo.beginEditBlock("inner")
        undo.push("inner_step", lambda: calls.append("inner"))
        undo.endEditBlock()  # inner closes → still in outer block
        assert undo.isEmpty() is True  # not committed yet

        undo.endEditBlock()  # outer closes → now committed
        assert len(undo._undoStack) == 1


# ============================================================================
# FILE UTILITIES
# ============================================================================

class TestLoadSaveJson:
    """Tests for loadJson() / saveJson()."""

    def testRoundTrip(self, tmp_path):
        """Data saved and loaded back is identical."""
        path = str(tmp_path / "data.json")
        data = {"key": [1, 2, 3], "nested": {"a": True}}
        saveJson(path, data)
        loaded = loadJson(path)
        assert loaded == data

    def testUnicodeRoundTrip(self, tmp_path):
        """Unicode characters survive save/load."""
        path = str(tmp_path / "unicode.json")
        data = {"text": "привет мир"}
        saveJson(path, data)
        loaded = loadJson(path)
        assert loaded["text"] == "привет мир"


class TestForceRemove:
    """Tests for forceRemove()."""

    def testRemovesDirectory(self, tmp_path):
        """Removes a non-empty directory."""
        d = tmp_path / "subdir"
        d.mkdir()
        (d / "file.txt").write_text("hello")
        forceRemove(str(d))
        assert not d.exists()

    def testRemovesFile(self, tmp_path):
        """Removes a single file."""
        f = tmp_path / "file.txt"
        f.write_text("data")
        forceRemove(str(f))
        assert not f.exists()

    def testNonexistentPathIsNoop(self, tmp_path):
        """Calling on a nonexistent path does nothing (no exception)."""
        forceRemove(str(tmp_path / "ghost"))


# ============================================================================
# CODE EXECUTION
# ============================================================================

class TestExecuteWithResult:
    """Tests for executeWithResult()."""

    def testSimpleExpression(self):
        """Returns the value of the final expression."""
        result = executeWithResult("1 + 2", {})
        assert result == 3

    def testStatementReturnsNone(self):
        """Pure statement (assignment) returns None."""
        globs = {}
        result = executeWithResult("x = 42", globs)
        assert result is None
        assert globs["x"] == 42

    def testMixedCodeReturnsLastExpression(self):
        """Statement followed by expression returns expression value."""
        globs = {}
        result = executeWithResult("x = 5\nx * 2", globs)
        assert result == 10

    def testEmptyCodeReturnsNone(self):
        """Empty string returns None without error."""
        result = executeWithResult("   ", {})
        assert result is None

    def testSyntaxErrorIsHandled(self):
        """Syntax-error code raises SyntaxError via exec fallback."""
        with pytest.raises(SyntaxError):
            executeWithResult("def f(\n", {})


# ============================================================================
# HOST DETECTION
# ============================================================================

class TestDetectHostByCode:
    """Tests for detectHostByCode()."""

    def testMayaDetected(self):
        """Maya import triggers maya host."""
        assert detectHostByCode("import maya.cmds as mc") == "maya"

    def testBlenderDetected(self):
        """Blender import triggers blender host."""
        assert detectHostByCode("import bpy") == "blender"

    def testHoudiniDetected(self):
        """Houdini import triggers houdini host."""
        assert detectHostByCode("import hou") == "houdini"

    def testUnrealDetected(self):
        """Unreal import triggers unreal host."""
        assert detectHostByCode("import unreal") == "unreal"

    def testNoHostForGenericCode(self):
        """Code with no DCC imports returns empty string."""
        assert detectHostByCode("import os\nimport sys") == ""

    def testEmptyCodeReturnsEmpty(self):
        """Empty code returns empty string."""
        assert detectHostByCode("") == ""

    def testCommentLinesSkipped(self):
        """Comment lines with DCC keywords are ignored."""
        code = "# import maya.cmds\nimport os\nx = 1"
        # first non-comment non-blank line is 'import os' (generic) → stops
        assert detectHostByCode(code) == ""


# ============================================================================
# PATH UTILITIES
# ============================================================================

class TestRelativePath:
    """Tests for relativePath()."""

    def testChildPathBecomesRelative(self):
        """Path under root returns relative portion."""
        root = os.path.join("projects", "rig")
        path = os.path.join("projects", "rig", "modules", "arm.rb")
        result = relativePath(path, root)
        assert result == os.path.join("modules", "arm.rb")

    def testPathOutsideRootUnchanged(self):
        """Path not under root is returned normalised but unchanged."""
        root = os.path.join("projects", "rig")
        path = os.path.join("other", "file.rb")
        result = relativePath(path, root)
        assert result == os.path.normpath(path)

    def testCaseInsensitive(self):
        """Case-insensitive root matching works (implementation uses .lower())."""
        root = os.path.join("Projects", "Rig")
        path = os.path.join("projects", "rig", "arm.rb")
        result = relativePath(path, root)
        assert result == "arm.rb"


class TestDisplayPath:
    """Tests for displayPath()."""

    def testShortPathUnchanged(self):
        """Paths with ≤3 components are returned as-is (with forward slashes)."""
        path = os.path.join("a", "b", "c")
        result = displayPath(path)
        assert result == "a/b/c"

    def testLongPathTruncated(self):
        """Paths with >3 components are truncated with '../' prefix."""
        path = os.path.join("a", "b", "c", "d", "e")
        result = displayPath(path)
        assert result.startswith("../")
        assert result.endswith("c/d/e")


# ============================================================================
# CAPTURE OUTPUT
# ============================================================================

class TestCaptureOutput:
    """Tests for captureOutput()."""

    def testCapturesStdout(self):
        """print() output is captured into the provided stream."""
        stream = io.StringIO()
        with captureOutput(stream):
            print("hello capture")
        assert "hello capture" in stream.getvalue()

    def testCapturesStderr(self):
        """stderr writes are captured into the provided stream."""
        import sys
        stream = io.StringIO()
        with captureOutput(stream):
            sys.stderr.write("err line\n")
        assert "err line" in stream.getvalue()

    def testYieldsTheSameStream(self):
        """The context manager yields back the stream that was passed in."""
        stream = io.StringIO()
        with captureOutput(stream) as s:
            assert s is stream

    def testExceptionPropagates(self):
        """Exceptions inside the context manager propagate normally."""
        stream = io.StringIO()
        with pytest.raises(ValueError):
            with captureOutput(stream):
                raise ValueError("boom")


# ============================================================================
# RELATIVE TIME STRING
# ============================================================================

class TestGetRelativeTimeString:
    """Tests for getRelativeTimeString()."""

    def _mtime(self, **kwargs):
        """Return a POSIX timestamp offset from now by the given timedelta kwargs."""
        from datetime import datetime, timedelta
        return (datetime.now() - timedelta(**kwargs)).timestamp()

    def testUnderOneMinute(self):
        """Timestamps within the last minute report '1 minute ago'."""
        mtime = self._mtime(seconds=30)
        assert getRelativeTimeString(mtime) == "1 minute ago"

    def testSingleMinute(self):
        """Exactly one minute ago reports '1 minute ago' (no plural)."""
        mtime = self._mtime(minutes=1)
        assert getRelativeTimeString(mtime) == "1 minute ago"

    def testMultipleMinutes(self):
        """Several minutes ago uses plural form."""
        mtime = self._mtime(minutes=5)
        result = getRelativeTimeString(mtime)
        assert result == "5 minutes ago"

    def testSingleHour(self):
        """One hour ago reports '1 hour ago' (no plural)."""
        mtime = self._mtime(hours=1, minutes=1)
        result = getRelativeTimeString(mtime)
        assert result == "1 hour ago"

    def testMultipleHours(self):
        """Several hours ago uses plural form."""
        mtime = self._mtime(hours=3)
        result = getRelativeTimeString(mtime)
        assert result == "3 hours ago"

    def testSingleDay(self):
        """One day ago reports '1 day ago' (no plural)."""
        mtime = self._mtime(days=1, hours=1)
        result = getRelativeTimeString(mtime)
        assert result == "1 day ago"

    def testMultipleDays(self):
        """Several days ago (under a week) uses plural form."""
        mtime = self._mtime(days=4)
        result = getRelativeTimeString(mtime)
        assert result == "4 days ago"

    def testOlderThanWeekReturnsDate(self):
        """Timestamps older than a week return a formatted date string."""
        mtime = self._mtime(days=10)
        result = getRelativeTimeString(mtime)
        # Should look like YYYY/MM/DD
        import re
        assert re.match(r"\d{4}/\d{2}/\d{2}", result)

    def testFutureTimestampReturnsDate(self):
        """Future timestamps return a formatted date string."""
        mtime = self._mtime(days=-5)  # 5 days in the future
        result = getRelativeTimeString(mtime)
        import re
        assert re.match(r"\d{4}/\d{2}/\d{2}", result)
