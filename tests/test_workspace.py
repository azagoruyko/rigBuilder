import os
import json
import shutil
import pytest

from rigBuilder.core.workspace import WorkspaceFile, Workspace, flattenModules
from rigBuilder.core import Module, Attribute
from rigBuilder.core.settings import RIG_BUILDER_WORKSPACES_PATH


# ============================================================================
# HELPERS
# ============================================================================

def makeModule(name="mod"):
    """Create a named module with no attributes."""
    m = Module()
    m.setName(name)
    return m


def makeAttribute(name="attr", value=1.0):
    """Create a float attribute."""
    a = Attribute()
    a.setName(name)
    a.setCategory("input")
    a.setTemplate("float")
    a.setLocalData({"default": "value", "value": value})
    return a


# ============================================================================
# FIXTURES
# ============================================================================

@pytest.fixture
def wsDir(tmp_path):
    """Isolated temporary directory acting as the workspace root folder."""
    return tmp_path


@pytest.fixture
def workspaceName(tmp_path):
    """
    Yield a unique workspace name backed by a real folder under
    RIG_BUILDER_WORKSPACES_PATH and clean it up after the test.
    """
    name = "_pytest_ws_" + tmp_path.name
    yield name
    folderPath = os.path.join(RIG_BUILDER_WORKSPACES_PATH, name)
    if os.path.exists(folderPath):
        shutil.rmtree(folderPath, ignore_errors=True)


# ============================================================================
# flattenModules
# ============================================================================

class TestFlattenModules:
    """Tests for flattenModules()."""

    def testEmptyList(self):
        """Empty root list returns empty flat list."""
        assert flattenModules([]) == []

    def testSingleRootNoChildren(self):
        """Single root without children returns just that root."""
        m = makeModule("root")
        assert flattenModules([m]) == [m]

    def testDepthFirstOrder(self):
        """Children are yielded depth-first before siblings."""
        root = makeModule("root")
        childA = makeModule("A")
        childB = makeModule("B")
        grandchild = makeModule("A1")

        root.addChild(childA)
        root.addChild(childB)
        childA.addChild(grandchild)

        names = [m.name() for m in flattenModules([root])]
        # DFS: root → A → A1 → B
        assert names == ["root", "A", "A1", "B"]

    def testMultipleRoots(self):
        """Multiple roots are each traversed depth-first."""
        r1 = makeModule("r1")
        r2 = makeModule("r2")
        c1 = makeModule("c1")
        r1.addChild(c1)

        names = [m.name() for m in flattenModules([r1, r2])]
        assert names == ["r1", "c1", "r2"]


# ============================================================================
# WorkspaceFile
# ============================================================================

class TestWorkspaceFile:
    """Tests for WorkspaceFile serialisation round-trip."""

    def testEmptyFileToXml(self):
        """Empty WorkspaceFile serialises to valid XML with a workspace root."""
        xml = WorkspaceFile().toXml()
        assert "<workspace>" in xml
        assert "<modules>" in xml

    def testRoundTripXml(self):
        """Modules and expanded states survive a toXml → fromXml round-trip."""
        wf = WorkspaceFile()
        m = makeModule("arm")
        m.addAttribute(makeAttribute("offset", 3.14))
        wf.modules = [m]
        wf.expanded = [True, False, True]

        restored = WorkspaceFile.fromXml(wf.toXml())

        assert len(restored.modules) == 1
        assert restored.modules[0].name() == "arm"
        assert restored.expanded == [True, False, True]

    def testExpandedOmittedWhenEmpty(self):
        """<expanded> element is omitted when list is empty."""
        assert "<expanded" not in WorkspaceFile().toXml()

    def testSaveAndLoad(self, wsDir):
        """save() + load() produces equivalent content."""
        wf = WorkspaceFile()
        wf.modules = [makeModule("leg")]
        wf.expanded = [False]

        path = str(wsDir / "workspace.rbws")
        wf.save(path)
        loaded = WorkspaceFile.load(path)

        assert len(loaded.modules) == 1
        assert loaded.modules[0].name() == "leg"
        assert loaded.expanded == [False]

    def testFromXmlIgnoresBadModules(self):
        """fromXml() skips modules that fail to deserialise without raising."""
        xml = "<workspace><modules><module/></modules></workspace>"
        wf = WorkspaceFile.fromXml(xml)
        assert isinstance(wf.modules, list)


# ============================================================================
# Workspace — construction
# ============================================================================

class TestWorkspaceInit:
    """Tests for Workspace construction defaults and name handling."""

    def testDefaultNameVariants(self):
        """No-arg and empty-string both default to 'default'."""
        assert Workspace().name == "default"
        assert Workspace("").name == "default"

    def testCustomName(self):
        """Any non-empty name is stored verbatim."""
        ws = Workspace("my_project_v2")
        assert ws.name == "my_project_v2"

    def testFolderPathContainsName(self):
        """folderPath() ends with the workspace name and lives under WORKSPACES_PATH."""
        ws = Workspace("demo")
        assert os.path.basename(ws.folderPath()) == "demo"
        assert ws.folderPath().startswith(RIG_BUILDER_WORKSPACES_PATH)


# ============================================================================
# Workspace — save / load
# ============================================================================

class TestWorkspaceSaveLoad:
    """Tests for Workspace.save() and Workspace.load()."""

    def testSaveCreatesFiles(self, workspaceName):
        """save() creates the folder structure and required files."""
        ws = Workspace(workspaceName)
        ws.save()

        folder = ws.folderPath()
        assert os.path.isdir(folder)
        assert os.path.isfile(os.path.join(folder, "workspace.rbws"))
        assert os.path.isfile(os.path.join(folder, "settings.json"))

    def testRoundTripModules(self, workspaceName):
        """Modules stored in the file survive a save → load cycle."""
        ws = Workspace(workspaceName)
        ws.file.modules = [makeModule("spine")]
        ws.save()

        loaded = Workspace.load(workspaceName)
        assert len(loaded.file.modules) == 1
        assert loaded.file.modules[0].name() == "spine"

    def testRoundTripExpandedState(self, workspaceName):
        """Expanded flags survive save → load; a second save fully overwrites them."""
        ws = Workspace(workspaceName)
        ws.file.expanded = [True, True]
        ws.save()

        ws.file.expanded = [False, False]
        ws.save()

        loaded = Workspace.load(workspaceName)
        assert loaded.file.expanded == [False, False]

    def testCustomSettingPersists(self, workspaceName):
        """A custom settings field survives save → load."""
        ws = Workspace(workspaceName)
        ws.settings.autoSaveInterval = 42
        ws.save()

        assert Workspace.load(workspaceName).settings.autoSaveInterval == 42


# ============================================================================
# Workspace — exists / list
# ============================================================================

class TestWorkspaceExistsAndList:
    """Tests for Workspace.exists() and Workspace.list()."""

    def testExistsReturnsFalseForMissing(self):
        """exists() returns False for a workspace that was never created."""
        assert Workspace.exists("__nonexistent_workspace__") is False

    def testExistsReturnsTrueAfterSave(self, workspaceName):
        """exists() returns True after a workspace is saved."""
        Workspace(workspaceName).save()
        assert Workspace.exists(workspaceName) is True

    def testListIsSorted(self, workspaceName):
        """list() returns workspace names in sorted order."""
        Workspace(workspaceName).save()
        names = Workspace.list()
        assert names == sorted(names)

    def testListExcludesPlainFiles(self, workspaceName):
        """Plain files in the workspaces directory are not listed."""
        Workspace(workspaceName).save()
        strayFile = os.path.join(RIG_BUILDER_WORKSPACES_PATH, "_stray_test_file.txt")
        try:
            with open(strayFile, "w") as f:
                f.write("stray")
            assert "_stray_test_file.txt" not in Workspace.list()
        finally:
            if os.path.exists(strayFile):
                os.remove(strayFile)

    def testListRemovedAfterDelete(self, workspaceName):
        """Workspace appears in list() after save and disappears after delete()."""
        ws = Workspace(workspaceName)
        ws.save()
        assert workspaceName in Workspace.list()
        ws.delete()
        assert workspaceName not in Workspace.list()


# ============================================================================
# Workspace — delete
# ============================================================================

class TestWorkspaceDelete:
    """Tests for Workspace.delete()."""

    def testDeleteRemovesFolderTree(self, workspaceName):
        """delete() removes the entire folder tree and returns True."""
        ws = Workspace(workspaceName)
        ws.save()
        ws.activate()  # ensures history/ and modules/ exist

        historyPath = ws.settings.historyPath
        modulesPath = ws.settings.modulesPath
        assert os.path.isdir(historyPath)

        result = ws.delete()
        assert result is True
        assert not os.path.exists(ws.folderPath())
        assert not os.path.exists(historyPath)
        assert not os.path.exists(modulesPath)

    def testDeleteIsIdempotent(self, workspaceName):
        """Calling delete() on a missing folder is safe and returns True."""
        ws = Workspace(workspaceName)
        ws.save()
        ws.delete()
        assert ws.delete() is True  # second call — folder already gone


# ============================================================================
# Workspace — activate
# ============================================================================

class TestWorkspaceActivate:
    """Tests for Workspace.activate()."""

    def testActivatePopulatesGlobalSettings(self, workspaceName):
        """activate() pushes workspace settings into the global settings singleton."""
        from rigBuilder.core.settings import settings

        ws = Workspace(workspaceName)
        ws.settings.vscode = "vscode-insiders"
        ws.save()
        ws.activate()

        assert settings.vscode == "vscode-insiders"

    def testActivateCreatesRequiredDirs(self, workspaceName):
        """activate() ensures historyPath, modulesPath, and scriptsPath directories exist."""
        ws = Workspace(workspaceName)
        ws.save()
        ws.activate()

        assert os.path.isdir(ws.settings.historyPath)
        assert os.path.isdir(ws.settings.modulesPath)
        assert os.path.isdir(ws.settings.scriptsPath)

    def testSwitchingWorkspacesOverridesSettings(self, tmp_path):
        """Activating a second workspace fully replaces the first workspace's settings."""
        from rigBuilder.core.settings import settings

        name1 = "_pytest_switch_ws1_" + tmp_path.name
        name2 = "_pytest_switch_ws2_" + tmp_path.name
        try:
            ws1 = Workspace(name1)
            ws1.settings.vscode = "code"
            ws1.save()
            ws1.activate()
            assert settings.vscode == "code"

            ws2 = Workspace(name2)
            ws2.settings.vscode = "vim"
            ws2.save()
            ws2.activate()
            assert settings.vscode == "vim"
        finally:
            for name in (name1, name2):
                fp = os.path.join(RIG_BUILDER_WORKSPACES_PATH, name)
                if os.path.exists(fp):
                    shutil.rmtree(fp, ignore_errors=True)


# ============================================================================
# Workspace — load fallback paths
# ============================================================================

class TestWorkspaceLoadFallbacks:
    """Workspace.load() fallback path logic."""

    def testModulesPathFallbackWhenMissing(self, workspaceName):
        """
        If the saved modulesPath no longer exists on disk, load() replaces it
        with <workspaceFolder>/modules.
        """
        ws = Workspace(workspaceName)
        ws.save()

        # Inject a nonexistent path directly into the settings file so that
        # makedirs (called by save) never creates it.
        settingsPath = os.path.join(ws.folderPath(), "settings.json")
        with open(settingsPath, "r", encoding="utf-8") as f:
            data = json.load(f)
        data["modulesPath"] = os.path.join(ws.folderPath(), "nonexistent_dir")
        with open(settingsPath, "w", encoding="utf-8") as f:
            json.dump(data, f)

        loaded = Workspace.load(workspaceName)
        assert loaded.settings.modulesPath == os.path.join(loaded.folderPath(), "modules")

    def testWorkspacePathAlwaysOverridden(self, workspaceName):
        """load() always overwrites workspacePath with the real folder."""
        ws = Workspace(workspaceName)
        ws.settings.workspacePath = os.path.join(ws.folderPath(), "stale_path")
        ws.save()

        assert Workspace.load(workspaceName).settings.workspacePath == ws.folderPath()

    def testHistoryPathAlwaysOverridden(self, workspaceName):
        """load() always overwrites historyPath with <folder>/history."""
        ws = Workspace(workspaceName)
        ws.settings.historyPath = os.path.join(ws.folderPath(), "stale_history")
        ws.save()

        loaded = Workspace.load(workspaceName)
        assert loaded.settings.historyPath == os.path.join(ws.folderPath(), "history")

    def testScriptsPathFallbackWhenMissing(self, workspaceName):
        """
        If the saved scriptsPath no longer exists on disk, load() replaces it
        with <workspaceFolder>/scripts.
        """
        ws = Workspace(workspaceName)
        ws.save()

        settingsPath = os.path.join(ws.folderPath(), "settings.json")
        with open(settingsPath, "r", encoding="utf-8") as f:
            data = json.load(f)
        data["scriptsPath"] = os.path.join(ws.folderPath(), "nonexistent_scripts")
        with open(settingsPath, "w", encoding="utf-8") as f:
            json.dump(data, f)

        loaded = Workspace.load(workspaceName)
        assert loaded.settings.scriptsPath == os.path.join(loaded.folderPath(), "scripts")


# ============================================================================
# Workspace — multiple modules
# ============================================================================

class TestWorkspaceMultipleModules:
    """WorkspaceFile stores and restores multiple modules correctly."""

    def testMultipleModuleOrder(self, workspaceName):
        """Module order is preserved after save → load."""
        names = ["spine", "arm_L", "arm_R", "leg_L", "leg_R"]
        ws = Workspace(workspaceName)
        ws.file.modules = [makeModule(n) for n in names]
        ws.save()

        loaded = Workspace.load(workspaceName)
        assert [m.name() for m in loaded.file.modules] == names

    def testModuleWithChildHierarchy(self, workspaceName):
        """Nested child modules survive the save → load round-trip."""
        root = makeModule("root")
        child = makeModule("child")
        grandchild = makeModule("grandchild")
        child.addChild(grandchild)
        root.addChild(child)

        ws = Workspace(workspaceName)
        ws.file.modules = [root]
        ws.save()

        loadedRoot = Workspace.load(workspaceName).file.modules[0]
        assert loadedRoot.name() == "root"
        loadedChild = loadedRoot.children()[0]
        assert loadedChild.name() == "child"
        assert loadedChild.children()[0].name() == "grandchild"

    def testModuleAttributeValuesRoundTrip(self, workspaceName):
        """Attribute values survive save → load."""
        m = makeModule("arm")
        m.addAttribute(makeAttribute("length", 42.0))

        ws = Workspace(workspaceName)
        ws.file.modules = [m]
        ws.save()

        attr = Workspace.load(workspaceName).file.modules[0].findAttribute("length")
        assert attr is not None
        assert attr.get() == 42.0


# ============================================================================
# Settings
# ============================================================================

class TestSettings:
    """Tests for the Settings data class (toDict / fromDict / save / load)."""

    def testToDictContainsExpectedKeys(self):
        """toDict() includes all public fields."""
        from rigBuilder.core.settings import Settings
        d = Settings().toDict()
        for key in ("vscode", "modulesPath", "historyPath", "scriptsPath", "workspacePath",
                    "trackHistory", "autoSaveInterval"):
            assert key in d

    def testToDictExcludesPrivateFields(self):
        """toDict() excludes keys starting with underscore."""
        from rigBuilder.core.settings import Settings
        s = Settings()
        s._internal = "secret"
        assert "_internal" not in s.toDict()

    def testFromDictUpdatesKnownFields(self):
        """fromDict() updates attributes that already exist on the object."""
        from rigBuilder.core.settings import Settings
        s = Settings()
        s.fromDict({"vscode": "code-insiders", "autoSaveInterval": 30})
        assert s.vscode == "code-insiders"
        assert s.autoSaveInterval == 30

    def testFromDictIgnoresUnknownFields(self):
        """fromDict() silently ignores keys the object doesn't have."""
        from rigBuilder.core.settings import Settings
        s = Settings()
        s.fromDict({"nonExistentKey": "value"})
        assert not hasattr(s, "nonExistentKey")

    def testSaveAndLoadRoundTrip(self, tmp_path):
        """Settings saved to disk and reloaded produce equivalent state."""
        from rigBuilder.core.settings import Settings
        s = Settings()
        s.vscode = "nvim"
        s.autoSaveInterval = 99
        path = str(tmp_path / "settings.json")
        s.save(path)

        s2 = Settings()
        s2.load(path)
        assert s2.vscode == "nvim"
        assert s2.autoSaveInterval == 99

    def testLoadMissingFileDoesNotRaise(self, tmp_path):
        """load() on a nonexistent file logs an error but does not raise."""
        from rigBuilder.core.settings import Settings
        Settings().load(str(tmp_path / "missing.json"))
