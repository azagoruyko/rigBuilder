"""Maya host server.

Run once inside Maya (e.g. from userSetup.py or Script Editor):

    from rigBuilder.server.hosts.maya import MayaServer
    MayaServer(rep_port=7202, pub_port=7203).start()
"""

import maya.utils

from rigBuilder.server.hosts import HostServer


class MayaServer(HostServer):
    """Dispatches execution to Maya's main thread via maya.utils.executeDeferred."""

    def executeOnMainThread(self, taskFunction):
        maya.utils.executeDeferred(taskFunction)