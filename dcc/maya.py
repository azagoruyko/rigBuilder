"""Maya-specific DCC implementations."""

import maya.cmds as cmds
import maya.OpenMaya as om
import maya.OpenMayaUI as omui

from ..core import APIRegistry
from ..qt import wrapInstance, QMainWindow


def getParentWindow():
    """Get Maya main window for PySide parent."""
    try:
        return wrapInstance(int(omui.MQtUtil.mainWindow()), QMainWindow)
    except Exception:
        return None


def register():
    """Register Maya functions into APIRegistry."""
    APIRegistry.override("getSelectedNodes", lambda: [n for n in cmds.ls(sl=True)])
    APIRegistry.override("selectNodes", lambda nodes: cmds.select(nodes))
    APIRegistry.override("getDccName", lambda: "maya")
    APIRegistry.override("getParentWindow", getParentWindow)
    APIRegistry.override("currentSceneFile", lambda: om.MFileIO.currentFile())
    APIRegistry.override("openUndoChunk", lambda: cmds.undoInfo(ock=True))
    APIRegistry.override("closeUndoChunk", lambda: cmds.undoInfo(cck=True))
