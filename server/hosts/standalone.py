"""Standalone host server — runs module code inline, no main-thread dispatch needed.
Used for testing and for running rigBuilder without any host.
"""

from . import HostServer


class StandaloneServer(HostServer):
    """Standalone server — executes module code directly in the socket thread."""
