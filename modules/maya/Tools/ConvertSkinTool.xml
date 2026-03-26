<module name="convertSkinTool" muted="0" uid="c7568f79334f48238ef02aacbae45fbe">
<run><![CDATA[# The script moves joints and use current deformer to get skin weights for each joint.

import maya.api.OpenMaya as om
import pymel.core as pm
import maya.mel as mel

def getMDagPath(nodeName):
    sel = om.MSelectionList()
    sel.add(nodeName)
    return sel.getDagPath(0)
    
meshFn = om.MFnMesh(getMDagPath(@skinGeo))
origPoints = meshFn.getPoints(om.MSpace.kWorld)

skin = pm.mel.eval("findRelatedSkinCluster \"%s\""%@skinGeo)
if not skin:
    pm.error("Cannot find skinCluster on "+@skinGeo)
skin = pm.PyNode(skin)    

beginProgress("Converting...", len(@joints))

for i, j in enumerate(@joints):
    stepProgress(i)
    j = pm.PyNode(j)
    
    old = j.ty.get()
    
    j.ty.set(old+1)
    
    idx = skin.indexForInfluenceObject(j)
    
    points = meshFn.getPoints(om.MSpace.kWorld)    
    
    for i in range(len(points)):
        w = (origPoints[i] - points[i]).length()
        pm.setAttr("%s.weightList[%d].weights[%d]"%(skin, i, idx), w)
    
    j.ty.set(old)
    
endProgress()
]]></run>
<attributes>
<attr name="" template="label" category="General" connect=""><![CDATA[{"text": "Make sure <b>skinGeo</b> has both skinCluster\nand a custom deformer. <u>Disable skinCluster!</u>", "default": "text"}]]></attr>
<attr name="skinGeo" template="lineEditAndButton" category="General" connect=""><![CDATA[{"value": "pCube1", "buttonCommand": "import maya.cmds as cmds\nls = cmds.ls(sl=True)\nif ls: value = ls[0]", "buttonLabel": "<", "default": "value"}]]></attr>
<attr name="joints" template="listBox" category="General" connect=""><![CDATA[{"items": ["joint1", "joint2", "joint3", "joint4"], "default": "items"}]]></attr>
</attributes>
<children>
</children>
</module>