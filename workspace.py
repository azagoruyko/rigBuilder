import html
import os
import xml.etree.ElementTree as ET
from typing import List, Protocol

from .core import Module, RigBuilderLocalPath

workspaceFilename = "workspace.xml"


class WorkspaceMainWindow(Protocol):
    """Protocol for the main window passed to save/load workspace. Avoids depending on ui (circular import)."""
    treeWidget: object
    logger: object


def flattenModules(roots: List[Module]) -> List[Module]:
    """Return all modules in depth-first order (roots and every descendant)."""
    flat = []
    stack = list(reversed(roots))
    while stack:
        m = stack.pop()
        flat.append(m)
        stack.extend(reversed(m.children()))
    return flat


def saveWorkspace(mainWindow: WorkspaceMainWindow) -> None:
    """Save top-level modules to workspace.xml. Modules stored as-is (toXml); meta holds per-module patch by index."""
    path = os.path.join(RigBuilderLocalPath, workspaceFilename)
    roots = [
        mainWindow.treeWidget.topLevelItem(i).module
        for i in range(mainWindow.treeWidget.topLevelItemCount())
    ]
    allModules = flattenModules(roots)

    lines = [
        '<workspace version="1">',
        "<modules>",
    ]
    for module in roots:
        lines.append(module.toXml(keepConnections=True).strip())

    lines.append("</modules>")
    lines.append("<meta>")

    for index, module in enumerate(allModules):
        if not module.filePath():
            continue

        filePath = html.escape(module.filePath(), quote=True)
        modified = str(int(module.modified()))

        modifiedAttrs = [(i, a) for i, a in enumerate(module.attributes()) if a.modified()]
        if not modifiedAttrs:
            lines.append('<module index="{}" filePath="{}" modified="{}"/>'.format(index, filePath, modified))

        else:
            lines.append('<module index="{}" filePath="{}" modified="{}">'.format(index, filePath, modified))
            for i, _ in modifiedAttrs:
                lines.append('<attr index="{}" modified="1"/>'.format(i))

            lines.append("</module>")

    lines.append("</meta>")
    lines.append("</workspace>")

    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))


def loadWorkspace(mainWindow: WorkspaceMainWindow) -> None:
    """Load module tree from workspace.xml and apply meta patch per module (by depth-first index)."""
    path = os.path.join(RigBuilderLocalPath, workspaceFilename)
    if not os.path.exists(path):
        return

    if mainWindow.treeWidget.topLevelItemCount() > 0:
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

    flat = flattenModules(roots)
    metaEl = root.find("meta")
    if metaEl is not None:
        metaByIndex = {}
        for item in metaEl.findall("module"):
            idx = item.attrib.get("index")
            if idx is not None:
                try:
                    metaByIndex[int(idx)] = item
                except ValueError:
                    pass

        for index, module in enumerate(flat):
            item = metaByIndex.get(index)
            if item is None:
                continue

            path = item.attrib.get("filePath", "")
            if path and os.path.exists(path):
                module._filePath = path
            module._modified = bool(int(item.attrib.get("modified", 0)))

            attrsList = module.attributes()
            for attrEl in item.findall("attr"):
                try:
                    i = int(attrEl.attrib.get("index", -1))
                except ValueError:
                    continue
                if 0 <= i < len(attrsList):
                    attrsList[i]._modified = bool(int(attrEl.attrib.get("modified", 0)))

    for module in roots:
        mainWindow.treeWidget.addTopLevelItem(
            mainWindow.treeWidget.makeItemFromModule(module)
        )
