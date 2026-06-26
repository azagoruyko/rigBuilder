"""Maya host server.

Run once inside Maya (e.g. from userSetup.py or Script Editor):

    from rigBuilder.host.servers.maya import MayaServer
    MayaServer(51605).start()
"""

import maya.utils
import maya.cmds as cmds

from rigBuilder.host.servers import HostServer


class MayaServer(HostServer):
    """Dispatches execution to Maya's main thread via maya.utils.executeDeferred."""

    def executeOnMainThread(self, taskFunction):
        maya.utils.executeDeferred(taskFunction)

    def ping(self) -> dict:
        return {
            "ok": True,
            "host": "maya",
            "name": f"Maya {cmds.about(version=True)}"
        }

# API functions mostly used by the client's widgets

def select(objects: list[str]):
    """Select objects."""
    cmds.select([o for o in objects if cmds.objExists(o)], replace=True)

def getSelected() -> list[str]:
    """Get selected objects."""
    return cmds.ls(sl=True)