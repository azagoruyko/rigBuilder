"""Houdini host server.

Run once inside Houdini (e.g. from a startup script or shelf tool):

    from rigBuilder.server.hosts.houdini import HoudiniServer
    HoudiniServer(rep_port=7206, pub_port=7207).start()
"""

import hou

from rigBuilder.server.hosts import HostServer


class HoudiniServer(HostServer):
    """Dispatches execution to Houdini's main thread via hou.ui.postEventCallback."""

    def executeOnMainThread(self, taskFunction) -> None:
        def task():
            try:
                taskFunction()
            finally:
                hou.ui.removeEventLoopCallback(task)

        hou.ui.addEventLoopCallback(task)


# API functions mostly used by the client's widgets

def select(names: list[str]) -> None:
    """Select nodes by name."""
    for name in names:
        node = hou.node(name)
        if node:
            node.setSelected(True)

def getSelected() -> list[str]:
    """Get selected nodes."""
    return [node.path() for node in hou.selectedNodes()]
