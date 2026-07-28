import sys
import os
import threading
import asyncio

# Isolate sys.path so 'import mcp' resolves to PyPI 'mcp' library in site-packages
origPath = sys.path[:]
sys.path = [p for p in sys.path if p not in ('', os.getcwd(), os.path.dirname(os.path.abspath(__file__)))]
try:
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client
finally:
    sys.path = origPath

from ..core.logger import logger


class MCPClientManager:
    """Manages background mcp_server.py subprocess via stdio MCP ClientSession."""
    _loop = None
    _thread = None
    _session = None
    _readyEvent = None

    @classmethod
    def _startWorker(cls):
        """Starts background thread and asyncio loop if not already running."""
        if cls._thread is not None and cls._thread.is_alive():
            return

        cls._loop = asyncio.new_event_loop()
        cls._readyEvent = threading.Event()
        cls._thread = threading.Thread(target=cls._runLoop, daemon=True)
        cls._thread.start()

        if not cls._readyEvent.wait(timeout=10.0):
            logger.error("Timed out waiting for MCP stdio client initialization.")

    @classmethod
    def _runLoop(cls):
        asyncio.set_event_loop(cls._loop)
        cls._loop.run_until_complete(cls._workerCoro())

    @classmethod
    async def _workerCoro(cls):
        mcpScriptPath = os.path.abspath(
            os.path.join(os.path.dirname(__file__), "mcp_server.py")
        )

        serverParams = StdioServerParameters(
            command=sys.executable,
            args=[mcpScriptPath],
            env=dict(os.environ, PYTHONUNBUFFERED="1")
        )

        try:
            async with stdio_client(serverParams) as (read, write):
                async with ClientSession(read, write) as session:
                    await session.initialize()
                    cls._session = session
                    cls._readyEvent.set()
                    logger.info("MCP Client connected to mcp_server.py subprocess via stdio.")
                    while True:
                        await asyncio.sleep(3600)
        except Exception as e:
            logger.error(f"MCP stdio client worker error: {e}")
            cls._session = None
            cls._readyEvent.set()

    @classmethod
    def getOllamaTools(cls) -> list:
        """Retrieves registered FastMCP tool functions with full Python signatures for Ollama."""
        try:
            from .mcp_server import mcp as _mcp_server
            comps = getattr(_mcp_server._local_provider, '_components', {})
            return [comp.fn for key, comp in comps.items() if key.startswith('tool:') and hasattr(comp, 'fn')]
        except Exception as e:
            logger.error(f"Error loading FastMCP tool signatures: {e}")
            return []

    @classmethod
    def executeTool(cls, funcName: str, args: dict) -> str:
        """Executes a tool call on the MCP subprocess over stdio."""
        cls._startWorker()
        if not cls._session:
            return f"MCP server subprocess is offline. Cannot execute {funcName}."

        try:
            coro = cls._session.call_tool(funcName, arguments=args)
            future = asyncio.run_coroutine_threadsafe(coro, cls._loop)
            result = future.result(timeout=15.0)

            outputParts = []
            for contentBlock in result.content:
                if getattr(contentBlock, 'type', None) == 'text':
                    outputParts.append(contentBlock.text)
                elif hasattr(contentBlock, 'text'):
                    outputParts.append(str(contentBlock.text))

            return "\n".join(outputParts) if outputParts else "Success"
        except Exception as e:
            logger.error(f"Error executing tool {funcName} on MCP subprocess: {e}")
            return f"Error executing {funcName}: {e}"
