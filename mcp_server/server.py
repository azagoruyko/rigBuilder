import json
import sys
import os
from fastmcp import FastMCP

MCP_DIRECTORY = os.path.dirname(os.path.abspath(__file__))
sys.path.append(MCP_DIRECTORY)
with open(os.path.join(os.path.dirname(MCP_DIRECTORY), "ai", "prompt.md"), "r", encoding="utf-8") as f:
    CHAT_PROMPT = f.read()

# Initialize MCP Server
mcp = FastMCP("RigBuilder AI", instructions=CHAT_PROMPT)

client = None

def get_client():
    global client
    if client is None:
        from zmq_client import ZmqClient
        client = ZmqClient()
    return client

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

@mcp.resource("docs://example.rb")
def get_example_module() -> str:
    """Returns the example.rb module. Useful as a reference for Rig Builder module structure."""
    example_path = os.path.join(os.path.dirname(MCP_DIRECTORY), "modules", "example.rb")
    if os.path.exists(example_path):
        with open(example_path, "r", encoding="utf-8") as f:
            return f.read()
            
    return "example.rb not found."

@mcp.tool()
def read_resource(uri: str) -> str:
    """Read content from an MCP resource URI (e.g. 'docs://rig-builder-reference', 'docs://example.rb').
    Args:
        uri: Resource URI string to read.
    """
    if uri == "docs://rig-builder-reference":
        return read_rig_builder_reference()
    elif uri == "docs://example.rb":
        return get_example_module()
    return f"Unknown resource URI: {uri}"

@mcp.tool()
def get_selected_modules() -> str:
    """Returns the names and paths of the currently selected modules in the UI.
    Useful for contextual edits when the user has something selected.
    """
    res = get_client().send_request("get_selected_modules")
    if res.get("error"):
        return res.get("error")

    names = res.get("names", [])
    paths = res.get("paths", [])
    if not names:
        return "No modules are currently selected."
        
    output = "Selected Modules:\n"
    for name, path in zip(names, paths):
        output += f"- {name} (Path: {path})\n"

    return output

@mcp.tool()
def get_selected_text() -> str:
    """Return the code editor's selected text, or an empty string if nothing is selected.

    Preserves whitespace and returns multiline selections with newline characters.
    """
    res = get_client().send_request("get_selected_text")
    if res.get("error"):
        return res.get("error")

    return res.get("text", "")

@mcp.tool()
def replace_selected_text(text: str) -> str:
    """Replace the code editor's current selection as one undoable edit.

    Use get_selected_text first to read the selection. The replacement stays
    selected so it can be read back. An empty text deletes the selection.
    Returns an error without editing if nothing is selected or the editor is read-only.

    Args:
        text: Replacement text for the current selection.
    """
    res = get_client().send_request("replace_selected_text", text=text)
    if res.get("error"):
        return res.get("error")

    return res.get("message", "Success")

@mcp.tool()
def get_active_module_tree() -> str:
    """Return the entire live module tree from ROOT.

    Each row includes its exact path, reference, UID, selection, and direct child count.
    Use the path= value for operations on a specific module.
    """
    res = get_client().send_request("get_active_module_tree")
    if res.get("error"):
        return res.get("error")

    root = res.get("tree")
    if not root:
        return "No modules are currently in the tree."

    lines = ["Current Module Hierarchy:"]

    def append_module(module, prefix="", branch=""):
        """Append one tree row and recursively append its children."""
        children = module["children"]
        parts = [module["name"], f'path={module["path"]}']
        if module["reference"]:
            parts.append(f'@ref={module["reference"]}')
        if module["uid"]:
            parts.append(f'uid={module["uid"]}')
        if children:
            count = len(children)
            parts.append(f'({count} child{"ren" if count != 1 else ""})')
        else:
            parts.append("[leaf]")
        if module["selected"]:
            parts.append("← selected")
        lines.append(prefix + branch + "  ".join(parts))

        child_prefix = prefix + ("   " if branch == "└─ " else "│  " if branch else "")
        for index, child in enumerate(children):
            append_module(child, child_prefix, "└─ " if index == len(children) - 1 else "├─ ")

    append_module(root)
    return "\n".join(lines)

@mcp.tool()
def query_module(query: str, k: int = 5) -> str:
    """Semantically search for existing workspace modules using natural language.
    Useful for finding a module if you don't know the exact name (e.g. 'an arm setup', 'IK solver').
    Args:
        query: Natural language query describing what you're looking for.
        k: Maximum number of results to return.
    """
    res = get_client().send_request("query_module", query=query, k=k)
    if res.get("error"):
        return res.get("error")

    results = res.get("results", [])
    results = [r for r in results if r['score'] > 0.5]
    if not results:
        return "No modules found matching the query."
        
    out = f"Search results for '{query}':\n"
    for r in results:
        out += f"- {r['name']} (Path: {r['path']}, Score: {r['score']:.2f})\n"

    return out

@mcp.tool()
def add_module(parent_path: str, name: str, reference_path: str = "") -> str:
    """Adds a new module to the current tree in Rig Builder.
    Args:
        parent_path: The path of the parent module (e.g. 'ROOT/spine'). Leave empty for ROOT.
        name: The name for the new module.
        reference_path: (Optional) Path string relative to 'modules/' of an existing module file in the current workspace (e.g. 'biped/arm.xml'). If empty, creates an empty module.
    """
    res = get_client().send_request("add_module", parent_path=parent_path, name=name, reference_path=reference_path)
    if res.get("error"):
        return res.get("error")

    return res.get("message", "Success")

@mcp.tool()
def move_module(module_path: str, target_parent_path: str, before_path: str = "") -> str:
    """Move one module under another parent or reorder it as one undoable edit.

    Use exact paths from get_active_module_tree. An empty target_parent_path means ROOT.
    Omit before_path to append; otherwise insert before a child of the target parent.

    Args:
        module_path: Full path of the module to move.
        target_parent_path: Full path of the destination parent, or empty for ROOT.
        before_path: Full path of the destination sibling to insert before.
    """
    res = get_client().send_request(
        "move_module",
        module_path=module_path,
        target_parent_path=target_parent_path,
        before_path=before_path,
    )
    if res.get("error"):
        return res.get("error")

    return res.get("message", "Success")

@mcp.tool()
def remove_module(module_path: str) -> str:
    """Removes a module from the active tree.
    Args:
        module_path: The full path to the module to remove (e.g. 'ROOT/spine/arm_L').
    """
    res = get_client().send_request("remove_module", module_path=module_path)
    if res.get("error"):
        return res.get("error")

    return res.get("message", "Success")

@mcp.tool()
def get_module_subtree(module_path: str = "") -> str:
    """Return a module and all its descendants as XML.
    
    CRITICAL INSTRUCTION FOR AI: Before reading or making any changes, you MUST 
    read the 'docs://rig-builder-reference' resource to understand the XML structure.
    
    Args:
        module_path: The full path to the module (e.g. 'ROOT/spine_01'). Leave empty for ROOT.
    """
    res = get_client().send_request("get_module_subtree", module_path=module_path)
    if res.get("error"):
        return res.get("error")

    return res.get("xml", "")

@mcp.tool()
def set_module_subtree(module_path: str, xml_str: str) -> str:
    """Replaces a module subtree exactly using its full XML representation as one undoable edit.
    Omitted content is removed. No reference synchronization or file saving is performed.
    
    CRITICAL INSTRUCTION FOR AI: Before setting any XML, you MUST read the 
    'docs://rig-builder-reference' resource to ensure you are using the correct schema and syntax.
    
    Args:
        module_path: The full path to the module being updated.
        xml_str: The complete XML string of the updated module.
    """
    res = get_client().send_request("set_module_subtree", module_path=module_path, xml=xml_str)
    if res.get("error"):
        return res.get("error")

    return res.get("message", "Success")


@mcp.tool()
def get_module(module_path: str) -> str:
    """Return one module's XML, including its attributes but not its children.

    Includes the module name, UID, muted state, run code, and documentation.
    Read docs://rig-builder-reference before editing module XML.
    """
    res = get_client().send_request("get_module", module_path=module_path)
    if res.get("error"):
        return res["error"]

    return res.get("xml", "")


@mcp.tool()
def set_module(module_path: str, module_xml: str) -> str:
    """Replace one module's content and attributes as one undoable edit.

    Use XML from get_module. The name and UID must match; children cannot be
    included. Existing children remain untouched. Omitted attributes are removed.
    Read docs://rig-builder-reference before editing module XML.
    """
    res = get_client().send_request("set_module", module_path=module_path, xml=module_xml)
    if res.get("error"):
        return res["error"]

    return res.get("message", "Success")


@mcp.tool()
def get_attribute(module_path: str, name: str) -> str:
    """Return one attribute's XML without reading its module's children.

    Read docs://rig-builder-reference before editing attribute XML.
    """
    res = get_client().send_request("get_attribute", module_path=module_path, name=name)
    if res.get("error"):
        return res["error"]

    return res.get("xml", "")


@mcp.tool()
def add_attribute(module_path: str, attribute_xml: str, before_name: str = "") -> str:
    """Add one attribute to a module as an undoable edit.

    Omit before_name to append. The XML must contain one complete <attr> element.
    Read docs://rig-builder-reference before creating attribute XML.
    """
    res = get_client().send_request(
        "add_attribute", module_path=module_path, xml=attribute_xml, before_name=before_name
    )
    if res.get("error"):
        return res["error"]

    return res.get("message", "Success")


@mcp.tool()
def set_attribute(module_path: str, name: str, attribute_xml: str) -> str:
    """Replace one existing attribute exactly, preserving its position.

    The XML attribute name must match name. Read docs://rig-builder-reference first.
    """
    res = get_client().send_request(
        "set_attribute", module_path=module_path, name=name, xml=attribute_xml
    )
    if res.get("error"):
        return res["error"]

    return res.get("message", "Success")


@mcp.tool()
def move_attribute(module_path: str, name: str, before_name: str = "") -> str:
    """Move one attribute before another in the same module as an undoable edit.

    Omit before_name to move it to the end.
    """
    res = get_client().send_request(
        "move_attribute", module_path=module_path, name=name, before_name=before_name
    )
    if res.get("error"):
        return res["error"]

    return res.get("message", "Success")


@mcp.tool()
def remove_attribute(module_path: str, name: str) -> str:
    """Remove one attribute from a module as an undoable edit."""
    res = get_client().send_request("remove_attribute", module_path=module_path, name=name)
    if res.get("error"):
        return res["error"]

    return res.get("message", "Success")


@mcp.tool()
def read_log() -> str:
    """Read the contents of the log widget from the main window."""
    res = get_client().send_request("read_log")
    if res.get("error"):
        return res.get("error")

    return res.get("log", "")

@mcp.tool()
def get_available_hosts() -> str:
    """Returns a list of available discovered hosts."""
    res = get_client().send_request("get_available_hosts")
    if res.get("error"):
        return res.get("error")

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
    res = get_client().send_request("switch_host", host_name=host_name)
    if res.get("error"):
        return res.get("error")

    return res.get("message", "Success")

@mcp.tool()
def execute_module(module_path: str) -> str:
    """Executes a module by its full path in the active tree.
    Args:
        module_path: The full path to the module (e.g. 'ROOT/spine_01').
    """
    res = get_client().send_request("execute_module", module_path=module_path)
    if res.get("error"):
        return res.get("error")

    return res.get("message", "Success")

@mcp.tool()
def read_module_api() -> str:
    """Reads the API functions and objects available to modules at runtime (from APIRegistry)."""
    res = get_client().send_request("read_module_api")
    if res.get("error"):
        return res.get("error")

    return res.get("api", "No API registered.")

@mcp.tool()
def get_workspace_settings() -> str:
    """Returns the settings of the current active workspace, including paths and auto-save options."""
    res = get_client().send_request("get_workspace_settings")
    if res.get("error"):
        return res.get("error")

    if not res:
        return "Failed to retrieve workspace settings."
    
    workspace_name = res.get("workspaceName", "Unknown")
    out = f"Active Workspace: {workspace_name}\nSettings:\n"
    for k, v in sorted(res.items()):
        if k == "workspaceName":
            continue
        out += f"- {k}: {v}\n"
    return out

if __name__ == "__main__":
    mcp.run(transport="stdio", show_banner=False, log_level="WARNING")
