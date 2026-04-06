<module name="convertSkinTool" muted="0" uid="c7568f79334f48238ef02aacbae45fbe">
<run><![CDATA[# The script moves joints and uses the current deformer to sample skin weights per joint.

import maya.api.OpenMaya as om
import pymel.core as pm

SAMPLING_OFFSET = 1


def getMDagPath(nodeName):
    """Returns MDagPath for the given node name."""
    sel = om.MSelectionList()
    sel.add(nodeName)
    return sel.getDagPath(0)


meshFn = om.MFnMesh(getMDagPath(@skinGeo))
origPoints = meshFn.getPoints(om.MSpace.kWorld)

skin = pm.mel.eval("findRelatedSkinCluster \"%s\"" % @skinGeo)
if not skin:
    pm.error("Cannot find skinCluster on " + @skinGeo)
skin = pm.PyNode(skin)

beginProgress("Converting...", len(@joints))

for jointIdx, jointName in enumerate(@joints):
    stepProgress(jointIdx)
    joint = pm.PyNode(jointName)
    oldTy = joint.ty.get()

    joint.ty.set(oldTy + SAMPLING_OFFSET)
    inflIdx = skin.indexForInfluenceObject(joint)
    deformedPoints = meshFn.getPoints(om.MSpace.kWorld)

    for vertIdx in range(len(deformedPoints)):
        weight = (origPoints[vertIdx] - deformedPoints[vertIdx]).length()
        pm.setAttr("%s.weightList[%d].weights[%d]" % (skin, vertIdx, inflIdx), weight)

    joint.ty.set(oldTy)

endProgress()]]></run>
<doc><![CDATA[**Summary**  
The script calculates initial skin‐cluster weights for a skinned mesh by measuring each vertex’s displacement when a joint is temporarily offset along the Y‑axis. It records the mesh’s original vertex positions, iterates over the selected joints, writes the resulting distance magnitudes as new weights, and reports progress through Maya’s progress utilities.

**Use cases**
- Automated skin weight generation for rigs where simple distance‑based weights are adequate.  
- Quick prototyping of joint influence on a mesh without manual weight painting.  
- Behavior verification by observing how small joint translations affect vertex positions.  
- Batch processing of multiple joints to set initial weight values before fine‑tuning.]]></doc>
<attributes>
<attr name="" template="label" category="General" connect=""><![CDATA[{"text": "Make sure <b>skinGeo</b> has both skinCluster\nand a custom deformer. <u>Disable skinCluster!</u>", "default": "text"}]]></attr>
<attr name="skinGeo" template="lineEditAndButton" category="General" connect=""><![CDATA[{"value": "pCube1", "buttonCommand": "import maya.cmds as cmds\nls = cmds.ls(sl=True)\nif ls: value = ls[0]", "buttonLabel": "<", "buttonEnabled": true, "min": 0, "max": 100, "validator": 0, "default": "value"}]]></attr>
<attr name="joints" template="listBox" category="General" connect=""><![CDATA[{"items": ["joint1", "joint2", "joint3", "joint4"], "default": "items"}]]></attr>
</attributes>
</module>