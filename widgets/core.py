import math
from ..utils import *

# curve functions

def listLerp(lst1, lst2, w):    
    return [p1*(1-w) + p2*w for p1, p2 in zip(lst1, lst2)]

def evaluateBezier(p1, p2, p3, p4, param): # De Casteljau's algorithm
    p1_p2 = listLerp(p1, p2, param)
    p2_p3 = listLerp(p2, p3, param)
    p3_p4 = listLerp(p3, p4, param)

    p1_p2_p2_p3 = listLerp(p1_p2, p2_p3, param)
    p2_p3_p3_p4 = listLerp(p2_p3, p3_p4, param)
    return listLerp(p1_p2_p2_p3, p2_p3_p3_p4, param)

def bezierSplit(p1, p2, p3, p4, at=0.5):
    p1_p2 = listLerp(p1, p2, at)
    p2_p3 = listLerp(p2, p3, at)
    p3_p4 = listLerp(p3, p4, at)

    p1_p2_p2_p3 = listLerp(p1_p2, p2_p3, at)
    p2_p3_p3_p4 = listLerp(p2_p3, p3_p4, at)
    p = listLerp(p1_p2_p2_p3, p2_p3_p3_p4, at)

    return (p1, p1_p2, p1_p2_p2_p3, p), (p, p2_p3_p3_p4, p3_p4, p4)

def findFromX(p1, p2, p3, p4, x, *, epsilon=1e-3):
    cvs1, cvs2 = bezierSplit(p1, p2, p3, p4)
    midp = cvs2[0]

    if abs(midp[0] - x) < epsilon:
        return midp
    elif x < midp[0]:
        return findFromX(cvs1[0], cvs1[1], cvs1[2], cvs1[3], x, epsilon=epsilon)
    else:
        return findFromX(cvs2[0], cvs2[1], cvs2[2], cvs2[3], x, epsilon=epsilon)

def evaluateBezierCurve(cvs, param, *, epsilon=1e-3):
    param = clamp(param, 0, 1)
    absParam = param * (math.floor((len(cvs) + 2) / 3.0) - 1)

    offset = int(math.floor(absParam - 1e-5))
    if offset < 0:
        offset = 0

    t = absParam - offset

    p1 = cvs[offset * 3]
    p2 = cvs[offset * 3 + 1]
    p3 = cvs[offset * 3 + 2]
    p4 = cvs[offset * 3 + 3]

    return evaluateBezier(p1, p2, p3, p4, t)
    
def evaluateBezierCurveFromX(cvs, x, *, epsilon=1e-3):
    x = clamp(x, 0, 1)

    for i in range(0, len(cvs), 3):
        if cvs[i][0] > x:
            break

    return findFromX(cvs[i-3], cvs[i-2], cvs[i-1], cvs[i], x, epsilon=epsilon)

def normalizedPoint(p, minX, maxX, minY, maxY):
    x = (p[0] - minX) / (maxX - minX)
    y = (p[1] - minY) / (maxY - minY)
    return [x, y]
    
def curve_evaluate(data, param, *, epsilon=1e-3):
    return evaluateBezierCurve(data["cvs"], param, epsilon=epsilon)

def curve_evaluateFromX(data, param, *, epsilon=1e-3): 
    return evaluateBezierCurveFromX(data["cvs"], param, epsilon=epsilon)

# listBox functions

def listBox_setSelected(data, indices):
    data["selected"] = indices

def listBox_selected(data):
    return [data["items"][idx] for idx in data["selected"] if idx < len(data["items"])]    

# comboBox functions

def comboBox_items(data):
    return data["items"]

def comboBox_setItems(data, items):
    data["items"] = items

# button functions

def runButtonCommand(module, buttonLabel):
    """Execute button command by label.
    
    Args:
        module: Module object containing attributes
        buttonLabel: Label text of the button to execute
    
    Returns:
        dict: Environment dictionary after execution
    """
    for attr in module.attributes():
        if attr.template() in ["button", "lineEditAndButton"]:
            data = attr.localData()
            if data.get("buttonLabel") == buttonLabel or data.get("label") == buttonLabel:
                command = data.get("buttonCommand") or data.get("command", "")
                if command:
                    ctx = module.context()
                    if attr.template() == "lineEditAndButton":
                        ctx["value"] = smartConversion(data.get("value", ""))
                    
                    exec(command, ctx)
                    
                    # Update value for lineEditAndButton
                    if attr.template() == "lineEditAndButton":
                        data["value"] = ctx.get("value", data.get("value", ""))
                        attr.setData(data)
                    
                    return ctx
    
    raise ValueError(f"Button with label '{buttonLabel}' not found in module '{module.name()}'")    