"""Execution context lifetime across host requests."""

import pytest

from rigBuilder.core import Module
from rigBuilder.core.settings import Settings
from rigBuilder.host import runner


@pytest.fixture(autouse=True)
def cleanContexts():
    """Keep saved host variables isolated between tests."""
    runner._interactiveContexts.clear()
    yield
    runner._interactiveContexts.clear()


def execute(kind, code, key):
    """Run code through any of the three host execution entry points."""
    events = []
    if kind == "code":
        return runner.executeCode(code, events.append, "test", key)

    module = Module()
    if kind == "snippet":
        return runner.executeModuleCode(module.toXml(), ".", code, events.append, "test", key)

    module.setRunCode(code)
    return runner.runModule(module.toXml(), ".", events.append, "test", key)


@pytest.mark.parametrize("kind", ["code", "snippet", "module"])
@pytest.mark.parametrize("key", ["", "global"])
def testContextLifetime(kind, key):
    """Only persistent requests can reuse variables from earlier runs."""
    assert execute(kind, "previousValue = 42", key)["ok"]
    reply = execute(kind, "assert previousValue == 42", key)
    assert reply["ok"] == bool(key)
    if not key:
        assert "previousValue" in reply["error"]
        assert not runner._interactiveContexts


def testResetContext():
    """Reset prevents old variables from returning when persistence resumes."""
    assert execute("code", "previousValue = 42", "global")["ok"]
    assert runner.resetContext()["ok"]
    assert not execute("code", "previousValue", "global")["ok"]


def testFreshRunIgnoresSavedContext():
    """A fresh request cannot see variables in an existing persistent context."""
    assert execute("code", "previousValue = 42", "global")["ok"]
    assert not execute("code", "previousValue", "")["ok"]


def testTreeSharesContextWithinFreshRun():
    """Parent variables remain available to children within one fresh run."""
    root = Module()
    root.setRunCode("parentValue = 42")
    child = Module()
    child.setRunCode("assert parentValue == 42")
    root.addChild(child)
    events = []
    assert runner.runModule(root.toXml(), ".", events.append, "test")["ok"]
    assert not runner._interactiveContexts


def testPersistContextSettings(tmp_path):
    """Old settings default to fresh runs; explicit persistence survives saving."""
    settings = Settings()
    settings.fromDict({"trackHistory": False})
    assert settings.persistContext is False
    settings.persistContext = True
    path = str(tmp_path / "settings.json")
    settings.save(path)
    restored = Settings()
    restored.load(path)
    assert restored.persistContext is True
