"""Blender host server.

Run once inside Blender (e.g. from a startup script):

    from rigBuilder.server.hosts.blender import BlenderServer
    BlenderServer(rep_port=7204, pub_port=7205).start()
"""

import bpy

from rigBuilder.server.hosts import HostServer


class BlenderServer(HostServer):
    """Dispatches execution to Blender's main thread via bpy.app.timers."""

    def executeOnMainThread(self, taskFunction) -> None:
        bpy.app.timers.register(taskFunction, first_interval=0)
