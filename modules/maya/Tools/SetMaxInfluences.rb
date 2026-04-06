<module name="setMaxInfluences" muted="0" uid="ba683572a8564671832cbe81d0fc0b8c">
<run><![CDATA[import pymel.core as pm

def setMaxInfluences(geo, maxinf=4):
    geo = pm.PyNode(geo)
    skin = pm.mel.eval("findRelatedSkinCluster "+geo)
    if not skin:
        pm.warning("setMaxInfluences: cannot find skinCluster on '%s'"%geo)
        return
    
    invalidIndices = []
    
    beginProgress("Set max influences", geo.numVertices(), 0.25)
    for i in range(geo.numVertices()):
        stepProgress(i)
        
        vtx = geo + ".vtx[%d]"%i
        weights = pm.skinPercent(skin, vtx, ignoreBelow=0.0001,query=True, value=True)
        
        if len(weights) > maxinf:
            invalidIndices.append(i)
            
            maxWeights = [0] * len(weights)
            for w in weights:                               
                # Move the target influence down until the bottom is reached (-1) or the next influence is greater
                j = len(weights)-1
                while j >= 0 and w > maxWeights[j]: 
                    j -= 1
                j += 1
                
                k = len(weights)-1
                while k > j:
                    maxWeights[k] = maxWeights[k-1]
                    k -= 1
                    
                maxWeights[k] = w
                 
            pruneValue = maxWeights[maxinf] + 0.0001
            pm.skinPercent(skin, vtx, pruneWeights=pruneValue)                             
    endProgress()
    print(invalidIndices)
    
if pm.objExists(@geo):
    setMaxInfluences(@geo, @maxInf)        
else:
    warning("Cannot find '%s' geometry"%@geo)    ]]></run>
<doc><![CDATA[## Summary

The script trims skin‑influence weights on a selected geometry to keep each vertex’s influence list below a specified maximum. It locates the geometry’s skin cluster, evaluates every vertex’s influence weights, and removes the lowest weights when the count exceeds the limit. The indices of affected vertices are gathered and reported, and the script can be run with command‑line arguments for geometry name and maximum influence count, issuing a warning when the geometry cannot be found.  

## Use cases  

- Pre‑processing skin weights for optimization or export constraints.  
- Enforcing a fixed maximum number of influences for compatibility with certain game engines.  
- Auditing and cleaning up character rigs during pipeline reviews.]]></doc>
<attributes>
<attr name="geo" template="lineEditAndButton" category="General" connect=""><![CDATA[{"default": "value", "buttonCommand": "import maya.cmds as cmds\nls = cmds.ls(sl=True)\nif ls: value = ls[0]", "buttonLabel": "<", "value": "Cat_geo"}]]></attr>
<attr name="maxInf" template="lineEditAndButton" category="General" connect=""><![CDATA[{"default": "value", "max": "10", "validator": 1, "value": 4, "min": "2", "buttonEnabled": false}]]></attr>
</attributes>
</module>