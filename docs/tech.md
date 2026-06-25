# Rig Builder AI Reference: Architecture, API, and Module Development

This document provides a comprehensive technical guide for AI code editors and generators to build, edit, and manipulate Rig Builder modules (`.rb` or `.xml` format) and workspaces (`.rbws` format).

---

## 1. System Overview & Architecture

Rig Builder is a hierarchical execution graph of **Modules**. Each module contains:
- **Run Code**: Python execution script.
- **Documentation**: Markdown-based description.
- **Attributes**: Parameters that define widgets, settings, inputs/outputs, and expressions.
- **Children**: Nested modules executing in order.

### Execution Flow
1. **Pull**: When a module starts execution, it recursively pulls data from connection sources.
2. **Execute Expressions**: Attributes evaluate their custom Python expressions to calculate final values.
3. **Execute Run Code**: The module's `<run>` Python code is executed.
4. **Execute Children**: Child modules execute sequentially (unless muted).

---

## 2. File Format Specification (.rb / .xml)

Modules are serialized to XML format. A `.rb` file represents a single root module with its descendants.

### XML Schema Layout
```xml
<module name="module_name" muted="0" uid="optional_uuid_hex_string">
  <run><![CDATA[
# Python execution code here
  ]]></run>
  <doc><![CDATA[
# Markdown Documentation Here
  ]]></doc>
  <attributes>
    <attr name="attribute_name" template="widget_template" category="CategoryName" connect="connection_path">
      <![CDATA[{"default": "key_name", "key_name": "value", ...}]]>
    </attr>
  </attributes>
  <children>
    <!-- Nested <module> elements here -->
  </children>
</module>
```

### Tag & Attribute Details

| Element/Attribute | Description |
| :--- | :--- |
| `<module>` | Root tag representing a module. |
| `name` | Unique name of the module among sibling modules. |
| `muted` | `1` to mute execution (runs child modules but skips its own run code, unless executed directly); `0` to execute. |
| `uid` | 32-character hexadecimal UUID. Generated when saving the file; points to external referenced modules. |
| `<run>` | CDATA block containing Python run code. |
| `<doc>` | CDATA block containing Markdown documentation. |
| `<attributes>` | Container for child `<attr>` elements. |
| `<attr>` | Individual attribute definition. |
| `template` | The widget UI template type (e.g. `lineEditAndButton`, `vector`, `checkBox`). |
| `category` | Tab or section name under which the attribute is categorized in the UI (e.g., `General`, `Expression`). |
| `connect` | Connection path to a source attribute (e.g., `/myAttr` or `../otherModule/sourceAttr`). |
| `<attr>` CDATA | JSON string defining the widget properties. **Must** contain a `"default"` key mapping to the main value key. |

---

## 3. Widget Templates & JSON Schemas

Every attribute uses a widget template determining how it is configured and displayed. Below are the precise JSON schemas stored inside the `<attr>` CDATA block:

### `lineEditAndButton` (Text, Int, Float input with button)
```json
{
  "value": "",
  "placeholder": "",
  "buttonCommand": "print(\"Hello world!\")",
  "buttonLabel": "Button",
  "buttonEnabled": false,
  "min": 0,
  "max": 100,
  "validator": 0, 
  "default": "value"
}
```
*Note on `validator`: `0` = String/None, `1` = Integer, `2` = Float.*

### `vector` (N-dimensional float array)
```json
{
  "value": [0.0, 0.0, 0.0],
  "dimension": 3,
  "columns": 3,
  "precision": 4,
  "default": "value"
}
```

### `checkBox` (Boolean toggle)
```json
{
  "checked": false,
  "default": "checked"
}
```

### `comboBox` (String dropdown list)
```json
{
  "items": ["option_a", "option_b"],
  "current": "option_a",
  "default": "current"
}
```

### `listBox` (Item list selection)
```json
{
  "items": ["item1", "item2"],
  "current": 0,
  "default": "items"
}
```

### `radioButton` (Exclusive button grid layout)
```json
{
  "items": ["Option A", "Option B", "Option C"],
  "current": 0,
  "columns": 3,
  "default": "current"
}
```

### `table` (2D String Grid)
```json
{
  "items": [["cell_r0_c0", "cell_r0_c1"]],
  "header": ["column_1", "column_2"],
  "default": "items"
}
```

### `curve` (Bezier spline data evaluation)
```json
{
  "cvs": [[0.0, 1.0], [0.5, 0.5], [1.0, 1.0]],
  "default": "cvs"
}
```

### `json` (Generic JSON list/dict editor)
```json
{
  "data": [{"key": "value"}],
  "height": 200,
  "readonly": false,
  "default": "data"
}
```

### `fileSelector` (File picker widget)
```json
{
  "value": "",
  "mode": "openFile", 
  "filter": "All Files (*.*)",
  "title": "Select File",
  "default": "value"
}
```
*Note on `mode`: `"openFile"`, `"saveFile"`, or `"existingDirectory"`.*

### `label` (Read-only HTML display)
```json
{
  "text": "Your message here",
  "default": "text"
}
```

### `text` (Multi-line text editor)
```json
{
  "text": "",
  "height": 200,
  "default": "text"
}
```

### `button` (Standalone execution button)
```json
{
  "command": "chset(\"/someAttr\", 1)",
  "label": "Button Label",
  "color": "#176f1a",
  "default": "command"
}
```

### `compound` (Complex widget containing nested sub-widgets)
```json
{
  "widgets": [
    {"items": ["a", "b"], "current": 0, "default": "items"},
    {"command": "...", "label": "Press me", "color": "", "default": "command"}
  ],
  "values": [["a", "b"], "command_string"],
  "templates": ["listBox", "button"],
  "default": "values"
}
```

---

## 4. Execution Context & The Macro `@` Syntax

### The `@` Macro Substitution
Inside module run scripts (`<run>`) and attribute expressions (`_expression`), the `@` prefix simplifies accessing attribute values. It is pre-processed before Python evaluation:

1. **`@attr_name`** -> Expands to **`attr_attr_name`**, which evaluates to the **default/primary value** of the attribute.
2. **`@set_attr_name(val)`** -> Expands to **`attr_set_attr_name(val)`**, which calls the attribute's setter method `attr.set(val)`.
3. **`@attr_name_data`** -> Expands to **`attr_attr_name_data`**, returning an `AttributeDataAccessor` mapping to the attribute's internal configuration dictionary. Used to get/set non-default JSON keys (e.g. `@my_attr_data["buttonLabel"] = "New Label"`).

### Context Scope Variable List
When running script code, the following scope is injected:

* `module`: Current execution instance of `core.Module`.
* `ch(path, key=None)`: Gets an attribute's default value (or specific key value) by relative path.
* `chset(path, value, key=None)`: Sets an attribute's value (or specific key value) by relative path.
* `chdata(path)`: Gets a read-only copy of the attribute's data dictionary by relative path.
* `attr_<attr_name>`: Evaluates to attribute's default value.
* `attr_set_<attr_name>(val)`: Method to set attribute value.
* `attr_<attr_name>_data`: `AttributeDataAccessor` for setting specific JSON keys in attribute data.

### Relative Pathing Syntax in Connections and `ch()` functions
Paths are constructed using Unix-like relative structures:
* `/attrName`: Look up attribute `attrName` in the **current** module.
* `childName/attrName`: Look up attribute `attrName` inside the **child** module named `childName`.
* `../attrName`: Look up attribute `attrName` inside the **parent** module.
* `../../childName/attrName`: Navigate two parents up, then down to `childName` module, and retrieve `attrName`.

---

## 5. Standard Global APIs

Registered via `APIRegistry` and available directly in module execution scope:

### General & Math Utilities
* `clamp(val, low, high) -> float`: Clamps numeric value between bounds.
* `listLerp(lst1, lst2, w) -> list`: Performs linear interpolation between two lists of numbers.
* `smartConversion(x: str) -> Any`: Attempts to parse a string as JSON, falling back to a raw string on failure.
* `fromSmartConversion(x) -> str`: Converts Python objects to a JSON string, keeping strings raw.
* `copyJson(data) -> Any`: Performs a deep copy of JSON-compatible structures.
* `exit()`: Exits the current module's execution immediately (raises `ExitModuleException`).
* `error(msg: str)`: Emits an error output and terminates the module execution.
* `warning(msg: str)`: Emits a warning to output logs without stopping execution.

### Widget Helpers
* `curve_evaluate(data: dict, param: float) -> list[float]`: Evaluates a Bezier curve attribute at `0-1` parameter.
* `curve_evaluateFromX(data: dict, x: float) -> list[float]`: Evaluates a Bezier curve attribute at X position.
* `comboBox_items(data: dict) -> list[str]`: Retrieves items from a combo box.
* `comboBox_setItems(data: dict, items: list[str])`: Replaces items in a combo box.

### UI Progress Control
* `beginProgress(text: str, count: int)`: Initializes progress bar tracker dialog.
* `stepProgress(value: int, text: str = None)`: Steps the active progress tracker.
* `endProgress()`: Hides the active progress tracker.

---

## 6. Python Class API (Reference)

For scripting rig builds programmatically using `rigBuilder.core`:

### `core.Module`
```python
class Module:
    def __init__(self, name="module", runCode="", doc="", children=None, attributes=None, muted=False): ...
    
    # Hierarchy Manipulation
    def parent(self) -> Optional[Module]: ...
    def root(self) -> Module: ...
    def children(self) -> List[Module]: ...
    def child(self, nameOrIndex: Union[str, int]) -> Optional[Module]: ...
    def addChild(self, child: Module): ...
    def insertChild(self, idx: int, child: Module): ...
    def removeChild(self, child: Module): ...
    def removeChildren(self): ...
    def findChild(self, name: str) -> Optional[Module]: ...
    
    # Attribute Manipulation
    def attributes(self) -> List[Attribute]: ...
    def addAttribute(self, attr: Attribute): ...
    def insertAttribute(self, idx: int, attr: Attribute): ...
    def removeAttribute(self, attr: Attribute): ...
    def findAttribute(self, name: str) -> Optional[Attribute]: ...
    
    # Path Resolution
    def findAttributeByPath(self, path: str) -> Attribute: ...
    def findModuleByPath(self, path: str) -> Optional[Module]: ...
    def path(self, inclusive: bool = True) -> str: ...
    
    # Execution
    def run(self, callback=None, context=None) -> DictExt: ...
    
    # Serialization
    def toXml(self, keepConnections=True) -> str: ...
    @staticmethod
    def fromXml(xml: Union[str, Element]) -> Module: ...
    def saveToFile(self, fileName: str, newUid=False): ...
    @staticmethod
    def loadFromFile(fileName: str) -> Module: ...
```

### `core.Attribute`
```python
class Attribute:
    def __init__(self, name="attr", template="lineEditAndButton", category="General", connect="", expression=""): ...
    
    # Property Accessors
    def name(self) -> str: ...
    def setName(self, name: str): ...
    def category(self) -> str: ...
    def setCategory(self, category: str): ...
    def template(self) -> str: ...
    def setTemplate(self, template: str): ...
    def connect(self) -> str: ...
    def setConnect(self, connect: str): ...
    def expression(self) -> str: ...
    def setExpression(self, expression: str): ...
    
    # Value Getters & Setters
    def get(self, key: Optional[str] = None) -> Any: ...
    def set(self, value: Any, key: Optional[str] = None): ...
    def data(self) -> dict: ...
    def localData(self) -> dict: ...
    def setData(self, data: dict): ...
    def setLocalData(self, data: dict): ...
    
    # Connections & Expressions
    def pull((): ...
    def push(): ...
    def executeExpression(): ...
    def findConnectionSource(self) -> Optional[Attribute]: ...
```

---

## 7. XML Example: Creating a Connected Rig Module Hierarchy

Here is a full XML layout demonstrating parent-child modules, multiple categories of widget templates, custom attribute expressions, cross-module attribute connections, and standard API usages inside `<run>` scripts:

```xml
<module name="root_character" muted="0" uid="f094f3d47efe4680b27c3d06b05f4ca6">
  <run><![CDATA[
# Execute main run logic
print("Rigging Character Name: ", @characterName)

# Execute child module programmatically if needed
ch_spine = module.child("spine_builder")
ch_spine.run()

# Set output value to child input connection
@set_spineJointCount(@jointCount)
  ]]></run>
  <doc><![CDATA[
## Root Character Builder
This is the root configuration module for Rig Builder modules.
- **Character Name**: Name prefix used in maya.
- **Joint Count**: Number of joints used in spine calculation.
  ]]></doc>
  <attributes>
    <attr name="characterName" template="lineEditAndButton" category="Settings" connect="">
      <![CDATA[{"value": "Hero", "placeholder": "Enter character name...", "buttonEnabled": false, "default": "value"}]]>
    </attr>
    <attr name="jointCount" template="lineEditAndButton" category="Settings" connect="">
      <![CDATA[{"value": 5, "validator": 1, "buttonEnabled": false, "default": "value"}]]>
    </attr>
    <attr name="spineJointCount" template="lineEditAndButton" category="Outputs" connect="">
      <![CDATA[{"value": 5, "validator": 1, "buttonEnabled": false, "default": "value"}]]>
    </attr>
  </attributes>
  <children>
    <module name="spine_builder" muted="0" uid="">
      <run><![CDATA[
# Spine module logic
print("Building Spine joints: ", @numJoints)
for i in range(@numJoints):
    print("Creating spine joint joint_{}".format(i))
      ]]></run>
      <attributes>
        <!-- This attribute connects to the parent root module output 'spineJointCount' -->
        <attr name="numJoints" template="lineEditAndButton" category="General" connect="../spineJointCount">
          <![CDATA[{"value": 5, "validator": 1, "buttonEnabled": false, "default": "value"}]]>
        </attr>
        <!-- Expression attribute evaluating calculations automatically -->
        <attr name="doubleJoints" template="lineEditAndButton" category="Expressions" connect="">
          <![CDATA[{"value": 10, "validator": 1, "buttonEnabled": false, "default": "value", "_expression": "value = ch(\"/numJoints\") * 2"}]]>
        </attr>
      </attributes>
    </module>
  </children>
</module>
```
