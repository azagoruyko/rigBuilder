"""Maya native UI and runner for Rig Builder modules.

Allows running and editing Rig Builder modules directly inside Maya using native maya.cmds.

Usage in Maya:
    from rigBuilder.host.ui.maya import mainWindow
    mainWindow.show()
"""
from __future__ import annotations

import os
import json
import math
from functools import partial
from typing import Optional, Union, Any

import maya.cmds as cmds

from ...core import Module, Attribute, UidManager
from ...core.widgets import DEFAULT_WIDGETS_DATA
from ...core.settings import settings
from ...core.workspace import Workspace, flattenModules


def _with_undo(func):
    """Decorator to wrap execution in a Maya undo chunk."""
    def wrapper(*args, **kwargs):
        cmds.undoInfo(openChunk=True)
        try:
            return func(*args, **kwargs)
        finally:
            cmds.undoInfo(closeChunk=True)
    return wrapper


def _pointsToRampString(points: Any, interp: int = 2) -> str:
    """Convert points list or curve dict to Maya gradientControlNoAttr string (val,pos,interp,...)."""
    if isinstance(points, dict):
        raw = points.get("cvs", [])
        knots = raw[::3] if len(raw) >= 4 and (len(raw) - 1) % 3 == 0 else raw
    elif isinstance(points, (list, tuple)):
        if len(points) >= 7 and (len(points) - 1) % 3 == 0:
            knots = points[::3]
        else:
            knots = points
    else:
        return f"1.0,0.0,{interp},0.0,1.0,{interp}"

    parts = [f"{float(p[1]):.4f},{float(p[0]):.4f},{interp}" for p in knots if isinstance(p, (list, tuple)) and len(p) >= 2]
    return ",".join(parts) if parts else f"1.0,0.0,{interp},0.0,1.0,{interp}"


def _rampStringToPoints(rampStr: str) -> list[list[float]]:
    """Convert Maya gradientControlNoAttr string (val,pos,interp,...) to key points [[x, y], ...]."""
    if not rampStr:
        return [[0.0, 1.0], [1.0, 0.0]]
    tokens = rampStr.split(",")
    pts = []
    for i in range(0, len(tokens) - 2, 3):
        try:
            val_y = round(float(tokens[i]), 4)
            pos_x = round(float(tokens[i + 1]), 4)
            pts.append([pos_x, val_y])
        except (ValueError, IndexError):
            pass
    return sorted(pts, key=lambda p: p[0]) if pts else [[0.0, 1.0], [1.0, 0.0]]


def _calculateBezierCVs(points: list[list[float]]) -> list[list[float]]:
    """Generate cubic Bezier CVs from key points for core evaluation."""
    if len(points) < 2:
        return points
    pts = sorted(points, key=lambda p: p[0])
    tangents = []
    for i, p in enumerate(pts):
        if i == 0:
            dx, dy = pts[1][0] - p[0], pts[1][1] - p[1]
        elif i == len(pts) - 1:
            dx, dy = p[0] - pts[i - 1][0], p[1] - pts[i - 1][1]
        else:
            dx, dy = pts[i + 1][0] - pts[i - 1][0], pts[i + 1][1] - pts[i - 1][1]
        length = math.hypot(dx, dy) or 1.0
        tangents.append([dx / length, dy / length])

    cvs = []
    for i in range(1, len(pts)):
        p1, p4 = pts[i - 1], pts[i]
        d = (p4[0] - p1[0]) / 3.0
        p2 = [round(p1[0] + tangents[i - 1][0] * d, 4), round(p1[1] + tangents[i - 1][1] * d, 4)]
        p3 = [round(p4[0] - tangents[i][0] * d, 4), round(p4[1] - tangents[i][1] * d, 4)]
        if i == 1:
            cvs.append(p1)
        cvs.extend([p2, p3, p4])
    return cvs


# ===========================================================================
# Maya Native Widget Hierarchy
# ===========================================================================

class MayaWidget:
    """Base class for Maya native template widgets."""

    ATTR_NAME_WIDTH: int = 110

    def __init__(self, attr: Attribute, module: Module):
        self.attr = attr
        self.module = module
        self.parentUI: Optional[Any] = None

    def buildUI(self):
        """Construct the Maya UI controls."""
        raise NotImplementedError

    def getValueFromUI(self) -> Any:
        """Query Maya controls and return current value."""
        return self.attr.get()

    def setValueToUI(self, value: Any):
        """Update Maya controls from attribute value."""
        pass

    def syncToAttribute(self):
        """Read value from UI controls and write back to attribute."""
        self.attr.set(self.getValueFromUI())


class LineEditAndButtonWidget(MayaWidget):
    """Widget for string, int, and float fields with optional slider and action button."""

    def __init__(self, attr: Attribute, module: Module):
        super().__init__(attr, module)
        self.ctrl: Optional[str] = None

    def buildUI(self):
        name, data, val = self.attr.name(), self.attr.data(), self.attr.get()
        btnEnabled = data.get("buttonEnabled", True)
        cmdStr = data.get("buttonCommand", "")
        btnLabel = data.get("buttonLabel", "Get")
        validator = data.get("validator", 0)
        minVal = data.get("min", 0)
        maxVal = data.get("max", 100)
        placeholder = data.get("placeholder", "")

        if validator == 1:  # integer field + slider
            minV, maxV, intVal = int(minVal), int(maxVal), int(val or 0)
            if btnEnabled:
                self.ctrl = cmds.intSliderButtonGrp(
                    label=name, field=True, minValue=minV, maxValue=maxV, value=intVal,
                    buttonLabel=btnLabel, buttonCommand=partial(self._onButtonClicked, cmdStr),
                    changeCommand=partial(self._onChanged),
                    columnWidth4=(self.ATTR_NAME_WIDTH, 50, 120, 45),
                    columnAlign4=("right", "left", "left", "left"),
                    adjustableColumn=3
                )
            else:
                self.ctrl = cmds.intSliderGrp(
                    label=name, field=True, minValue=minV, maxValue=maxV, value=intVal,
                    changeCommand=partial(self._onChanged),
                    columnWidth3=(self.ATTR_NAME_WIDTH, 50, 165),
                    columnAlign3=("right", "left", "left"),
                    adjustableColumn=3
                )
        elif validator == 2:  # float field + slider
            minV, maxV, fltVal = float(minVal), float(maxVal), float(val or 0.0)
            if btnEnabled:
                self.ctrl = cmds.floatSliderButtonGrp(
                    label=name, field=True, minValue=minV, maxValue=maxV, value=fltVal,
                    step=0.01, precision=3,
                    buttonLabel=btnLabel, buttonCommand=partial(self._onButtonClicked, cmdStr),
                    changeCommand=partial(self._onChanged),
                    columnWidth4=(self.ATTR_NAME_WIDTH, 55, 115, 45),
                    columnAlign4=("right", "left", "left", "left"),
                    adjustableColumn=3
                )
            else:
                self.ctrl = cmds.floatSliderGrp(
                    label=name, field=True, minValue=minV, maxValue=maxV, value=fltVal,
                    step=0.01, precision=3,
                    changeCommand=partial(self._onChanged),
                    columnWidth3=(self.ATTR_NAME_WIDTH, 55, 160),
                    columnAlign3=("right", "left", "left"),
                    adjustableColumn=3
                )
        else:  # text field
            strVal = str(val if val is not None else "")
            if btnEnabled:
                self.ctrl = cmds.textFieldButtonGrp(
                    label=name, text=strVal,
                    buttonLabel=btnLabel, buttonCommand=partial(self._onButtonClicked, cmdStr),
                    changeCommand=partial(self._onChanged),
                    columnWidth3=(self.ATTR_NAME_WIDTH, 170, 45),
                    columnAlign3=("right", "left", "left"),
                    adjustableColumn=2
                )
            else:
                self.ctrl = cmds.textFieldGrp(
                    label=name, text=strVal, placeholderText=placeholder,
                    changeCommand=partial(self._onChanged),
                    columnWidth2=(self.ATTR_NAME_WIDTH, 200),
                    columnAlign2=("right", "left"),
                    adjustableColumn=2
                )

    def _onChanged(self, *args):
        self.attr.set(self.getValueFromUI())

    @_with_undo
    def _onButtonClicked(self, cmdStr: str, *args):
        if not cmdStr:
            return

        res = self.module.executeCode(cmdStr)
        if res and res.get("value"):
            v = res.get("value")
            self.setValueToUI(v)
            self.attr.set(v)

        if self.parentUI:
            self.parentUI._updateUIFromAttributes()

    def getValueFromUI(self) -> Any:
        if not self.ctrl or not cmds.control(self.ctrl, exists=True):
            return self.attr.get()
        validator = self.attr.data().get("validator", 0)
        btnEnabled = self.attr.data().get("buttonEnabled", True)
        if validator == 1:
            cmd = cmds.intSliderButtonGrp if btnEnabled else cmds.intSliderGrp
            return int(cmd(self.ctrl, query=True, value=True))

        elif validator == 2:
            cmd = cmds.floatSliderButtonGrp if btnEnabled else cmds.floatSliderGrp
            return float(cmd(self.ctrl, query=True, value=True))

        else:
            cmd = cmds.textFieldButtonGrp if btnEnabled else cmds.textFieldGrp
            return str(cmd(self.ctrl, query=True, text=True))

    def setValueToUI(self, value: Any):
        if not self.ctrl or not cmds.control(self.ctrl, exists=True):
            return
        validator = self.attr.data().get("validator", 0)
        btnEnabled = self.attr.data().get("buttonEnabled", True)

        if validator == 1:
            cmd = cmds.intSliderButtonGrp if btnEnabled else cmds.intSliderGrp
            cmd(self.ctrl, edit=True, value=int(value or 0))

        elif validator == 2:
            cmd = cmds.floatSliderButtonGrp if btnEnabled else cmds.floatSliderGrp
            cmd(self.ctrl, edit=True, value=float(value or 0.0))

        else:
            cmd = cmds.textFieldButtonGrp if btnEnabled else cmds.textFieldGrp
            cmd(self.ctrl, edit=True, text=str(value if value is not None else ""))


class ButtonWidget(MayaWidget):
    """Widget for standalone action buttons."""

    def buildUI(self):
        cmdStr = self.attr.data().get("command", "")
        label = self.attr.data().get("label", self.attr.name())
        cmds.button(label=label, height=28, command=partial(self._onButtonClicked, cmdStr))

    @_with_undo
    def _onButtonClicked(self, cmdStr: str, *args):
        if cmdStr:
            self.module.executeCode(cmdStr)
            if self.parentUI:
                self.parentUI._updateUIFromAttributes()


class CheckBoxWidget(MayaWidget):
    """Widget for boolean attributes."""

    def __init__(self, attr: Attribute, module: Module):
        super().__init__(attr, module)
        self.ctrl: Optional[str] = None

    def buildUI(self):
        self.ctrl = cmds.checkBoxGrp(
            label=self.attr.name(),
            value1=bool(self.attr.get()),
            changeCommand=partial(self._onChanged),
            columnWidth2=(self.ATTR_NAME_WIDTH, 200),
            columnAlign2=("right", "left"),
            adjustableColumn=2
        )

    def _onChanged(self, *args):
        self.attr.set(self.getValueFromUI())

    def getValueFromUI(self) -> bool:
        if self.ctrl and cmds.control(self.ctrl, exists=True):
            return bool(cmds.checkBoxGrp(self.ctrl, query=True, value1=True))

        return bool(self.attr.get())

    def setValueToUI(self, value: Any):
        if self.ctrl and cmds.control(self.ctrl, exists=True):
            cmds.checkBoxGrp(self.ctrl, edit=True, value1=bool(value))


class ComboBoxWidget(MayaWidget):
    """Widget for dropdown choice attributes."""

    def __init__(self, attr: Attribute, module: Module):
        super().__init__(attr, module)
        self.ctrl: Optional[str] = None

    def buildUI(self):
        items = [str(i) for i in self.attr.data().get("items", [])]
        self.ctrl = cmds.optionMenuGrp(
            label=self.attr.name(),
            changeCommand=partial(self._onChanged),
            columnWidth2=(self.ATTR_NAME_WIDTH, 180),
            columnAlign2=("right", "left"),
            adjustableColumn=2
        )

        for item in items:
            cmds.menuItem(label=item)

        valStr = str(self.attr.get())
        if valStr in items:
            cmds.optionMenuGrp(self.ctrl, edit=True, value=valStr)

    def _onChanged(self, val: str, *args):
        self.attr.set(val)

    def getValueFromUI(self) -> str:
        if self.ctrl and cmds.control(self.ctrl, exists=True):
            return cmds.optionMenuGrp(self.ctrl, query=True, value=True)

        return str(self.attr.get())

    def setValueToUI(self, value: Any):
        if self.ctrl and cmds.control(self.ctrl, exists=True):
            items = [str(i) for i in self.attr.data().get("items", [])]

            if str(value) in items:
                cmds.optionMenuGrp(self.ctrl, edit=True, value=str(value))


class RadioButtonWidget(MayaWidget):
    """Widget for radio option collections."""

    def __init__(self, attr: Attribute, module: Module):
        super().__init__(attr, module)
        self.ctrl: Optional[str] = None

    def buildUI(self):
        items = [str(i) for i in self.attr.data().get("items", [])]
        numItems = min(len(items), 4)
        if not numItems:
            return

        val = self.attr.get()
        currIdx = int(val) if isinstance(val, (int, float)) and 0 <= int(val) < numItems else 0

        kwargs = {f"label{i+1}": items[i] for i in range(numItems)}
        self.ctrl = cmds.radioButtonGrp(
            label=self.attr.name(),
            numberOfRadioButtons=numItems,
            select=currIdx + 1,
            onCommand=partial(self._onSelected),
            columnWidth2=(self.ATTR_NAME_WIDTH, 200),
            columnAlign2=("right", "left"),
            adjustableColumn=2,
            **kwargs
        )

    def _onSelected(self, *args):
        self.attr.set(self.getValueFromUI())

    def getValueFromUI(self) -> int:
        if self.ctrl and cmds.control(self.ctrl, exists=True):
            sel = cmds.radioButtonGrp(self.ctrl, query=True, select=True)
            
            return max(sel - 1, 0)
        return 0

    def setValueToUI(self, value: Any):
        idx = int(value or 0)
        if self.ctrl and cmds.control(self.ctrl, exists=True):
            cmds.radioButtonGrp(self.ctrl, edit=True, select=idx + 1)


class VectorWidget(MayaWidget):
    """Widget for vector/multi-float arrays."""

    def __init__(self, attr: Attribute, module: Module):
        super().__init__(attr, module)
        self.ctrl: Optional[str] = None
        self.dim: int = 3

    def buildUI(self):
        v = self.attr.get() if isinstance(self.attr.get(), (list, tuple)) else [0.0, 0.0, 0.0]
        self.dim = min(max(len(v), 1), 4)
        val4 = [float(v[i]) if i < len(v) else 0.0 for i in range(4)]

        self.ctrl = cmds.floatFieldGrp(
            label=self.attr.name(),
            numberOfFields=self.dim,
            value=val4,
            precision=3,
            changeCommand=partial(self._onChanged),
            columnWidth2=(self.ATTR_NAME_WIDTH, 200),
            columnAlign2=("right", "left"),
            adjustableColumn=2
        )

    def _onChanged(self, *args):
        self.attr.set(self.getValueFromUI())

    def getValueFromUI(self) -> list[float]:
        if self.ctrl and cmds.control(self.ctrl, exists=True):
            vals = list(cmds.floatFieldGrp(self.ctrl, query=True, value=True) or [])
            return vals[:self.dim]
        return self.attr.get() if isinstance(self.attr.get(), list) else [0.0, 0.0, 0.0]

    def setValueToUI(self, value: Any):
        v = value if isinstance(value, (list, tuple)) else [0.0, 0.0, 0.0]
        if self.ctrl and cmds.control(self.ctrl, exists=True):
            val4 = [float(v[i]) if i < len(v) else 0.0 for i in range(4)]
            cmds.floatFieldGrp(self.ctrl, edit=True, value=val4)


class FileSelectorWidget(MayaWidget):
    """Widget for selecting file/folder paths."""

    def __init__(self, attr: Attribute, module: Module):
        super().__init__(attr, module)
        self.ctrl: Optional[str] = None

    def buildUI(self):
        data = self.attr.data()
        mode = data.get("mode", "openFile")
        fileMode = 2 if mode == "directory" else (0 if mode == "saveFile" else 1)
        self.ctrl = cmds.textFieldButtonGrp(
            label=self.attr.name(),
            text=str(self.attr.get() or ""),
            buttonLabel="📁",
            buttonCommand=partial(self._onBrowseClicked, fileMode, data.get("title", "Select File")),
            changeCommand=partial(self._onChanged),
            columnWidth3=(self.ATTR_NAME_WIDTH, 170, 40),
            columnAlign3=("right", "left", "left"),
            adjustableColumn=2
        )

    def _onChanged(self, *args):
        self.attr.set(self.getValueFromUI())

    def _onBrowseClicked(self, fileMode: int, title: str, *args):
        res = cmds.fileDialog2(fileMode=fileMode, caption=title)
        if res and self.ctrl and cmds.control(self.ctrl, exists=True):
            self.setValueToUI(res[0])
            self.attr.set(res[0])

    def getValueFromUI(self) -> str:
        if self.ctrl and cmds.control(self.ctrl, exists=True):
            return cmds.textFieldButtonGrp(self.ctrl, query=True, text=True)
        return str(self.attr.get() or "")

    def setValueToUI(self, value: Any):
        if self.ctrl and cmds.control(self.ctrl, exists=True):
            cmds.textFieldButtonGrp(self.ctrl, edit=True, text=str(value or ""))


class ListBoxWidget(MayaWidget):
    """Widget for string list selection with scene selection context menu."""

    def __init__(self, attr: Attribute, module: Module):
        super().__init__(attr, module)
        self.ctrl: Optional[str] = None

    def buildUI(self):
        val = self.attr.get()
        items = [str(i) for i in (val if isinstance(val, list) else self.attr.data().get("items", []))]
        cmds.text(label=self.attr.name(), align="left")
        self.ctrl = cmds.textScrollList(
            numberOfRows=min(max(len(items), 3), 12),
            allowMultiSelection=True,
            append=items
        )
        cmds.textScrollList(self.ctrl, edit=True, selectCommand=partial(self._onSelectionChanged))
        if items:
            cmds.textScrollList(self.ctrl, edit=True, selectIndexedItem=1)

        menu = cmds.popupMenu(parent=self.ctrl, button=3)
        cmds.menuItem(label="Get from Selection", parent=menu, command=partial(self._getSelection, False))
        cmds.menuItem(label="Add from Selection", parent=menu, command=partial(self._getSelection, True))
        cmds.menuItem(divider=True, parent=menu)
        cmds.menuItem(label="Select in Scene", parent=menu, command=partial(self._selectInScene))
        cmds.menuItem(label="Remove Selected", parent=menu, command=partial(self._removeSelected))
        cmds.menuItem(divider=True, parent=menu)
        cmds.menuItem(label="Clear", parent=menu, command=partial(self._clear))

    def _onSelectionChanged(self, *args):
        if self.ctrl and cmds.control(self.ctrl, exists=True):
            sel = cmds.textScrollList(self.ctrl, query=True, selectIndexedItem=True)
            if sel:
                self.attr.set(sel[0] - 1, key="current")

    def _getSelection(self, add: bool, *args):
        if not self.ctrl or not cmds.control(self.ctrl, exists=True):
            return
        sel = cmds.ls(selection=True) or []
        current = cmds.textScrollList(self.ctrl, query=True, allItems=True) or []
        items = (current + [s for s in sel if s not in current]) if add else sel
        self.setValueToUI(items)
        self.attr.set(items)

    def _selectInScene(self, *args):
        if not self.ctrl or not cmds.control(self.ctrl, exists=True):
            return
        selItems = cmds.textScrollList(self.ctrl, query=True, selectItem=True) or []
        existing = [item for item in selItems if cmds.objExists(item)]
        if existing:
            cmds.select(existing, replace=True)

    def _removeSelected(self, *args):
        if not self.ctrl or not cmds.control(self.ctrl, exists=True):
            return
        selIdxs = set(cmds.textScrollList(self.ctrl, query=True, selectIndexedItem=True) or [])
        current = cmds.textScrollList(self.ctrl, query=True, allItems=True) or []
        if selIdxs:
            newItems = [item for i, item in enumerate(current) if (i + 1) not in selIdxs]
            self.setValueToUI(newItems)
            self.attr.set(newItems)

    def _clear(self, *args):
        self.setValueToUI([])
        self.attr.set([])

    def getValueFromUI(self) -> list[str]:
        if self.ctrl and cmds.control(self.ctrl, exists=True):
            return cmds.textScrollList(self.ctrl, query=True, allItems=True) or []
        return self.attr.get() or []

    def setValueToUI(self, value: Any):
        if self.ctrl and cmds.control(self.ctrl, exists=True):
            items = [str(i) for i in (value if isinstance(value, list) else [])]
            cmds.textScrollList(self.ctrl, edit=True, removeAll=True, numberOfRows=min(max(len(items), 3), 12))
            if items:
                cmds.textScrollList(self.ctrl, edit=True, append=items, selectIndexedItem=1)


class TextWidget(MayaWidget):
    """Widget for multiline plain text."""

    def __init__(self, attr: Attribute, module: Module):
        super().__init__(attr, module)
        self.ctrl: Optional[str] = None

    def buildUI(self):
        cmds.text(label=self.attr.name(), align="left")
        self.ctrl = cmds.scrollField(text=str(self.attr.get() or ""), height=self.attr.data().get("height", 80))
        cmds.scrollField(self.ctrl, edit=True, changeCommand=partial(self._onChanged))

    def _onChanged(self, *args):
        self.attr.set(self.getValueFromUI())

    def getValueFromUI(self) -> str:
        if self.ctrl and cmds.control(self.ctrl, exists=True):
            return cmds.scrollField(self.ctrl, query=True, text=True)
        return str(self.attr.get() or "")

    def setValueToUI(self, value: Any):
        if self.ctrl and cmds.control(self.ctrl, exists=True):
            cmds.scrollField(self.ctrl, edit=True, text=str(value or ""))


class LabelWidget(MayaWidget):
    """Widget for descriptive text labels."""

    def buildUI(self):
        text = self.attr.get()
        self.ctrl = cmds.text(label=str(text))


class JsonWidget(MayaWidget):
    """Widget for editable/formatted JSON dictionaries."""

    def __init__(self, attr: Attribute, module: Module):
        super().__init__(attr, module)
        self.ctrl: Optional[str] = None

    def buildUI(self):
        cmds.text(label=self.attr.name(), align="left")
        val = self.attr.get()
        self.ctrl = cmds.scrollField(
            text=json.dumps(val, indent=2) if val is not None else "",
            height=100,
            editable=not self.attr.data().get("readonly", False)
        )
        cmds.scrollField(self.ctrl, edit=True, changeCommand=partial(self._onChanged))

    def _onChanged(self, *args):
        self.attr.set(self.getValueFromUI())

    def getValueFromUI(self) -> Any:
        if self.ctrl and cmds.control(self.ctrl, exists=True):
            try:
                return json.loads(cmds.scrollField(self.ctrl, query=True, text=True))
            except Exception:
                pass
        return self.attr.get()

    def setValueToUI(self, value: Any):
        if self.ctrl and cmds.control(self.ctrl, exists=True):
            cmds.scrollField(self.ctrl, edit=True, text=json.dumps(value, indent=2) if value is not None else "")


class CurveWidget(MayaWidget):
    """Widget for curves and ramps using Maya gradientControlNoAttr."""

    def __init__(self, attr: Attribute, module: Module):
        super().__init__(attr, module)
        self.ctrl: Optional[str] = None

    def buildUI(self):
        val = self.attr.get()
        pts = val if val is not None else self.attr.data().get("cvs", [[0.0, 1.0], [1.0, 0.0]])
        rampStr = _pointsToRampString(pts, interp=2)

        cmds.text(label=self.attr.name(), align="left")
        self.ctrl = cmds.gradientControlNoAttr(h=90, asString=rampStr)
        cmds.gradientControlNoAttr(self.ctrl, edit=True, asString=rampStr, changeCommand=partial(self._onChanged))

    def _onChanged(self, *args):
        self.attr.set(self.getValueFromUI())

    def getValueFromUI(self) -> Any:
        if self.ctrl and cmds.control(self.ctrl, exists=True):
            rampStr = cmds.gradientControlNoAttr(self.ctrl, query=True, asString=True)
            pts = _rampStringToPoints(rampStr)
            return {"cvs": _calculateBezierCVs(pts), "default": "cvs"}
        return self.attr.get()

    def setValueToUI(self, value: Any):
        if self.ctrl and cmds.control(self.ctrl, exists=True):
            rampStr = _pointsToRampString(value, interp=2)
            cmds.gradientControlNoAttr(self.ctrl, edit=True, asString=rampStr)


class TableWidget(MayaWidget):
    """Widget for editable 2D tabular data grids."""

    def __init__(self, attr: Attribute, module: Module):
        super().__init__(attr, module)
        self.rowsCol: Optional[str] = None
        self.rowCtrls: list[tuple[str, list[str]]] = []
        self.headers: list[str] = []

    def buildUI(self):
        self.headers = [str(h) for h in self.attr.data().get("header", ["Name", "Value"])]
        items = [list(row) for row in self.attr.get()] if isinstance(self.attr.get(), (list, tuple)) else [["", ""]]
        numCols = max(len(self.headers), 1)
        colWidth = max(int(220 / numCols), 60)

        cmds.text(label=self.attr.name(), align="left")
        mainCol = cmds.columnLayout(adjustableColumn=True, rowSpacing=2)

        cmds.rowLayout(
            numberOfColumns=numCols + 1,
            columnWidth=[(i + 1, colWidth) for i in range(numCols)] + [(numCols + 1, 24)],
            columnAttach=[(i + 1, "both", 1) for i in range(numCols + 1)],
            columnAlign=[(i + 1, "center") for i in range(numCols)] + [(numCols + 1, "center")]
        )
        for h in self.headers:
            cmds.text(label=h, font="boldLabelFont", align="center")
        cmds.text(label="", width=24)
        cmds.setParent(mainCol)

        self.rowsCol = cmds.columnLayout(adjustableColumn=True, rowSpacing=2)
        self._rebuildRows(items)
        cmds.setParent(mainCol)

        cmds.rowLayout(numberOfColumns=2, columnWidth2=(80, 80), columnAttach2=("both", "both"))
        cmds.button(label="+ Add Row", height=20, command=partial(self._addRow))
        cmds.button(label="Clear", height=20, command=partial(self._clearRows))
        cmds.setParent(mainCol)
        cmds.setParent("..")

    def _rebuildRows(self, items: list[list]):
        numCols = max(len(self.headers), 1)
        colWidth = max(int(220 / numCols), 60)
        for ch in cmds.layout(self.rowsCol, query=True, childArray=True) or []:
            cmds.deleteUI(ch)

        cmds.setParent(self.rowsCol)
        self.rowCtrls = []
        for rowData in items:
            rowFields = []
            rowLayout = cmds.rowLayout(
                numberOfColumns=numCols + 1,
                columnWidth=[(i + 1, colWidth) for i in range(numCols)] + [(numCols + 1, 24)],
                columnAttach=[(i + 1, "both", 1) for i in range(numCols + 1)]
            )
            for colIdx in range(numCols):
                cellVal = str(rowData[colIdx]) if colIdx < len(rowData) else ""
                rowFields.append(cmds.textField(text=cellVal, changeCommand=partial(self._onCellChanged)))
            cmds.button(label="✕", width=24, command=partial(self._removeRow, rowLayout))
            cmds.setParent(self.rowsCol)
            self.rowCtrls.append((rowLayout, rowFields))

    def _onCellChanged(self, *args):
        self.attr.set(self.getValueFromUI())

    def _addRow(self, *args):
        items = self.getValueFromUI()
        items.append(["" for _ in range(max(len(self.headers), 1))])
        self._rebuildRows(items)
        self.attr.set(items)

    def _removeRow(self, targetLayout: str, *args):
        items = []
        for rowLayout, rowFields in self.rowCtrls:
            if rowLayout != targetLayout and cmds.control(rowLayout, exists=True):
                items.append([cmds.textField(tf, query=True, text=True) for tf in rowFields if cmds.control(tf, exists=True)])
        self._rebuildRows(items)
        self.attr.set(items)

    def _clearRows(self, *args):
        self._rebuildRows([])
        self.attr.set([])

    def getValueFromUI(self) -> list[list[str]]:
        items = []
        for rowLayout, rowFields in self.rowCtrls:
            if cmds.control(rowLayout, exists=True):
                items.append([cmds.textField(tf, query=True, text=True) for tf in rowFields if cmds.control(tf, exists=True)])
        return items

    def setValueToUI(self, value: Any):
        items = [list(row) for row in value] if isinstance(value, (list, tuple)) else []
        self._rebuildRows(items)


class FallbackWidget(MayaWidget):
    """Fallback text field for unknown templates."""

    def __init__(self, attr: Attribute, module: Module):
        super().__init__(attr, module)
        self.ctrl: Optional[str] = None

    def buildUI(self):
        self.ctrl = cmds.textFieldGrp(
            label=self.attr.name(),
            text=str(self.attr.get() or ""),
            changeCommand=partial(self._onChanged),
            columnWidth2=(self.ATTR_NAME_WIDTH, 200),
            columnAlign2=("right", "left"),
            adjustableColumn=2
        )

    def _onChanged(self, val: str, *args):
        self.attr.set(val)

    def getValueFromUI(self) -> str:
        if self.ctrl and cmds.control(self.ctrl, exists=True):
            return cmds.textFieldGrp(self.ctrl, query=True, text=True)
        return str(self.attr.get() or "")

    def setValueToUI(self, value: Any):
        if self.ctrl and cmds.control(self.ctrl, exists=True):
            cmds.textFieldGrp(self.ctrl, edit=True, text=str(value or ""))


WIDGET_REGISTRY: dict[str, type[MayaWidget]] = {
    "lineEditAndButton": LineEditAndButtonWidget,
    "button": ButtonWidget,
    "checkBox": CheckBoxWidget,
    "comboBox": ComboBoxWidget,
    "radioButton": RadioButtonWidget,
    "vector": VectorWidget,
    "fileSelector": FileSelectorWidget,
    "listBox": ListBoxWidget,
    "text": TextWidget,
    "label": LabelWidget,
    "json": JsonWidget,
    "curve": CurveWidget,
    "table": TableWidget,
}


# ===========================================================================
# Module Window
# ===========================================================================

class ModuleWindow:
    """Renders a Rig Builder module window and synchronizes its widgets with module attributes."""

    def __init__(self, module: Union[str, Module]):
        if isinstance(module, str):
            module = Module.loadModule(module)

        self.module = module
        self.currentModule: Module = module
        self.widgets: dict[str, MayaWidget] = {}
        self.hierarchyItems: list[tuple[str, Module]] = []
        self.hierarchyList: Optional[str] = None
        self.attrLayout: Optional[str] = None

    def show(self):
        """Build and display the native Maya window."""
        hasChildren = bool(self.module.children())
        window = cmds.window(
            title=f"Rig Builder — {self.module.name()}",
            widthHeight=(600 if hasChildren else 400, 480),
            sizeable=True,
            tlb=True
        )
        form = cmds.formLayout()

        attrScroll = cmds.scrollLayout(childResizable=True)
        self.attrLayout = cmds.columnLayout(adjustableColumn=True, rowSpacing=4)
        cmds.setParent(form)

        runBtn = cmds.button(label="Run", height=34, bgc=(0.25, 0.45, 0.25), command=partial(self.run))

        if hasChildren:
            self.hierarchyList = cmds.textScrollList(
                width=180,
                allowMultiSelection=False,
                selectCommand=partial(self._onModuleSelected)
            )
            self.hierarchyItems = []
            self._collectHierarchy(self.module, depth=0)
            for label, _ in self.hierarchyItems:
                cmds.textScrollList(self.hierarchyList, edit=True, append=label)

            cmds.formLayout(
                form, edit=True,
                attachForm=[
                    (self.hierarchyList, "top", 4), (self.hierarchyList, "left", 4),
                    (attrScroll, "top", 4), (attrScroll, "right", 4),
                    (runBtn, "left", 4), (runBtn, "right", 4), (runBtn, "bottom", 4)
                ],
                attachControl=[
                    (self.hierarchyList, "bottom", 4, runBtn),
                    (attrScroll, "left", 4, self.hierarchyList),
                    (attrScroll, "bottom", 4, runBtn)
                ],
                attachNone=[(runBtn, "top")]
            )
            cmds.textScrollList(self.hierarchyList, edit=True, selectIndexedItem=1)
        else:
            self.hierarchyList = None
            self.hierarchyItems = [(self.module.name(), self.module)]

            cmds.formLayout(
                form, edit=True,
                attachForm=[
                    (attrScroll, "top", 4), (attrScroll, "left", 4), (attrScroll, "right", 4),
                    (runBtn, "left", 4), (runBtn, "right", 4), (runBtn, "bottom", 4)
                ],
                attachControl=[(attrScroll, "bottom", 4, runBtn)],
                attachNone=[(runBtn, "top")]
            )

        self._renderModuleAttributes(self.module)
        cmds.showWindow(window)

    def _collectHierarchy(self, m: Module, depth: int):
        indent = " " * depth * 4
        self.hierarchyItems.append((f"{indent}{m.name()}", m))
        for ch in m.children():
            self._collectHierarchy(ch, depth + 1)

    def _onModuleSelected(self, *args):
        if not self.hierarchyList or not cmds.control(self.hierarchyList, exists=True):
            return
        selIdxs = cmds.textScrollList(self.hierarchyList, query=True, selectIndexedItem=True)
        if not selIdxs:
            return
        idx = selIdxs[0] - 1
        if 0 <= idx < len(self.hierarchyItems):
            self._syncAllFromUI()
            targetModule = self.hierarchyItems[idx][1]
            self._renderModuleAttributes(targetModule)

    def _renderModuleAttributes(self, module: Module):
        self.currentModule = module
        if cmds.layout(self.attrLayout, exists=True):
            for ch in cmds.layout(self.attrLayout, query=True, childArray=True) or []:
                cmds.deleteUI(ch)
            cmds.setParent(self.attrLayout)

        # 1. Group attributes by category
        categories: dict[str, list[Attribute]] = {}
        for attr in module.attributes():
            categories.setdefault(attr.category() or "General", []).append(attr)

        self.widgets = {}
        for catName, attrs in categories.items():
            cmds.frameLayout(label=catName, collapsable=False, collapse=False)
            cmds.columnLayout(adjustableColumn=True)
            for attr in attrs:
                self._renderAttribute(attr, module)
            cmds.setParent(self.attrLayout)

        # 2. Doc
        doc = (module.doc() or "").strip()
        if doc:
            cmds.frameLayout(label="Doc", collapsable=True, collapse=True)
            cmds.scrollField(text=doc, editable=False, wordWrap=True, height=120)

    def _renderAttribute(self, attr: Attribute, module: Module):
        currentParent = cmds.setParent(query=True)
        cls = WIDGET_REGISTRY.get(attr.template(), FallbackWidget)
        widget = cls(attr, module)
        widget.parentUI = self
        widget.buildUI()
        cmds.setParent(currentParent)
        self.widgets[attr.name()] = widget

    def updateAttributeFromUI(self, attr: Attribute):
        """Query the registered Maya control for a single attribute and write its value back."""
        widget = self.widgets.get(attr.name())
        if widget:
            widget.syncToAttribute()

    def _updateUIFromAttributes(self):
        """Update Maya UI widgets from current module attribute values."""
        if not self.currentModule:
            return
        for attr in self.currentModule.attributes():
            widget = self.widgets.get(attr.name())
            if widget:
                widget.setValueToUI(attr.get())

    def _syncAllFromUI(self):
        """Query all registered Maya controls and write their values back to module attributes."""
        if not self.currentModule:
            return
        for attr in self.currentModule.attributes():
            self.updateAttributeFromUI(attr)

    @_with_undo
    def run(self, *args):
        """Execute the currently selected module with undo support."""
        self._syncAllFromUI()
        target = self.currentModule or self.module
        res = target.run()
        self._updateUIFromAttributes()
        cmds.inViewMessage(statusMessage=f"<hl>{target.name()}</hl> finished", pos="topCenter", fade=True)
        return res

    def sync(self):
        """Sync current module parameters with disk definition and refresh UI."""
        target = self.currentModule or self.module
        target.sync()
        self.show()


class MainWindow:
    """Native Maya UI to browse workspaces, filter modules, and launch module UIs."""

    def __init__(self, workspace: Optional[Union[str, Workspace]] = None):
        self.currentWorkspace: Optional[Workspace] = (
            Workspace.load(workspace) if isinstance(workspace, str) else workspace
        )
        self.modules: list[tuple[str, Union[Module, str]]] = []
        self.filteredModules: list[tuple[str, Union[Module, str]]] = []

    def show(self):
        """Build and display the Maya Rig Builder window."""
        window = cmds.window(
            title="Rig Builder",
            widthHeight=(300, 400),
            sizeable=True,
            mxb=False,
            mnb=False,
            tlb=True
        )
        form = cmds.formLayout()

        topCol = cmds.columnLayout(adjustableColumn=True, rowSpacing=4)
        cmds.rowLayout(numberOfColumns=2, columnWidth2=(80, 240), adjustableColumn=2)
        cmds.text(label="Workspace:", align="right", width=80)
        self.wsMenu = cmds.optionMenu(changeCommand=partial(self._onWorkspaceChanged))
        workspaces = Workspace.list()
        for w in workspaces:
            cmds.menuItem(label=w)
        cmds.setParent(topCol)

        cmds.rowLayout(numberOfColumns=2, columnWidth2=(80, 240), adjustableColumn=2)
        cmds.text(label="Filter:", align="right", width=80)
        self.filterField = cmds.textField(
            placeholderText="Search modules...",
            changeCommand=partial(self._refreshModuleList),
            textChangedCommand=partial(self._refreshModuleList)
        )
        cmds.setParent(topCol)
        cmds.separator(height=6, style="in")
        cmds.setParent(form)

        self.moduleListCtrl = cmds.textScrollList(
            numberOfRows=15,
            allowMultiSelection=False,
            doubleClickCommand=partial(self._openSelectedModule)
        )
        cmds.setParent(form)

        menu = cmds.popupMenu(parent=self.moduleListCtrl, button=3)
        cmds.menuItem(label="Open", parent=menu, command=partial(self._openSelectedModule))
        cmds.menuItem(label="Copy Code", parent=menu, command=partial(self._copySelectedModuleCode))

        cmds.formLayout(
            form, edit=True,
            attachForm=[
                (topCol, "top", 6), (topCol, "left", 6), (topCol, "right", 6),
                (self.moduleListCtrl, "left", 6), (self.moduleListCtrl, "right", 6), (self.moduleListCtrl, "bottom", 6)
            ],
            attachControl=[(self.moduleListCtrl, "top", 4, topCol)]
        )

        targetWs = self.currentWorkspace.name if self.currentWorkspace else ""
        if not targetWs or targetWs not in workspaces:
            currentWsName = settings.workspacePath
            targetWs = os.path.basename(currentWsName) if currentWsName else (workspaces[0] if workspaces else "default")

        if targetWs in workspaces:
            cmds.optionMenu(self.wsMenu, edit=True, value=targetWs)

        selectedWs = cmds.optionMenu(self.wsMenu, query=True, value=True) if cmds.optionMenu(self.wsMenu, exists=True) else targetWs
        self._onWorkspaceChanged(selectedWs or targetWs)
        cmds.showWindow(window)

    def _onWorkspaceChanged(self, wsName: str, *args):
        try:
            self.currentWorkspace = Workspace.load(wsName)
            self.currentWorkspace.activate()
        except Exception as e:
            print(f"Error loading workspace '{wsName}': {e}")
            return

        self._loadModules()
        self._refreshModuleList()

    def _loadModules(self):
        self.modules = []
        if not self.currentWorkspace:
            return

        modulesPath = self.currentWorkspace.settings.modulesPath
        if not os.path.isdir(modulesPath):
            return

        # Build folder hierarchy tree
        tree: dict = {}
        for f in sorted(Module.listModules(modulesPath)):
            relPath = os.path.relpath(f, modulesPath).replace("\\", "/")
            parts = relPath.split("/")
            curr = tree
            for folder in parts[:-1]:
                curr = curr.setdefault(folder, {})
            curr[parts[-1]] = f

        def _traverse(node: dict, depth: int):
            for key, val in sorted(node.items(), key=lambda x: (not isinstance(x[1], dict), x[0])):
                indent = " " * depth * 4
                if isinstance(val, dict):  # Folder header
                    self.modules.append((f"{indent}{key}", None))
                    _traverse(val, depth + 1)
                else:  # Module file
                    modName = os.path.splitext(key)[0]
                    self.modules.append((f"{indent}{modName}", val))

        _traverse(tree, 0)

    def _refreshModuleList(self, *args):
        query = (cmds.textField(self.filterField, query=True, text=True) or "").lower()
        cmds.textScrollList(self.moduleListCtrl, edit=True, removeAll=True)
        self.filteredModules = []

        lineIdx = 1
        for name, spec in self.modules:
            if not query or query in name.lower():
                cmds.textScrollList(self.moduleListCtrl, edit=True, append=name)
                if spec is None:  # Folder header
                    cmds.textScrollList(self.moduleListCtrl, edit=True, lineFont=(lineIdx, "boldLabelFont"))
                self.filteredModules.append((name, spec))
                lineIdx += 1

        if self.filteredModules:
            cmds.textScrollList(self.moduleListCtrl, edit=True, selectIndexedItem=1)

    def _openSelectedModule(self, *args):
        selIdx = cmds.textScrollList(self.moduleListCtrl, query=True, selectIndexedItem=True)
        if selIdx and selIdx[0] <= len(self.filteredModules):
            spec = self.filteredModules[selIdx[0] - 1][1]
            if spec:
                ModuleWindow(spec).show()

    def _copySelectedModuleCode(self, *args):
        selIdx = cmds.textScrollList(self.moduleListCtrl, query=True, selectIndexedItem=True)
        if selIdx and selIdx[0] <= len(self.filteredModules):
            spec = self.filteredModules[selIdx[0] - 1][1]
            if spec:
                code = f"ModuleWindow({spec!r}).show()"
                _copyToClipboard(code)
                cmds.inViewMessage(statusMessage=f"<hl>Copied:</hl> {code}", pos="topCenter", fade=True)


def _copyToClipboard(text: str):
    """Copy text string to system clipboard."""
    try:
        from PySide2.QtWidgets import QApplication
        QApplication.clipboard().setText(text)
        return
    except ImportError:
        pass
    try:
        from PySide6.QtWidgets import QApplication
        QApplication.clipboard().setText(text)
        return
    except ImportError:
        pass
    try:
        import tkinter as tk
        r = tk.Tk()
        r.withdraw()
        r.clipboard_clear()
        r.clipboard_append(text)
        r.update()
        r.destroy()
    except Exception:
        pass


mainWindow = MainWindow()
