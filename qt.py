"""Qt compatibility shim for PySide2 and PySide6."""

qtBinding = None
_qtWrapInstance = None

try:
    from PySide2.QtCore import *
    from PySide2.QtGui import *
    from PySide2.QtWidgets import *
    from shiboken2 import wrapInstance as _qtWrapInstance
    qtBinding = "PySide2"

except ImportError:
    from PySide6.QtCore import *
    from PySide6.QtGui import *
    from PySide6.QtWidgets import *
    from shiboken6 import wrapInstance as _qtWrapInstance
    qtBinding = "PySide6"


def wrapInstance(ptr, baseType):
    """Wrap a C++ Qt pointer into a Python Qt object."""
    if _qtWrapInstance is None:
        raise ImportError("No shiboken wrapInstance is available.")
    return _qtWrapInstance(int(ptr), baseType)


def execFunc(obj, *args, **kwargs):
    """Execute object using exec/exec_ compatibility fallback."""
    execFn = getattr(obj, "exec", None) or getattr(obj, "exec_", None)
    if execFn is None:
        raise AttributeError("Object has no exec/exec_ method.")
    return execFn(*args, **kwargs)
