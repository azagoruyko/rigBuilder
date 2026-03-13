"""DCC abstraction layer. Provides selection and other DCC operations via APIRegistry."""

import sys


def detectDcc():
    """Detect current DCC from already-loaded modules (avoids importing maya.cmds in standalone)."""
    if "maya.cmds" in sys.modules:
        return "maya"
    return "standalone"


DCC = detectDcc()


def register():
    """Register DCC-specific functions into APIRegistry. Call once at startup."""
    if DCC == "maya":
        from . import maya
        maya.register()
    else:
        from . import standalone
        standalone.register()
