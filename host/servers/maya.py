"""Maya host server.

Run once inside Maya (e.g. from userSetup.py or Script Editor):

    from rigBuilder.host.servers.maya import MayaServer
    MayaServer(51605).start()
"""
from __future__ import annotations

import os
import maya.utils
import maya.cmds as cmds
import maya.OpenMaya as om

from rigBuilder.host.servers import HostServer


class MayaServer(HostServer):
    """Dispatches execution to Maya's main thread via maya.utils.executeDeferred."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.title = "Maya"

    def executeOnMainThread(self, taskFunction):
        def f():
            cmds.undoInfo(openChunk=True)
            try:
                taskFunction()
            finally:
                cmds.undoInfo(closeChunk=True)
        
        maya.utils.executeDeferred(f)

    def ping(self) -> dict:
        def task():
            scene_path = om.MFileIO.currentFile() or "Untitled"
            scene = os.path.basename(scene_path)
            self.title = f"Maya {om.MGlobal.mayaVersion()} — {scene}"

        maya.utils.executeDeferred(task)
        return {
            "ok": True,
            "host": "maya",
            "name": self.title,
        }

# API functions mostly used by the client's widgets

def select(objects: list[str]):
    """Select objects."""
    cmds.select([o for o in objects if cmds.objExists(o)], replace=True)

def getSelected() -> list[str]:
    """Get selected objects."""
    return cmds.ls(sl=True)