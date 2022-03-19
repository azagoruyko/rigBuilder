# Rig Builder
Rig Builder is an easy to use ui maker for python scripts. Mostly used in Maya rigging.

![rb1](https://user-images.githubusercontent.com/9614751/159115306-4226af19-0d0a-4096-876c-f2180257b7f6.PNG)

## How to run
Add *rigBuilder* folder to your script path and run the following:
```python
import rigBuilder
rigBuilder.mainWindow.show() 
```

## File structure
| Name | Description |
| -- | -- |
|modules |All modules in xml |
|qss|Dark style |
|utils | Utilities such as yapf for python formatting |
|widgets | Attribute widgets|
|classes.py	| Definition of the two main classes: Attribute and Module|
|editor.py |	Python code editor|
|templateWidgets.py |	Widgets set up here|

## The Basics
The main working element is a module. The module is a container with attributes and executable Python code.
Modules can be hierarchically linked. Data is stored in attributes. Attribute is a field that contains json-compatible data:
* Numbers  -  12, 3.14, -0.123
* Strings  -  Hello world!
* Lists  -  [This, list, [1,2,3]]
* Dictionaries  -  {a: 1, b: 2, list:[1,2,3]}

The attributes store all the information about the corresponding widget. By transmitting such information, connections are implemented.

Modules are launched sequentially from top to bottom in the hierarchy, starting from the current module. In the module code, its own attributes are available as variables with the @ prefix.

There are three kinds of variables for each attribute:
* Default value (@).<br>
  Attribute name prefixed with @: `@input`, `@curve`.<br> 
  This is the value that the widget represents.
* All attribute data (@_data).<br>
  `@input_data`, `@curve_data`.<br>
  By changing this data, you can edit the behavior of the widget. 
* Attribute value setting function (@set) <br>
  `@set_input(3)`, `@set_list([1,2,3,4])`<br>
  This sets the default value of the attribute.
  
## Connections
Module attributes can be connected to each other. You can connect either to parent attributes or to adjacent ones in any nesting. Thus, any parent module can always be considered completely independent (since no child can communicate with attributes above the parent). Only attributes with the same widget type can be connected! Connections are bidirectional - you can change either end of the connection.

## Representation of the module

![scheme drawio (2)](https://user-images.githubusercontent.com/9614751/159116041-0eb5c6d9-ce91-41a6-959e-425a5fad063e.png)

## Writing code
In general, the code is written in the usual way, except that you can use attribute variables using @ as `@set_output(@input * 2)`
In addition, several predefined variables and functions are available:

| Variable | Description |
| -- | -- |
|MODULE_NAME |	Current module name |
|MODULE_TYPE |	Current module type |
|SHOULD_RUN_CHILDREN |	If False then don’t run children |
|copyJson (function) |	Fast copy json-compatible data |
|error/warning (function) |	Error/warning in log |
|evaluateBezierCurve (function) |	For curve widget. Evaluate point on bezier f(@curve, param) => [x, y] |
|evaluateBezierCurveFromX (function) |	For curve widget. Find such point P(x, y), that P.x = param, f(@curve, param) => [x, y] |
