<module name="replaceSkinJoint" muted="0" uid="b7606eb6a4484ca2a9131f7f9290d458">
<run><![CDATA[import pymel.core as pm

sourceJoint = pm.PyNode(@sourceJoint)
destinationJoint = pm.PyNode(@destinationJoint)

for p in sourceJoint.wm.outputs(p=True,):
    destinationJoint.wm >> p
    
    if not destinationJoint.hasAttr("lockInfluenceWeights"):
        destinationJoint.addAttr("lockInfluenceWeights", at="bool", dv=False)
    
    destinationJoint.lockInfluenceWeights >> p.node().lockWeights[p.index()]
    
    if @updatePreMatrix:
        p.node().bindPreMatrix[p.index()].set(destinationJoint.wim.get())
        
    print(p)        ]]></run>
<doc><![CDATA[## Summary

The script copies weight manager connections from a source joint to a destination joint, replicating the same animation influence across all output nodes. It secures a boolean attribute on the destination to lock weight values and links it to each weight node. Optionally, it synchronizes each weight node’s pre‑matrix with the destination’s inverse world matrix, resulting in a coherent set of weight influences ready for subsequent rigging tasks.

## Use cases

- Replicating animation influences during rig transfer or mirroring.
- Automating the locking of weight node influence to prevent unintended modifications.
- Aligning weight pre‑matrices for consistent behavior across different rig sections.]]></doc>
<attributes>
<attr name="sourceJoint" template="lineEditAndButton" category="General" connect=""><![CDATA[{"default": "value", "buttonCommand": "import maya.cmds as cmds\nls = cmds.ls(sl=True)\nif ls: value = ls[0]", "buttonLabel": "<", "value": "joint1"}]]></attr>
<attr name="destinationJoint" template="lineEditAndButton" category="General" connect=""><![CDATA[{"default": "value", "buttonCommand": "import maya.cmds as cmds\nls = cmds.ls(sl=True)\nif ls: value = ls[0]", "buttonLabel": "<", "value": "joint2"}]]></attr>
<attr name="updatePreMatrix" template="checkBox" category="General" connect=""><![CDATA[{"default": "checked", "checked": true}]]></attr>
</attributes>
</module>