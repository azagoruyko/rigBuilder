"""DCC abstraction layer. Provides selection and other DCC operations via APIRegistry."""

import os


def detectDcc():
    """Detect current DCC. RIG_BUILDER_DCC overrides; otherwise auto-detect via imports."""
    if os.getenv("RIG_BUILDER_DCC"):
        return os.getenv("RIG_BUILDER_DCC")
    try:
        import maya.cmds  # noqa: F401
        return "maya"
    except ImportError:
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
