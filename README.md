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
The main working element of the program is the module. A module is a container with attributes and executable Python code.
Modules can be hierarchically linked. Data is stored in attributes. Attribute is a field that contains json-compatible data:
* Numbers  -  12, 3.14, -0.123
* Strings  -  Hello world!
* Lists  -  [This, list, [1,2,3]]
* Dictionaries  -  {a: 1, b: 2, list:[1,2,3]}

The attributes store all the information describing the corresponding widget. By transmitting such information, the system of connections is implemented.

Modules are launched sequentially from top to bottom in the hierarchy, starting from the current one. In the module code, its own attributes are available as variables with the @ prefix.

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

