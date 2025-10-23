import pytest
import os
import json
import tempfile
import shutil
import xml.etree.ElementTree as ET

from rigBuilder.core import (
    Attribute, Module, AttrsWrapper, DataAccessor, Dict,
    ExitModuleException, AttributeResolverError, AttributeExpressionError,
    ModuleNotFoundError, CopyJsonError, ModuleRuntimeError,
    getUidFromFile, calculateRelativePath,
    printError, printWarning, exitModule,
    API, RigBuilderPath, RigBuilderLocalPath
)
from rigBuilder.utils import copyJson


# ============================================================================
# HELPER FUNCTIONS
# ============================================================================

def createAttribute(name="testAttr", category="input", template="float", value=10.5):
    """Create attribute using public API."""
    attr = Attribute()
    attr.setName(name)
    attr.setCategory(category)
    attr.setTemplate(template)
    attr.setLocalData({"default": "value", "value": value})
    return attr


def createModule(name="testModule"):
    """Create module using public API."""
    module = Module()
    module.setName(name)
    return module


# ============================================================================
# FIXTURES
# ============================================================================

@pytest.fixture
def tempDir():
    """Create temporary directory in local modules folder for realistic caching."""
    # Create temp dir in local modules folder
    tmpdir = tempfile.mkdtemp(prefix="test_", dir=RigBuilderLocalPath + "/modules")

    yield tmpdir

    # Cleanup
    shutil.rmtree(tmpdir, ignore_errors=True)

    # Update cache to remove deleted directory
    Module.updateUidsCache()


@pytest.fixture
def simpleAttribute():
    """Create simple attribute with basic data."""
    return createAttribute("testAttr", "input", "float", 10.5)


@pytest.fixture
def simpleModule():
    """Create simple module with one attribute."""
    module = createModule("testModule")
    attr = createAttribute("input", "input", "float", 5.0)
    module.addAttribute(attr)
    return module


@pytest.fixture
def moduleHierarchy():
    """Create module hierarchy for testing paths and connections."""
    root = createModule("root")
    rootAttr = createAttribute("rootAttr", "input", "float", 100.0)
    root.addAttribute(rootAttr)

    child1 = createModule("child1")
    child1Attr = createAttribute("childAttr", "input", "float", 50.0)
    child1.addAttribute(child1Attr)
    root.addChild(child1)

    child2 = createModule("child2")
    child2Attr = createAttribute("deepAttr", "input", "float", 25.0)
    child2.addAttribute(child2Attr)
    child1.addChild(child2)

    return root


# ============================================================================
# ATTRIBUTE TESTS
# ============================================================================

class TestAttribute:
    """Tests for Attribute class."""

    def testAttributeCreation(self):
        """Test basic attribute creation with default values."""
        attr = Attribute()
        assert attr.name() == ""
        assert attr.category() == ""
        assert attr.template() == ""
        assert attr.connect() == ""
        assert attr.expression() == ""
        assert attr.modified() == False
        assert attr.module() is None

    def testAttributeProperties(self, simpleAttribute):
        """Test all attribute property getters/setters."""
        # Name
        assert simpleAttribute.name() == "testAttr"
        simpleAttribute.setName("newName")
        assert simpleAttribute.name() == "newName"
        assert simpleAttribute.modified() == True

        # Category
        simpleAttribute.setCategory("output")
        assert simpleAttribute.category() == "output"

        # Template
        simpleAttribute.setTemplate("int")
        assert simpleAttribute.template() == "int"

        # Connect
        simpleAttribute.setConnect("/parent/attr")
        assert simpleAttribute.connect() == "/parent/attr"

        # Expression
        simpleAttribute.setExpression("value = value * 2")
        assert simpleAttribute.expression() == "value = value * 2"

    def testAttributeDataOperations(self, simpleAttribute):
        """Test get/set and data operations."""
        # Simple get/set
        assert simpleAttribute.get() == 10.5
        simpleAttribute.set(30.5)
        assert simpleAttribute.get() == 30.5

        # Get/set with key
        simpleAttribute.set("customValue", "customKey")
        assert simpleAttribute.get("customKey") == "customValue"

        # Data returns copy
        data = simpleAttribute.data()
        originalValue = data["value"]
        data["value"] = 999
        assert simpleAttribute.get() == originalValue

        # Local data
        newData = {"default": "value", "value": 99.9}
        simpleAttribute.setLocalData(newData)
        assert simpleAttribute.get() == 99.9

    def testAttributeCopy(self, simpleAttribute):
        """Test attribute deep copy."""
        copy = simpleAttribute.copy()
        assert copy.name() == simpleAttribute.name()
        assert copy.data() == simpleAttribute.data()
        assert copy is not simpleAttribute

    def testAttributeJsonError(self, simpleAttribute):
        """Test that non-JSON data raises error."""
        with pytest.raises(CopyJsonError):
            simpleAttribute.set(lambda x: x)


class TestAttributeConnections:
    """Tests for attribute connections."""

    def testConnectionSourceAndPullPush(self, moduleHierarchy):
        """Test finding source, pulling and pushing values."""
        child1 = moduleHierarchy.findChild("child1")
        childAttr = child1.findAttribute("childAttr")
        rootAttr = moduleHierarchy.findAttribute("rootAttr")

        childAttr.setConnect("/rootAttr")

        # Find source
        source = childAttr.findConnectionSource()
        assert source is rootAttr

        # Pull
        rootAttr.set(250.0)
        childAttr.pull()
        assert childAttr.get() == 250.0

        # Push
        childAttr.set(300.0)
        assert rootAttr.get() == 300.0

    def testListConnections(self, moduleHierarchy):
        """Test listing all connections to an attribute."""
        rootAttr = moduleHierarchy.findAttribute("rootAttr")
        child1 = moduleHierarchy.findChild("child1")
        childAttr = child1.findAttribute("childAttr")

        childAttr.setConnect("/rootAttr")

        connections = rootAttr.listConnections()
        assert len(connections) == 1
        assert connections[0] is childAttr


class TestAttributeExpressions:
    """Tests for attribute expressions."""

    def testExecuteExpression(self, simpleModule):
        """Test executing expressions with context."""
        attr = simpleModule.findAttribute("input")

        # Simple expression
        attr.setExpression("value = value * 2")
        initial = attr.get()
        attr.executeExpression()
        assert attr.get() > initial

        # Expression with clamp from context
        attr.set(10.0)
        attr.setExpression("value = clamp(value, 0, 5)")
        attr.executeExpression()
        assert attr.localData()["value"] == 5.0

    def testExecuteExpressionError(self, simpleModule):
        """Test expression with syntax error."""
        attr = simpleModule.findAttribute("input")
        attr.setExpression("this is invalid python")

        with pytest.raises(AttributeExpressionError):
            attr.executeExpression()


class TestAttributeXML:
    """Tests for attribute XML serialization."""

    def testXmlSerialization(self, simpleAttribute):
        """Test converting to XML and back."""
        simpleAttribute.setExpression("value = value * 2")
        simpleAttribute.setConnect("/parent/attr")

        # To XML
        xmlStr = simpleAttribute.toXml()
        assert 'name="testAttr"' in xmlStr
        assert 'template="float"' in xmlStr
        assert "_expression" in xmlStr

        # From XML
        root = ET.fromstring(xmlStr)
        restored = Attribute.fromXml(root)
        assert restored.name() == simpleAttribute.name()
        assert restored.expression() == simpleAttribute.expression()
        assert restored.localData() == simpleAttribute.localData()

    def testXmlConnectionControl(self, simpleAttribute):
        """Test XML serialization with/without connection."""
        simpleAttribute.setConnect("/parent/attr")

        xmlWith = simpleAttribute.toXml(keepConnection=True)
        assert 'connect="/parent/attr"' in xmlWith

        xmlWithout = simpleAttribute.toXml(keepConnection=False)
        assert 'connect=""' in xmlWithout


# ============================================================================
# MODULE TESTS
# ============================================================================

class TestModule:
    """Tests for Module class."""

    def testModuleCreation(self):
        """Test basic module creation with default values."""
        module = Module()
        assert module.uid() == ""
        assert module.name() == ""
        assert module.runCode() == ""
        assert module.parent() is None
        assert module.children() == []
        assert module.attributes() == []
        assert module.muted() == False
        assert module.filePath() == ""
        assert module.modified() == False

    def testModuleProperties(self, simpleModule):
        """Test module property getters/setters."""
        # Name
        assert simpleModule.name() == "testModule"
        simpleModule.setName("newModule")
        assert simpleModule.name() == "newModule"

        # Mute/unmute
        simpleModule.mute()
        assert simpleModule.muted() == True
        simpleModule.unmute()
        assert simpleModule.muted() == False

        # Run code
        simpleModule.setRunCode("print('hello')")
        assert simpleModule.runCode() == "print('hello')"
        assert simpleModule.modified() == True

    def testModuleCopy(self, simpleModule):
        """Test module deep copy."""
        copy = simpleModule.copy()
        assert copy.name() == simpleModule.name()
        assert len(copy.attributes()) == len(simpleModule.attributes())
        assert copy is not simpleModule
        assert copy.attributes()[0] is not simpleModule.attributes()[0]


class TestModuleChildren:
    """Tests for module children management."""

    def testChildrenOperations(self, simpleModule):
        """Test add/insert/remove/find children."""
        child1 = createModule("child1")
        child2 = createModule("child2")

        # Add
        simpleModule.addChild(child1)
        assert len(simpleModule.children()) == 1
        assert child1.parent() is simpleModule
        assert simpleModule.modified() == True

        # Insert
        simpleModule.insertChild(0, child2)
        assert simpleModule.children()[0] is child2
        assert simpleModule.children()[1] is child1

        # Find
        found = simpleModule.findChild("child1")
        assert found is child1
        assert simpleModule.findChild("nonexistent") is None

        # Get by index/name
        assert simpleModule.child(0) is child2
        assert simpleModule.child("child1") is child1

        # Remove one
        simpleModule.removeChild(child1)
        assert len(simpleModule.children()) == 1
        assert child1.parent() is None

        # Remove all
        simpleModule.removeChildren()
        assert len(simpleModule.children()) == 0


class TestModuleAttributes:
    """Tests for module attributes management."""

    def testAttributesOperations(self):
        """Test add/insert/remove/find attributes."""
        module = createModule("test")
        attr1 = createAttribute("attr1")
        attr2 = createAttribute("attr2")

        # Add
        module.addAttribute(attr1)
        assert len(module.attributes()) == 1
        assert attr1.module() is module
        assert module.modified() == True

        # Insert
        module.insertAttribute(0, attr2)
        assert module.attributes()[0] is attr2

        # Find
        found = module.findAttribute("attr1")
        assert found is attr1
        assert module.findAttribute("nonexistent") is None

        # Remove one
        module.removeAttribute(attr1)
        assert len(module.attributes()) == 1
        assert attr1.module() is None

        # Remove all
        module.removeAttributes()
        assert len(module.attributes()) == 0


class TestModulePaths:
    """Tests for module path operations."""

    def testPathNavigation(self, moduleHierarchy):
        """Test root, path and path navigation."""
        child1 = moduleHierarchy.findChild("child1")
        child2 = child1.findChild("child2")

        # Root
        assert moduleHierarchy.root() is moduleHierarchy
        assert child1.root() is moduleHierarchy
        assert child2.root() is moduleHierarchy

        # Paths
        assert moduleHierarchy.path() == "root"
        assert child1.path() == "root/child1"
        assert child2.path() == "root/child1/child2"
        assert child1.path(inclusive=False) == "root"

    def testFindAttributeByPath(self, moduleHierarchy):
        """Test finding attributes by path with various notations."""
        # Simple path
        attr = moduleHierarchy.findAttributeByPath("rootAttr")
        assert attr.name() == "rootAttr"

        # Child path
        attr = moduleHierarchy.findAttributeByPath("child1/childAttr")
        assert attr.name() == "childAttr"

        # Nested path
        attr = moduleHierarchy.findAttributeByPath("child1/child2/deepAttr")
        assert attr.name() == "deepAttr"

        # Parent notation (..)
        child1 = moduleHierarchy.findChild("child1")
        attr = child1.findAttributeByPath("../rootAttr")
        assert attr.name() == "rootAttr"

        # Current notation (.)
        attr = moduleHierarchy.findAttributeByPath("./rootAttr")
        assert attr.name() == "rootAttr"

        # Error on invalid path
        with pytest.raises(AttributeResolverError):
            moduleHierarchy.findAttributeByPath("nonexistent/attr")

    def testConvenienceMethods(self, moduleHierarchy):
        """Test ch/chdata/chset convenience methods."""
        # ch - get value
        value = moduleHierarchy.ch("child1/childAttr")
        assert value == 50.0

        # chdata - get data
        data = moduleHierarchy.chdata("rootAttr")
        assert "value" in data
        assert data["value"] == 100.0

        # chset - set value
        moduleHierarchy.chset("rootAttr", 200.0)
        assert moduleHierarchy.ch("rootAttr") == 200.0


class TestModuleXML:
    """Tests for module XML serialization."""

    def testXmlSerialization(self, moduleHierarchy):
        """Test converting module to XML and back."""
        # To XML
        xmlStr = moduleHierarchy.toXml()
        assert '<module' in xmlStr
        assert 'name="root"' in xmlStr
        assert 'name="child1"' in xmlStr
        assert '<attributes>' in xmlStr
        assert '<children>' in xmlStr

        # From XML
        root = ET.fromstring(xmlStr)
        restored = Module.fromXml(root)
        assert restored.name() == moduleHierarchy.name()
        assert len(restored.children()) == len(moduleHierarchy.children())
        assert restored.findChild("child1") is not None


class TestModuleFileOperations:
    """Tests for module file operations."""

    def testSaveAndLoad(self, simpleModule, tempDir):
        """Test saving to file and loading back."""
        filePath = os.path.join(tempDir, "test_module.xml")

        # Save
        simpleModule.saveToFile(filePath)
        assert os.path.exists(filePath)
        assert simpleModule.filePath() == os.path.normpath(filePath)
        assert simpleModule.uid() != ""

        # Load
        loaded = Module.loadFromFile(filePath)
        assert loaded.name() == simpleModule.name()
        assert len(loaded.attributes()) == len(simpleModule.attributes())

    def testSaveWithNewUid(self, simpleModule, tempDir):
        """Test saving with new UID generation."""
        filePath = os.path.join(tempDir, "test.xml")
        simpleModule.saveToFile(filePath)
        oldUid = simpleModule.uid()

        simpleModule.saveToFile(filePath, newUid=True)
        assert simpleModule.uid() != oldUid

    def testLoadModuleByPath(self, simpleModule, tempDir):
        """Test loading module by various path formats."""
        filePath = os.path.join(tempDir, "test.xml")
        simpleModule.saveToFile(filePath)

        # Load by path
        loaded = Module.loadModule(filePath)
        assert loaded.name() == simpleModule.name()

        # Get UID from file
        uid = getUidFromFile(filePath)
        assert uid == simpleModule.uid()

    def testUpdatePreservesAttributeValues(self, tempDir):
        """Test that update() preserves attribute values while updating structure."""
        # Create original module
        original = createModule("original")
        attr1 = createAttribute("input1", "input", "float", 10.0)
        attr2 = createAttribute("input2", "input", "float", 20.0)
        original.addAttribute(attr1)
        original.addAttribute(attr2)
        original.setRunCode("result = @input1 + @input2")

        filePath = os.path.join(tempDir, "original.xml")
        original.saveToFile(filePath)

        # Load and modify
        loaded = Module.loadModule(filePath)
        loaded.findAttribute("input1").set(100.0)
        loaded.findAttribute("input2").set(200.0)

        # Update from original file
        loaded.update()

        # Values should be preserved
        assert loaded.findAttribute("input1").get() == 100.0
        assert loaded.findAttribute("input2").get() == 200.0

    def testUpdateAddsNewAttributes(self, tempDir):
        """Test that update() adds new attributes from reference file."""
        # Create v1
        v1 = createModule("module")
        attr1 = createAttribute("input1", "input", "float", 10.0)
        v1.addAttribute(attr1)

        filePath = os.path.join(tempDir, "module.xml")
        v1.saveToFile(filePath)

        # Load v1
        loaded = Module.loadModule(filePath)
        assert len(loaded.attributes()) == 1

        # Create v2 with new attribute
        v2 = createModule("module")
        attr1_v2 = createAttribute("input1", "input", "float", 10.0)
        attr2_v2 = createAttribute("input2", "input", "float", 20.0)
        v2.addAttribute(attr1_v2)
        v2.addAttribute(attr2_v2)
        v2._uid = loaded.uid()  # Same UID
        v2.saveToFile(filePath)
        Module.updateUidsCache()  # Update cache from disk

        # Update
        loaded.update()

        # Should have new attribute
        assert len(loaded.attributes()) == 2
        assert loaded.findAttribute("input2") is not None

    def testUpdateRemovesOldAttributes(self, tempDir):
        """Test that update() removes attributes not in reference file."""
        # Create v1 with 2 attributes
        v1 = createModule("module")
        attr1 = createAttribute("input1", "input", "float", 10.0)
        attr2 = createAttribute("input2", "input", "float", 20.0)
        v1.addAttribute(attr1)
        v1.addAttribute(attr2)

        filePath = os.path.join(tempDir, "module.xml")
        v1.saveToFile(filePath)

        # Load v1
        loaded = Module.loadModule(filePath)
        assert len(loaded.attributes()) == 2

        # Create v2 with only 1 attribute
        v2 = createModule("module")
        attr1_v2 = createAttribute("input1", "input", "float", 10.0)
        v2.addAttribute(attr1_v2)
        v2._uid = loaded.uid()  # Same UID
        v2.saveToFile(filePath)
        Module.updateUidsCache()  # Update cache from disk

        # Update
        loaded.update()

        # Should have only 1 attribute
        assert len(loaded.attributes()) == 1
        assert loaded.findAttribute("input1") is not None
        assert loaded.findAttribute("input2") is None

    def testUpdatePreservesConnectionsAndExpressions(self, tempDir):
        """Test that update() preserves connections and expressions."""
        # Create original
        original = createModule("original")
        attr1 = createAttribute("input", "input", "float", 10.0)
        original.addAttribute(attr1)

        filePath = os.path.join(tempDir, "original.xml")
        original.saveToFile(filePath)
        Module.updateUidsCache()  # Update cache from disk

        # Load and add connection/expression
        loaded = Module.loadModule(filePath)
        loadedAttr = loaded.findAttribute("input")
        loadedAttr.setConnect("/someAttr")
        loadedAttr.setExpression("value = value + 10")  # Simple additive expression
        loadedAttr.set(50.0)

        # Update
        loaded.update()

        # Connection and expression should be preserved
        updatedAttr = loaded.findAttribute("input")
        assert updatedAttr.connect() == "/someAttr"
        assert updatedAttr.expression() == "value = value + 10"
        # Value preserved (expression doesn't execute during update)
        assert updatedAttr.localData()["value"] == 50.0

    def testUpdateChangesRunCode(self, tempDir):
        """Test that update() updates runCode from reference file."""
        # Create v1
        v1 = createModule("module")
        v1.setRunCode("old_code = 1")

        filePath = os.path.join(tempDir, "module.xml")
        v1.saveToFile(filePath)

        # Load v1
        loaded = Module.loadModule(filePath)
        assert loaded.runCode() == "old_code = 1"

        # Create v2 with new runCode
        v2 = createModule("module")
        v2.setRunCode("new_code = 2")
        v2._uid = loaded.uid()
        v2.saveToFile(filePath)
        Module.updateUidsCache()  # Update cache from disk

        # Update
        loaded.update()

        # RunCode should be updated
        assert loaded.runCode() == "new_code = 2"

    def testUpdateReplacesEmbeddedChildren(self, tempDir):
        """Test that update() replaces embedded children from reference file."""
        # Create v1 with one child
        parent = createModule("parent")
        child1 = createModule("child1")
        child1.addAttribute(createAttribute("input", "input", "float", 10.0))
        parent.addChild(child1)

        filePath = os.path.join(tempDir, "parent.xml")
        parent.saveToFile(filePath)
        Module.updateUidsCache()  # Update cache from disk

        # Load and modify
        loaded = Module.loadModule(filePath)
        assert len(loaded.children()) == 1

        # Create v2 with different children structure
        parentV2 = createModule("parent")
        child2 = createModule("child2")
        child2.addAttribute(createAttribute("output", "output", "float", 20.0))
        parentV2.addChild(child2)
        parentV2._uid = loaded.uid()
        parentV2.saveToFile(filePath)
        Module.updateUidsCache()  # Update cache from disk

        # Update
        loaded.update()

        # Children should be replaced from reference file
        assert len(loaded.children()) == 1
        assert loaded.findChild("child2") is not None
        assert loaded.findChild("child1") is None

    def testUpdateWithNoReferenceFile(self, tempDir):
        """Test that update() does nothing when no reference file exists."""
        module = createModule("module")
        attr = createAttribute("input", "input", "float", 10.0)
        module.addAttribute(attr)

        # No file saved, no reference
        initialAttrs = len(module.attributes())
        module.update()

        # Nothing should change
        assert len(module.attributes()) == initialAttrs

    def testUpdateWithMismatchedTemplate(self, tempDir):
        """Test that update() replaces attributes with mismatched templates."""
        # Create v1 with float attribute
        v1 = createModule("module")
        attr1 = createAttribute("input", "input", "float", 10.0)
        v1.addAttribute(attr1)

        filePath = os.path.join(tempDir, "module.xml")
        v1.saveToFile(filePath)

        # Load and set value
        loaded = Module.loadModule(filePath)
        loaded.findAttribute("input").set(100.0)

        # Create v2 with same attribute name but different template
        v2 = createModule("module")
        attr1_v2 = createAttribute("input", "input", "int", 5)  # Changed to int
        v2.addAttribute(attr1_v2)
        v2._uid = loaded.uid()
        v2.saveToFile(filePath)
        Module.updateUidsCache()  # Update cache from disk

        # Update
        loaded.update()

        # Should get new template with original value
        updatedAttr = loaded.findAttribute("input")
        assert updatedAttr.template() == "int"
        assert updatedAttr.get() == 5  # Value from reference, not preserved


class TestModuleExecution:
    """Tests for module execution."""

    def testModuleContext(self, simpleModule):
        """Test module execution context contains required functions."""
        ctx = simpleModule.context()
        assert "module" in ctx
        assert "ch" in ctx
        assert "chdata" in ctx
        assert "chset" in ctx
        assert ctx["module"] is simpleModule

    def testModuleRunBasics(self, simpleModule):
        """Test basic module execution."""
        # Simple code
        simpleModule.setRunCode("result = 42")
        ctx = simpleModule.run()
        assert ctx["result"] == 42

        # Attribute access with @
        simpleModule.setRunCode("result = @input * 2")
        ctx = simpleModule.run()
        assert ctx["result"] == 10.0

        # Attribute setter
        simpleModule.setRunCode("attr_set_input(100)")
        simpleModule.run()
        assert simpleModule.findAttribute("input").get() == 100

        # Data accessor
        attr = simpleModule.findAttribute("input")
        attr.set("test", "customKey")
        simpleModule.setRunCode("result = attr_input_data['customKey']")
        ctx = simpleModule.run()
        assert ctx["result"] == "test"

    def testModuleRunWithChMethods(self, moduleHierarchy):
        """Test using ch/chdata/chset in module execution."""
        moduleHierarchy.setRunCode("result = ch('rootAttr') * 2")
        ctx = moduleHierarchy.run()
        assert ctx["result"] == 200.0

    def testModuleRunControl(self, simpleModule):
        """Test exit() and error handling."""
        # Exit
        simpleModule.setRunCode("exit()\nresult = 42")
        ctx = simpleModule.run()
        assert "result" not in ctx

        # Error
        simpleModule.setRunCode("raise ValueError('test error')")
        with pytest.raises(ModuleRuntimeError):
            simpleModule.run()

    def testModuleRunCallback(self, simpleModule):
        """Test module run with callback."""
        calledModules = []
        def callback(module):
            calledModules.append(module)

        simpleModule.run(callback=callback)
        assert simpleModule in calledModules

    def testModuleRunChildren(self, moduleHierarchy):
        """Test running module with children and muted children."""
        child1 = moduleHierarchy.findChild("child1")
        child1.setRunCode("child_result = 123")

        # Normal child execution
        moduleHierarchy.run()
        childCtx = child1.run()
        assert childCtx["child_result"] == 123

        # Muted child not executed
        child1.mute()
        child1.setRunCode("module.glob.muted_child_ran = True")
        moduleHierarchy.setRunCode("parent_ran = True")

        # Clear flag before running
        Module.glob.pop("muted_child_ran", None)

        ctx = moduleHierarchy.run()
        assert "parent_ran" in ctx
        assert Module.glob.get("muted_child_ran") is None  # Child should not have run


# ============================================================================
# HELPER CLASSES TESTS
# ============================================================================

class TestHelperClasses:
    """Tests for helper classes."""

    def testDict(self):
        """Test Dict attribute access."""
        d = Dict()
        d["key"] = "value"
        assert d.key == "value"

        d.key2 = "value2"
        assert d["key2"] == "value2"

    def testAttrsWrapper(self, simpleModule):
        """Test AttrsWrapper for attribute access."""
        # Get attribute
        attr = simpleModule.attr.input
        assert isinstance(attr, Attribute)
        assert attr.name() == "input"

        # Set attribute value
        simpleModule.attr.input = 99.9
        assert simpleModule.findAttribute("input").get() == 99.9

        # Non-existent attribute
        with pytest.raises(AttributeError):
            _ = simpleModule.attr.nonexistent

    def testDataAccessor(self, simpleAttribute):
        """Test DataAccessor for data access."""
        accessor = DataAccessor(simpleAttribute)

        # Get/set
        assert accessor["value"] == 10.5
        accessor["value"] = 50.0
        assert simpleAttribute.get("value") == 50.0

        # String representation
        strRepr = str(accessor)
        assert isinstance(strRepr, str)
        assert "value" in strRepr


# ============================================================================
# INTEGRATION TESTS
# ============================================================================

class TestIntegration:
    """Integration tests for complete workflows."""

    def testCompleteModuleWorkflow(self, tempDir):
        """Test complete module lifecycle: create, save, load."""
        # Create
        module = createModule("integration_test")
        attr = createAttribute("value", "input", "float", 10.0)
        module.addAttribute(attr)
        child = createModule("child")
        module.addChild(child)

        # Save
        filePath = os.path.join(tempDir, "integration.xml")
        module.saveToFile(filePath)

        # Load
        loaded = Module.loadFromFile(filePath)

        # Verify
        assert loaded.name() == "integration_test"
        assert len(loaded.attributes()) == 1
        assert len(loaded.children()) == 1
        assert loaded.findAttribute("value").get() == 10.0

    def testConnectionWorkflow(self, moduleHierarchy):
        """Test complete connection workflow with pull/push."""
        rootAttr = moduleHierarchy.findAttribute("rootAttr")
        child1 = moduleHierarchy.findChild("child1")
        childAttr = child1.findAttribute("childAttr")

        childAttr.setConnect("/rootAttr")

        # Pull workflow
        rootAttr.set(250.0)
        childAttr.pull()
        assert childAttr.get() == 250.0

        # Push workflow
        childAttr.set(300.0)
        assert rootAttr.get() == 300.0

    def testExecutionWithExpressions(self, simpleModule):
        """Test module execution with attribute expressions."""
        attr = simpleModule.findAttribute("input")
        attr.set(5.0)
        attr.setExpression("value = value * 2")

        attr.pull()

        result = attr.localData()["value"]
        assert result == 10.0

    def testCalculatorModule(self):
        """Test module that performs calculations on attributes."""
        module = createModule("calculator")

        input1 = createAttribute("input1", "input", "float", 10.0)
        input2 = createAttribute("input2", "input", "float", 5.0)
        output = createAttribute("output", "output", "float", 0.0)

        module.addAttribute(input1)
        module.addAttribute(input2)
        module.addAttribute(output)

        module.setRunCode("attr_set_output(@input1 + @input2)")
        module.run()

        assert module.findAttribute("output").get() == 15.0

    def testDeepConnectionChains(self):
        """Test connection chains through multiple hierarchy levels."""
        # Create hierarchy: root -> child1 -> child2 -> child3
        root = createModule("root")
        rootAttr = createAttribute("source", "input", "float", 100.0)
        root.addAttribute(rootAttr)

        child1 = createModule("child1")
        child1Attr = createAttribute("intermediate1", "input", "float", 0.0)
        child1Attr.setConnect("/source")
        child1.addAttribute(child1Attr)
        root.addChild(child1)

        child2 = createModule("child2")
        child2Attr = createAttribute("intermediate2", "input", "float", 0.0)
        child2Attr.setConnect("/intermediate1")
        child2.addAttribute(child2Attr)
        child1.addChild(child2)

        child3 = createModule("child3")
        child3Attr = createAttribute("final", "input", "float", 0.0)
        child3Attr.setConnect("/intermediate2")
        child3.addAttribute(child3Attr)
        child2.addChild(child3)

        # Pull through the chain
        child3Attr.pull()
        assert child3Attr.get() == 100.0

        # Push back through the chain
        child3Attr.set(500.0)
        assert rootAttr.get() == 500.0
        assert child1Attr.get() == 500.0
        assert child2Attr.get() == 500.0

    def testSaveLoadWithConnections(self, tempDir):
        """Test that inner connections are kept, outer connections are cleared."""
        # Create module with internal connection
        parent = createModule("parent")
        parentAttr = createAttribute("source", "input", "float", 50.0)
        parent.addAttribute(parentAttr)

        child = createModule("child")
        childAttr = createAttribute("connected", "input", "float", 0.0)
        childAttr.setConnect("/source")  # Inner connection to parent's attribute
        child.addAttribute(childAttr)
        parent.addChild(child)

        # Verify connection works before save
        childAttr.pull()
        assert childAttr.get() == 50.0

        # Save and load
        filePath = os.path.join(tempDir, "connection_test.xml")
        parent.saveToFile(filePath)
        loaded = Module.loadFromFile(filePath)

        # Inner connection should be preserved
        loadedChild = loaded.findChild("child")
        loadedChildAttr = loadedChild.findAttribute("connected")
        assert loadedChildAttr.connect() == "/source"  # Inner connection kept

        # Connection should work after load
        loadedChildAttr.pull()
        assert loadedChildAttr.get() == 50.0

    def testExpressionErrorInWorkflow(self):
        """Test handling expression errors during complete workflow."""
        module = createModule("errorModule")
        attr = createAttribute("input", "input", "float", 10.0)
        attr.setExpression("value = undefined_variable * 2")
        module.addAttribute(attr)

        # Expression error should propagate
        with pytest.raises(AttributeExpressionError):
            attr.pull()

    def testNestedMutedChildren(self):
        """Test execution with nested muted/unmuted children."""
        root = createModule("root")
        root.setRunCode("module.glob.root_ran = True")

        child1 = createModule("child1")
        child1.setRunCode("module.glob.child1_ran = True")
        root.addChild(child1)

        child2 = createModule("child2")
        child2.setRunCode("module.glob.child2_ran = True")
        child1.addChild(child2)

        child3 = createModule("child3")
        child3.setRunCode("module.glob.child3_ran = True")
        child2.addChild(child3)

        # Clear flags
        Module.glob.pop("root_ran", None)
        Module.glob.pop("child1_ran", None)
        Module.glob.pop("child2_ran", None)
        Module.glob.pop("child3_ran", None)

        # Mute middle child
        child2.mute()

        # Run
        root.run()

        # Root and child1 should run, child2 and child3 should not
        assert Module.glob.get("root_ran") is True
        assert Module.glob.get("child1_ran") is True
        assert Module.glob.get("child2_ran") is None  # Muted
        assert Module.glob.get("child3_ran") is None  # Parent muted

    def testConnectionWithExpressionChain(self):
        """Test connections combined with expressions in workflow."""
        parent = createModule("parent")
        sourceAttr = createAttribute("source", "input", "float", 10.0)
        parent.addAttribute(sourceAttr)

        child = createModule("child")
        connectedAttr = createAttribute("connected", "input", "float", 0.0)
        connectedAttr.setConnect("/source")
        connectedAttr.setExpression("value = value * 3")  # Expression modifies pulled value
        child.addAttribute(connectedAttr)
        parent.addChild(child)

        # Pull should get value from source, then apply expression
        connectedAttr.pull()
        assert connectedAttr.get() == 30.0  # 10 * 3

        # Change source and pull again
        sourceAttr.set(5.0)
        connectedAttr.pull()
        assert connectedAttr.get() == 15.0  # 5 * 3
