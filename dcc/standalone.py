"""Default DCC implementations when no DCC is active (testing, standalone tools)."""

from ..core import APIRegistry


def register():
    """Register standalone functions into APIRegistry."""
    APIRegistry.override("getDccName", lambda: "standalone")
    

