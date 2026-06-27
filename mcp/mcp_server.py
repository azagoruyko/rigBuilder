import json
import sys
import os
from fastmcp import FastMCP

MCP_DIRECTORY = os.path.dirname(os.path.abspath(__file__))
sys.path.append(MCP_DIRECTORY)
from zmq_client import ZmqClient

# Initialize MCP Server
mcp = FastMCP("RigBuilder AI")
client = ZmqClient()

@mcp.resource("docs://rig-builder-reference")
def read_rig_builder_reference() -> str:
    """CRITICAL REFERENCE: Contains the complete Rig Builder architecture, module XML format specifications, 
    JSON schemas for all widget templates (e.g. lineEditAndButton, vector, checkBox), relative path syntax, 
    and API references. 
    
    MUST READ this resource whenever creating, modifying, or debugging Rig Builder modules, 
    attributes, connections, or scripts to ensure correctness.
    """
    
    tech_md_path = os.path.join(os.path.dirname(MCP_DIRECTORY), "docs", "tech.md")
    with open(tech_md_path, "r", encoding="utf-8") as f:
        return f.read()

@mcp.tool()
def get_selected_modules() -> str:
    """Returns the names and paths of the currently selected modules in the UI.
    Useful for contextual edits when the user has something selected.
    """
    res = client.send_request("get_selected_modules")
    names = res.get("names", [])
    paths = res.get("paths", [])
    if not names:
        return "No modules are currently selected."
        
    output = "Selected Modules:\n"
    for name, path in zip(names, paths):
        output += f"- {name} (Path: {path})\n"
    return output

@mcp.tool()
def get_modules() -> str:
    """Returns a list of all instantiated modules currently in the active tree.
    This provides the AI with the structural overview of the module tree (the module paths).
    """
    res = client.send_request("get_modules")
    modules = res.get("modules", [])
    if not modules:
        return "No modules are currently in the tree."
        
    out = "Current Tree Modules:\n"
    for m in modules:
        out += f"- {m}\n"
    return out

@mcp.tool()
def query_module(query: str, k: int = 5) -> str:
    """Semantically search for existing workspace modules using natural language.
    Useful for finding a module if you don't know the exact name (e.g. 'an arm setup', 'IK solver').
    Args:
        query: Natural language query describing what you're looking for.
        k: Maximum number of results to return.
    """
    res = client.send_request("query_module", query=query, k=k)
    results = res.get("results", [])
    results = [r for r in results if r['score'] > 0.5]
    if not results:
        return "No modules found matching the query."
        
    out = f"Search results for '{query}':\n"
    for r in results:
        out += f"- {r['name']} (Path: {r['path']}, Score: {r['score']:.2f})\n"
    return out

@mcp.tool()
def add_module(parent_path: str, name: str, template_path: str = "") -> str:
    """Adds a new module to the current tree in Rig Builder.
    Args:
        parent_path: The path of the parent module (e.g. 'ROOT/spine'). Leave empty for ROOT.
        name: The name for the new module.
        template_path: (Optional) The relative path to an existing module file from the workspace (e.g. 'biped/arm.xml'). If empty, creates an empty module.
    """
    res = client.send_request("add_module", parent_path=parent_path, name=name, template_path=template_path)
    return res.get("message", "Success")

@mcp.tool()
def remove_module(module_path: str) -> str:
    """Removes a module from the active tree.
    Args:
        module_path: The full path to the module to remove (e.g. 'ROOT/spine/arm_L').
    """
    res = client.send_request("remove_module", module_path=module_path)
    return res.get("message", "Success")

@mcp.tool()
def get_module_xml(module_path: str = "") -> str:
    """Returns the full XML representation of a specific module (including its runCode, children, and doc).
    Args:
        module_path: The full path to the module (e.g. 'ROOT/spine_01'). Leave empty for ROOT.
    """
    res = client.send_request("get_module_xml", module_path=module_path)
    return res.get("xml", "")

@mcp.tool()
def set_module_xml(module_path: str, xml_str: str) -> str:
    """Replaces or updates a module using its full XML representation.
    This synchronizes the module structure, attributes, and Python runCode.
    Args:
        module_path: The full path to the module being updated.
        xml_str: The complete XML string of the updated module.
    """
    res = client.send_request("set_module_xml", module_path=module_path, xml=xml_str)
    return res.get("message", "Success")

@mcp.tool()
def read_log() -> str:
    """Read the contents of the log widget from the main window."""
    res = client.send_request("read_log")
    return res.get("log", "")

@mcp.tool()
def get_available_hosts() -> str:
    """Returns a list of available discovered hosts."""
    res = client.send_request("get_available_hosts")
    hosts = res.get("hosts", [])
    if not hosts:
        return "No hosts available."
    return "Available hosts:\n" + "\n".join(f"- {h}" for h in hosts)

@mcp.tool()
def switch_host(host_name: str) -> str:
    """Switches the current active host in the UI.
    Args:
        host_name: The name of the host to switch to.
    """
    res = client.send_request("switch_host", host_name=host_name)
    return res.get("message", "Success")

@mcp.tool()
def execute_module(module_path: str) -> str:
    """Executes a module by its full path in the active tree.
    Args:
        module_path: The full path to the module (e.g. 'ROOT/spine_01').
    """
    res = client.send_request("execute_module", module_path=module_path)
    return res.get("message", "Success")

@mcp.tool()
def read_module_api() -> str:
    """Reads the API functions and objects available to modules at runtime (from APIRegistry)."""
    res = client.send_request("read_module_api")
    api = res.get("api", {})
    if not api:
        return "No API registered."
    
    out = "Module API:\n"
    for name, doc in api.items():
        doc_indented = doc.replace("\n", "\n    ")
        out += f"\n- {name}:\n    {doc_indented}"
    return out

if __name__ == "__main__":
    mcp.run()
