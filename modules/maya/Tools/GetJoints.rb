<module name="getJoints" muted="0" uid="9f20a01b042e46d389ce6774b7248fc3">
<run><![CDATA[import pymel.core as pm

joints = []
for skin in @skinClusters:
    skin = pm.PyNode(skin)
    
    for inf in skin.influenceObjects():
        if inf not in joints:
            joints.append(inf.name())
            
@set_outJoints(joints)]]></run>
<doc><![CDATA[**Summary**  
The script collects the names of all joint influences affecting a set of Maya skin clusters. For each skin cluster, it scans the influencing joints, aggregates unique names, and passes the compiled list to the `set_outJoints` function for downstream use.

**Use cases**  
- Extract every joint involved in a character’s skinning setup.  
- Populate a UI or data structure with the influencing joint list.  
- Prepare a list of joints for automated rigging or baking operations.  
- Provide input to downstream tools that require joint names as arguments.]]></doc>
<attributes>
<attr name="skinClusters" template="lineEditAndButton" category="General" connect=""><![CDATA[{"default": "value", "buttonCommand": "import pymel.core as pm\n\nls = pm.ls(sl=True, fl=True)\n    \nvalue = []\nfor obj in ls:\n\tskin = pm.mel.eval(\"findRelatedSkinCluster \"+obj)\n\tif skin and skin not in value:\n\t\tvalue.append(skin)\n", "buttonLabel": "Get skinClusters by mesh", "value": ["skinCluster164"]}]]></attr>
<attr name="" template="label" category="General" connect=""><![CDATA[{"default": "text", "text": "Press <b>Run</b> to get skinClusters' joints."}]]></attr>
<attr name="outJoints" template="listBox" category="General" connect=""><![CDATA[{"default": "items", "items": ["root", "Root_M", "Spine1_M", "Spine1Part1_M", "Spine2_M", "Chest_M", "Neck_M", "NeckPart1_M", "Head_M", "M_jaw_joint", "Scapula_R", "Shoulder_R", "ShoulderPart1_R", "Elbow_R", "R_elbow_lowPsd_joint", "Scapula_L", "Shoulder_L", "ShoulderPart1_L", "Elbow_L", "L_elbow_upPsd_joint", "Hip_R", "Hip_L"]}]]></attr>
</attributes>
</module>