import html
import os
import xml.etree.ElementTree as ET
from typing import List, Protocol

from .core import Module, RigBuilderPrivatePath

workspaceFilename = "workspace.xml"


class WorkspaceMainWindow(Protocol):
    """Protocol for the main window passed to save/load workspace. Avoids depending on ui (circular import)."""
    treeWidget: object
    logger: object
    hostCombo: object
    connectionManager: object


def flattenModules(roots: List[Module]) -> List[Module]:
    """Return all modules in depth-first order (roots and every descendant)."""
    flat = []
    # Avoid recursion just in case, but usually depth is fine.
    stack = list(reversed(roots))
    while stack:
        m = stack.pop()
        flat.append(m)
        stack.extend(reversed(m.children()))
    return flat


def saveWorkspace(mainWindow: WorkspaceMainWindow) -> None:
    """Save top-level modules to workspace.xml."""
    path = os.path.join(RigBuilderPrivatePath, workspaceFilename)
    treeWidget = mainWindow.treeWidget
    rootModules = treeWidget.moduleModel.rootModule().children()
    flattenedModules = flattenModules(rootModules)

    lines = [
        '<workspace version="1">',
        "<modules>",
    ]
    for module in rootModules:
        lines.append(module.toXml(keepConnections=True).strip())

    lines.append("</modules>")

    if flattenedModules:
        value = ",".join(str(int(treeWidget.isExpanded(treeWidget.moduleModel.indexForModule(item)))) for item in flattenedModules)
        lines.append('<expanded value="{}"/>'.format(value))

    # Store latest host
    hostName = mainWindow.hostCombo.currentData()
    if hostName:
        lines.append('<host name="{}"/>'.format(html.escape(hostName, quote=True)))

    lines.append("</workspace>")

    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))


def loadWorkspace(mainWindow: WorkspaceMainWindow) -> None:
    """Load module tree from workspace.xml."""
    path = os.path.join(RigBuilderPrivatePath, workspaceFilename)
    if not os.path.exists(path):
        return

    if mainWindow.treeWidget.moduleModel.rowCount() > 0:
        return

    try:
        tree = ET.parse(path)
        root = tree.getroot()
    except ET.ParseError as e:
        mainWindow.logger.warning("Cannot parse workspace: {}".format(e))
        return

    modulesEl = root.find("modules")
    if modulesEl is None:
        return

    roots = []
    for child in modulesEl:
        if child.tag == "module":
            try:
                roots.append(Module.fromXml(child))
            except Exception as e:
                mainWindow.logger.warning("Failed to load module: {}".format(e))

    for module in roots:
        mainWindow.treeWidget.moduleModel.addModuleAt(module)

    expandedEl = root.find("expanded")
    if expandedEl is not None:
        expanded = [x == "1" for x in expandedEl.attrib.get("value", "").split(",")]
        
        rootModules = mainWindow.treeWidget.moduleModel.rootModule().children()
        allModules = flattenModules(rootModules)

        for m, isExpanded in zip(allModules, expanded):
            if isExpanded:
                idx = mainWindow.treeWidget.moduleModel.indexForModule(m)
                if idx.isValid():
                    mainWindow.treeWidget.setExpanded(idx, True)

    # Load latest host
    hostEl = root.find("host")
    if hostEl is not None:
        hostName = hostEl.attrib.get("name")
        if hostName:
            idx = mainWindow.hostCombo.findData(hostName)
            if idx >= 0:
                mainWindow.hostCombo.setCurrentIndex(idx)
