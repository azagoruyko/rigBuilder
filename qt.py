"""Qt compatibility shim for PySide2 and PySide6."""

qtBinding = None
_qtWrapInstance = None

try:
    from PySide2.QtCore import *  # noqa: F401,F403
    from PySide2.QtGui import *  # noqa: F401,F403
    from PySide2.QtWidgets import *  # noqa: F401,F403

    import PySide2.QtCore as QtCore
    import PySide2.QtGui as QtGui
    import PySide2.QtWidgets as QtWidgets
    from shiboken2 import wrapInstance as _qtWrapInstance

    qtBinding = "PySide2"
except ImportError:
    from PySide6.QtCore import *  # noqa: F401,F403
    from PySide6.QtGui import *  # noqa: F401,F403
    from PySide6.QtWidgets import *  # noqa: F401,F403

    import PySide6.QtCore as QtCore
    import PySide6.QtGui as QtGui
    import PySide6.QtWidgets as QtWidgets
    from shiboken6 import wrapInstance as _qtWrapInstance

    qtBinding = "PySide6"


def wrapInstance(ptr, baseType):
    """Wrap a C++ Qt pointer into a Python Qt object."""
    if _qtWrapInstance is None:
        raise ImportError("No shiboken wrapInstance is available.")
    return _qtWrapInstance(int(ptr), baseType)


def execFunc(obj):
    """Execute object using exec/exec_ compatibility fallback."""
    execFn = getattr(obj, "exec", None) or getattr(obj, "exec_", None)
    if execFn is None:
        raise AttributeError("Object has no exec/exec_ method.")
    return execFn()
