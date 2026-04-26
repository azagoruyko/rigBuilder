import math
from typing import Any, Optional, Tuple, TYPE_CHECKING
from ..utils import *

DEFAULT_WIDGETS_DATA = {
    "button": {"command": 'chset("/someAttr", 1)', "label": "Press me", "color": "", "default": "command"},
    "checkBox": {"checked": False, "default": "checked"},
    "comboBox": {"items": ["a", "b"], "current": "a", "default": "current"},
    "curve": {"default": "cvs", "cvs": [[0.0, 1.0], [0.13973423457023273, 0.722154453101879], 
                                      [0.3352803473835302, -0.0019584480764515554], [0.5029205210752953, -0.0], 
                                      [0.6686136807168636, 0.0019357021806590401], [0.8623842449806401, 0.7231513901834298], [1.0, 1.0]]},
    "compound": {
        "widgets": [
            {"items": ["a", "b"], "current": 0, "default": "items"},
            {"command": 'chset("/someAttr", 1)', "label": "Press me", "color": "", "default": "command"}
        ],
        "values": [["a", "b"], 'chset("/someAttr", 1)'],
        "templates": ["listBox", "button"],
        "default": "values"
    },
    "fileSelector": {"value": "", "mode": "openFile", "filter": "All Files (*.*)", "title": "Select File", "default": "value"},
    "json": {"data": [{"a": 1, "b": 2}], "height": 200, "readonly": False, "default": "data"},
    "label": {"text": "Description", "default": "text"},
    "lineEditAndButton": {
        "value": "",
        "placeholder": "",
        "buttonCommand": 'print("Hello, world!")',
        "buttonLabel": "Button",
        "buttonEnabled": True,
        "min": 0,
        "max": 100,
        "validator": 0,
        "default": "value"
    },
    "listBox": {"items": ["a", "b"], "current": 0, "default": "items"},
    "radioButton": {"items": ["Helpers", "Run"], "current": 0, "default": "current", "columns": 3},
    "table": {"items": [["a", "1"]], "header": ["name", "value"], "default": "items"},
    "text": {"text": "", "height": 200, "default": "text"},
    "vector": {"value": [0.0, 0.0, 0.0], "default": "value", "dimension": 3, "columns": 3, "precision": 4}
}

def getAttributeFromValue(name: str, v: any, category: str = "") -> 'Attribute':
    """Get an attribute with proper widget template and default data from a value."""
    from ..core import Attribute

    template = "lineEditAndButton"

    if type(v) == bool:
        template = "checkBox"
    elif type(v) == dict:
        template = "json"
    elif type(v) == list and len(v) in [2, 3] and all(type(x) in [int, float] for x in v):
        template = "vector"
    elif type(v) == list:
        template = "listBox"
    
    attr = Attribute(name, template, category or "General")
    data = copyJson(DEFAULT_WIDGETS_DATA[template])
    
    if template == "lineEditAndButton":
        data["buttonEnabled"] = False
        
    attr.setData(data)
    attr.set(v)
    return attr

# curve functions

def listLerp(lst1: list[float], lst2: list[float], w: float) -> list[float]:    
    """Linearly interpolate between two lists of numbers.
    Useful for color or position interpolation.
    """
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
    
def curve_evaluate(data: dict, param: float, *, epsilon: float = 1e-3) -> list[float]:
    """Evaluate a bezier curve at the given 0-1 parameter."""
    return evaluateBezierCurve(data["cvs"], param, epsilon=epsilon)

def curve_evaluateFromX(data: dict, x: float, *, epsilon: float = 1e-3) -> list[float]: 
    """Evaluate a bezier curve at a specific X coordinate.
    
    Useful when one axis represents time or a sorted parameter.
    """
    return evaluateBezierCurveFromX(data["cvs"], x, epsilon=epsilon)

# comboBox functions

def comboBox_items(data: dict) -> list[str]:
    """Get the available items from a combo box widget's data.
    """
    return data["items"]

def comboBox_setItems(data: dict, items: list[str]):
    """Replace all items in a combo box widget's data.
    """
    data["items"] = items
