<module name="bindMode" muted="0" uid="c7ae99e054f94721afc9256cf449e180">
<run><![CDATA[import pymel.core as pm

joints = [pm.PyNode(j) for j in @joints]

def getJointsSkinClusters(joint):
    skins = [obj for obj in pm.PyNode(joint).worldMatrix.listConnections() if pm.objectType(obj)=="skinCluster"]
    return set(skins)

if @mode == 0: # bind
    for j in joints:
        for skin in getJointsSkinClusters(j):
            idx = skin.indexForInfluenceObject(j)
        
            if not pm.isConnected(j.worldInverseMatrix, skin.bindPreMatrix[idx]):
                j.worldInverseMatrix >> skin.bindPreMatrix[idx]
    
    print("Binded")
    
elif @mode == 1: # unbind
    for j in joints:
        for skin in getJointsSkinClusters(j):
            idx = skin.indexForInfluenceObject(j)
        
            matrix = j.worldInverseMatrix.get()

            if pm.isConnected(j.worldInverseMatrix, skin.bindPreMatrix[idx]):
                j.worldInverseMatrix // skin.bindPreMatrix[idx]
                
            skin.bindPreMatrix[idx].set(matrix)
    
    print("Unbinded")
        ]]></run>
<doc><![CDATA[## Summary

The script synchronizes joint inverse world matrices with the pre‑bind matrices of influencing skin clusters. In bind mode it connects each joint’s `worldInverseMatrix` to the corresponding entry in the skin’s `bindPreMatrix`, effectively locking the joint to the skin. In unbind mode it disconnects that linkage, stores the current matrix into the skin’s pre‑bind slot, and leaves the joint and skin independent again, thereby enabling toggling of joint binding state to skin clusters.

## Use cases

- Locking joints to their skin clusters for stable deformation in bind mode.  
- Restoring independent joint control by storing current matrices in unbind mode.  
- Precision control of skin binding state for animation rigging workflows.]]></doc>
<attributes>
<attr name="" template="label" category="General" connect=""><![CDATA[{"text": "<html>\nHow to use: <br>\n1. Set joints and press <b>Run</b> with Unbind mode.<br>\n2. Change joints position and press <b>Run</b> with Bind mode.<br>\n</html>", "default": "text"}]]></attr>
<attr name="mode" template="radioButton" category="General" connect=""><![CDATA[{"items": ["Bind", "Unbind"], "current": 0, "columns": 3, "default": "current"}]]></attr>
<attr name="joints" template="listBox" category="General" connect=""><![CDATA[{"items": ["pelvis"], "selected": [], "default": "items"}]]></attr>
</attributes>
</module>