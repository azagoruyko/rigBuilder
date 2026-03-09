"""Default DCC implementations when no DCC is active (testing, standalone tools)."""

from ..core import APIRegistry


def register():
    """Override stubs with no-op implementations."""
    APIRegistry.override("getSelectedNodes", lambda: [])
    APIRegistry.override("selectNodes", lambda nodes: None)
    APIRegistry.override("getDccName", lambda: "standalone")
    APIRegistry.override("getParentWindow", lambda: None)
    APIRegistry.override("currentSceneFile", lambda: None)
    APIRegistry.override("openUndoChunk", lambda: None)
    APIRegistry.override("closeUndoChunk", lambda: None)
