# RigBuilder Core Documentation

This documentation covers the internal structure and format of RigBuilder modules and widgets for AI systems to create and manipulate modules programmatically.

## Module XML Format

Modules are stored as XML files with a specific structure that defines their behavior, attributes, and hierarchy.

### Basic Module Structure

```xml
<module name="moduleName" muted="0" uid="uniqueId">
    <run><![CDATA[
        # Python execution code goes here
        print("Module is running...")
        # Use @attributeName to access attribute values
        # Use @set_attributeName(value) to set attribute values
    ]]></run>
    
    <attributes>
        <!-- Attribute definitions go here -->
    </attributes>
    
    <children>
        <!-- Child modules go here -->
    </children>
</module>
```

### Module Attributes

- `name`: Module display name
- `muted`: "0" for active, "1" for muted (won't execute automatically)
- `uid`: Unique identifier (generated automatically when saving)

### Code Execution Context

In the `<run>` section, you have access to:
- `@attributeName` - Get attribute value
- `@set_attributeName(value)` - Set attribute value
- `module` - Current module object
- `ch(path)` - Get attribute value by path (e.g., "/childModule/attributeName")
- `chset(path, value)` - Set attribute value by path
- `chdata(path)` - Get attribute data by path
- Standard Python environment with print() for output

### Attribute XML Structure

```xml
<attr name="attributeName" template="widgetType" category="General" connect="">
    <![CDATA[{JSON_DATA_HERE}]]>
</attr>
```

#### Attribute Properties

- `name`: Attribute identifier (used in code as @name)
- `template`: Widget type (see Widget Types section)
- `category`: UI grouping category
- `connect`: Connection path to another attribute (e.g., "/parentModule/attributeName")

#### Special JSON Keys

- `default`: Specifies which JSON key contains the main value
- `_expression`: Python code executed when attribute updates

## Widget Types and JSON Data Format

### 1. label - Text Display

Displays static text with HTML support.

```json
{
    "text": "Module Description",
    "default": "text"
}
```

### 2. button - Action Button

Executes Python command when clicked.

```json
{
    "command": "print('Button clicked!')",
    "label": "Execute",
    "default": "label"
}
```

### 3. checkBox - Boolean Toggle

Simple true/false checkbox.

```json
{
    "checked": true,
    "default": "checked"
}
```

### 4. lineEdit - Text Input with Optional Validation

Text input field with optional numeric validation and slider.

```json
{
    "value": "text or number",
    "validator": 0,
    "min": 0,
    "max": 100,
    "default": "value"
}
```

**Validator Types:**
- `0`: Default (text input)
- `1`: Integer with range
- `2`: Float with range

**Integer Example with Range:**
```json
{
    "value": 50,
    "validator": 1,
    "min": 0,
    "max": 100,
    "default": "value"
}
```

**Float Example with Range:**
```json
{
    "value": 3.14,
    "validator": 2,
    "min": 0.0,
    "max": 10.0,
    "default": "value"
}
```

### 5. comboBox - Dropdown Selection

Dropdown list with selectable items.

```json
{
    "items": ["Option A", "Option B", "Option C"],
    "current": "Option A",
    "default": "current"
}
```

### 6. lineEditAndButton - Text Input with Action Button

Text field with associated button for actions like file selection.

```json
{
    "value": "current value",
    "buttonCommand": "value = 'New Value!'",
    "buttonLabel": "<",
    "default": "value"
}
```

**File Selection Example:**
```json
{
    "value": "",
    "buttonCommand": "from PySide6.QtWidgets import QFileDialog; import os\npath,_ = QFileDialog.getOpenFileName(None, 'Open file', os.path.expandvars(value))\nvalue = path or value",
    "buttonLabel": "...",
    "default": "value"
}
```

### 7. listBox - Multi-Selection List

List widget with multiple selection support.

```json
{
    "items": ["item1", "item2", "item3"],
    "selected": [0, 2],
    "default": "items"
}
```

### 8. radioButton - Single Selection from Group

Radio button group for exclusive selection.

```json
{
    "items": ["Option 1", "Option 2", "Option 3"],
    "current": 0,
    "columns": 3,
    "default": "current"
}
```

### 9. table - Data Table

Editable table for structured data.

```json
{
    "items": [
        ["Name", "Value"],
        ["item1", 10],
        ["item2", 20]
    ],
    "header": ["Name", "Value"],
    "default": "items"
}
```

### 10. text - Multi-line Text

Multi-line text editor with adjustable height.

```json
{
    "text": "Multi-line\ntext content\ngoes here",
    "height": 200,
    "default": "text"
}
```

### 11. vector - Numeric Vector Input

Multi-dimensional numeric input (2D to 16D).

```json
{
    "value": [1.0, 2.0, 3.0],
    "dimension": 3,
    "columns": 3,
    "precision": 4,
    "default": "value"
}
```

**2D Vector Example:**
```json
{
    "value": [0.0, 1.0],
    "dimension": 2,
    "columns": 2,
    "precision": 2,
    "default": "value"
}
```

### 12. curve - Bezier Curve Editor

Interactive Bezier curve for animations or mappings.

```json
{
    "cvs": [
        [0.0, 1.0],
        [0.33, 0.7],
        [0.66, 0.3],
        [1.0, 0.0]
    ],
    "default": "cvs"
}
```

### 13. json - Structured Data Editor

Tree-based JSON data editor for complex data structures.

```json
{
    "data": [
        {
            "name": "item1",
            "properties": {
                "enabled": true,
                "value": 42
            }
        }
    ],
    "height": 200,
    "readonly": false,
    "default": "data"
}
```

### 14. compound - Multiple Widgets Combined

Combines multiple widgets into a single attribute.

```json
{
    "templates": ["listBox", "button"],
    "widgets": [
        {
            "items": ["a", "b"],
            "selected": [],
            "default": "items"
        },
        {
            "command": "print('clicked')",
            "label": "Execute",
            "default": "label"
        }
    ],
    "values": [
        ["a", "b"],
        "Execute"
    ],
    "default": "values"
}
```

## Common Usage Patterns

### Creating Integer Slider

```json
{
    "value": 50,
    "validator": 1,
    "min": 0,
    "max": 100,
    "default": "value"
}
```

### Creating File Path Input

```json
{
    "value": "",
    "buttonCommand": "from PySide6.QtWidgets import QFileDialog\npath,_ = QFileDialog.getOpenFileName(None, 'Select File', value)\nvalue = path or value",
    "buttonLabel": "Browse...",
    "default": "value"
}
```

### Creating Object List from Maya

```json
{
    "items": [],
    "selected": [],
    "default": "items"
}
```

### Creating Progress Table

```json
{
    "items": [
        ["Task", "Status", "Progress"],
        ["Load Models", "Complete", 100],
        ["Apply Materials", "In Progress", 75],
        ["Export Scene", "Pending", 0]
    ],
    "header": ["Task", "Status", "Progress"],
    "default": "items"
}
```

## Attribute Connections and Expressions

### Connection System

Attributes can connect to other attributes using paths:

```xml
<attr name="output" template="lineEdit" category="General" connect="/input">
```

This connects the `output` attribute to the `input` attribute in the parent module.

### Expression System

Attributes can have Python expressions that execute when dependencies change:

```json
{
    "value": "processed_value",
    "default": "value",
    "_expression": "value = ch('/input').upper() + '_processed'"
}
```

**Available in expressions:**
- `data`: Current attribute data
- `value`: Current attribute value
- `ch(path)`: Get value from path
- `chset(path, val)`: Set value at path
- `module`: Current module

### Path Syntax

- `/attrName` - Attribute in parent module
- `/childModule/attrName` - Attribute in child module
- `../attrName` - Attribute in grandparent module
- `./attrName` - Attribute in current module

## API Functions for Widget Data

### Curve Functions
```python
curve_evaluate(data, param)          # Evaluate curve at parameter (0-1)
curve_evaluateFromX(data, x_value)   # Find Y value for given X
```

### List Functions
```python
listBox_selected(data)               # Get selected items
listBox_setSelected(data, indices)   # Set selection by indices
```

### ComboBox Functions
```python
comboBox_items(data)                 # Get all items
comboBox_setItems(data, items)       # Set items list
```

### Button Execution
```python
runButtonCommand(module, buttonLabel)  # Execute button by label
```

### Utility Functions
```python
smartConversion(text)                # Convert string to appropriate type
fromSmartConversion(value)           # Convert value back to string
clamp(value, min_val, max_val)      # Clamp value to range
```

## Creating Complex Modules

### Module with File Processing

```xml
<module name="FileProcessor" muted="0" uid="">
    <run><![CDATA[
        import os
        import json
        
        input_file = @input_file
        output_dir = @output_directory
        process_mode = @process_mode
        
        if not os.path.exists(input_file):
            print(f"Input file does not exist: {input_file}")
            exit()
        
        # Process based on mode
        if process_mode == 0:  # Copy mode
            import shutil
            output_file = os.path.join(output_dir, os.path.basename(input_file))
            shutil.copy2(input_file, output_file)
            @set_status(f"Copied to {output_file}")
        
        elif process_mode == 1:  # Analyze mode
            stats = os.stat(input_file)
            info = {
                "size": stats.st_size,
                "modified": stats.st_mtime,
                "name": os.path.basename(input_file)
            }
            @set_analysis_results(info)
            print(f"Analysis complete: {info}")
    ]]></run>
    
    <attributes>
        <attr name="input_file" template="lineEditAndButton" category="Input">
            <![CDATA[{
                "value": "",
                "buttonCommand": "from PySide6.QtWidgets import QFileDialog\npath,_ = QFileDialog.getOpenFileName(None, 'Select Input File', value)\nvalue = path or value",
                "buttonLabel": "Browse...",
                "default": "value"
            }]]>
        </attr>
        
        <attr name="output_directory" template="lineEditAndButton" category="Input">
            <![CDATA[{
                "value": "",
                "buttonCommand": "from PySide6.QtWidgets import QFileDialog\npath = QFileDialog.getExistingDirectory(None, 'Select Output Directory', value)\nvalue = path or value",
                "buttonLabel": "Browse...",
                "default": "value"
            }]]>
        </attr>
        
        <attr name="process_mode" template="radioButton" category="Settings">
            <![CDATA[{
                "items": ["Copy", "Analyze"],
                "current": 0,
                "columns": 2,
                "default": "current"
            }]]>
        </attr>
        
        <attr name="status" template="text" category="Output">
            <![CDATA[{
                "text": "Ready to process",
                "height": 100,
                "default": "text"
            }]]>
        </attr>
        
        <attr name="analysis_results" template="json" category="Output">
            <![CDATA[{
                "data": {},
                "height": 200,
                "readonly": true,
                "default": "data"
            }]]>
        </attr>
    </attributes>
    
    <children></children>
</module>
```

This documentation provides comprehensive information for AI systems to understand and create RigBuilder modules with proper widget configurations and data structures.