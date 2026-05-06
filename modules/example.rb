<module name="example" muted="0" uid="f094f3d47efe4680b27c3d06b05f4ca6">
<run><![CDATA[import time
print("lineAttr:", @lineAttr, type(@lineAttr))

beginProgress("Some slow operation", 10)
for i in range(10):
    stepProgress(i)
    time.sleep(0.1)
endProgress()

@set_out_other("Hello world")

chset("/out_lst", [1,2,3])

# children access
ch = module.child("child") # or module.child(0)
ch.run()

]]></run>
<doc><![CDATA[## Example

Documentation supports `Markdown` syntax, even code blocks.

```
def someFunc():
	pass
```

Links supported as well.
- [Project page](https://github.com/azagoruyko/rigBuilder)
- [Open example module](module:example)

Happy creating!]]></doc>
<attributes>
<attr name="" template="button" category="General" connect=""><![CDATA[{"command": "# you can set json data directly\nmodule.attr.lineAttr.set({\"value\":5, \"list\":[1,2,3]})\n\n# or with ch/chset\nchset(\"/out_lst\", [\"a\", \"b\", \"c\"])\n\n# or even with @ syntax\n@set_slider(10)", "label": "Press me", "color": "#176f1a", "default": "command"}]]></attr>
<attr name="" template="label" category="General" connect=""><![CDATA[{"text": "<center><h3>You can use html markup here</h3></center>", "default": "text"}]]></attr>
<attr name="lineAttr" template="lineEditAndButton" category="General" connect=""><![CDATA[{"value": "", "placeholder": "You can set placeholder from the menu...", "buttonCommand": "print(\"Hello, world!\")", "buttonLabel": "Button", "buttonEnabled": false, "min": 0, "max": 100, "validator": 0, "default": "value"}]]></attr>
<attr name="out_lst" template="listBox" category="General" connect=""><![CDATA[{"items": [], "default": "items"}]]></attr>
<attr name="out_other" template="lineEditAndButton" category="General" connect=""><![CDATA[{"value": "", "placeholder": "", "buttonCommand": "print(\"Hello, world!\")", "buttonLabel": "Button", "buttonEnabled": false, "min": 0, "max": 100, "validator": 0, "default": "value"}]]></attr>
<attr name="slider" template="lineEditAndButton" category="General" connect=""><![CDATA[{"value": 10, "placeholder": "", "buttonCommand": "print(\"Hello, world!\")", "buttonLabel": "Button", "buttonEnabled": false, "min": 0, "max": 100, "validator": 1, "default": "value"}]]></attr>
<attr name="lst" template="listBox" category="Expression" connect=""><![CDATA[{"items": [], "default": "items", "_expression": "value = ch(\"/out_lst\")"}]]></attr>
<attr name="selected" template="lineEditAndButton" category="Expression" connect=""><![CDATA[{"value": [], "buttonCommand": "print(\"Hello, world!\")", "buttonLabel": "Button", "buttonEnabled": false, "min": 0, "max": 100, "validator": 0, "default": "value", "_expression": "value = ch(\"/lst\")"}]]></attr>
</attributes>
<children>
<module name="child" muted="1" uid="">
<run><![CDATA[print("I'm a muted child, but can be run directly with Module.run")
print("lineAttr = {}".format(ch("../lineAttr")))]]></run>
<attributes>
<attr name="input" template="lineEditAndButton" category="General" connect="/out_other"><![CDATA[{"value": "", "buttonCommand": "print(\"Hello, world!\")", "buttonLabel": "Button", "buttonEnabled": false, "min": 0, "max": 100, "validator": 0, "default": "value"}]]></attr>
<attr name="input_edited" template="lineEditAndButton" category="General" connect=""><![CDATA[{"value": "_edited!", "buttonCommand": "print(\"Hello, world!\")", "buttonLabel": "Button", "buttonEnabled": false, "min": 0, "max": 100, "validator": 0, "default": "value", "_expression": "value = ch(\"/input\") + \"_edited!\""}]]></attr>
<attr name="slider" template="lineEditAndButton" category="General" connect="/slider"><![CDATA[{"value": 10, "buttonCommand": "print(\"Hello, world!\")", "buttonLabel": "Button", "buttonEnabled": false, "min": 0, "max": 100, "validator": 1, "default": "value", "_expression": "chset(\"/out_slider\", value+1)"}]]></attr>
<attr name="out_slider" template="lineEditAndButton" category="General" connect=""><![CDATA[{"value": 11, "buttonCommand": "print(\"Hello, world!\")", "buttonLabel": "Button", "buttonEnabled": false, "min": 0, "max": 100, "validator": 0, "default": "value"}]]></attr>
<attr name="table" template="table" category="General" connect=""><![CDATA[{"items": [[10, 11]], "header": ["name", "value"], "default": "items", "_expression": "a = ch(\"/slider\")\nb = ch(\"/out_slider\")\nvalue = [[a,b]]"}]]></attr>
</attributes>
</module>
<module name="curve" muted="0" uid="">
<attributes>
<attr name="param" template="lineEditAndButton" category="General" connect=""><![CDATA[{"value": 0.0, "buttonCommand": "print(\"Hello, world!\")", "buttonLabel": "Button", "buttonEnabled": false, "min": 0, "max": 1, "validator": 2, "default": "value", "_expression": "p = curve_evaluateFromX(chdata(\"/curve\"), value)\nchset(\"/out_vec\", p)"}]]></attr>
<attr name="curve" template="curve" category="General" connect=""><![CDATA[{"cvs": [[0.0, 1.0], [0.1364919774234294, 0.7236900971443566], [0.3293209876543207, -0.0], [0.49398148148148113, -0.0], [0.6626543209876541, -0.0], [0.8591423581319826, 0.7216353982411047], [1.0, 1.0]], "default": "cvs"}]]></attr>
<attr name="out_vec" template="vector" category="General" connect=""><![CDATA[{"value": [0.0008004017767750135, 0.9983758855280973], "default": "value", "dimension": 2, "precision": 4, "columns": 3}]]></attr>
<attr name="node" template="lineEditAndButton" category="General" connect=""><![CDATA[{"value": "", "buttonCommand": "import maya.cmds as cmds\nls = cmds.ls(sl=True)\nif ls: value = ls[0]", "buttonLabel": "<", "buttonEnabled": true, "min": 0, "max": 100, "validator": 0, "default": "value"}]]></attr>
</attributes>
</module>
</children>
</module>