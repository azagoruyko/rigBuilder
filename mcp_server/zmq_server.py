import zmq
import json
from PySide6.QtCore import QObject, QTimer, QPersistentModelIndex
from PySide6.QtGui import QTextCursor

ZMQ_PORT = 51607

class RigBuilderAPI:
    """API for RigBuilder"""
    mainWindow = None

    @classmethod
    def get_selected_modules(cls, req):
        """Get currently selected modules"""
        modules = cls.mainWindow.treeWidget.selectedModules()
        if not modules:
            return {"names": [], "paths": []}
        return {
            "names": [m.name() for m in modules],
            "paths": [m.path(inclusive=True) for m in modules]
        }

    @classmethod
    def get_selected_text(cls, req):
        """Get the code editor selection with standard newline characters."""
        editor = cls.mainWindow.codeEditorWidget.editorWidget
        return {"text": editor.textCursor().selectedText().replace("\u2029", "\n")}

    @classmethod
    def replace_selected_text(cls, req):
        """Replace the editor selection in one undo step and select the new text."""
        editor = cls.mainWindow.codeEditorWidget.editorWidget
        if editor.isReadOnly():
            return {"error": "The code editor is read-only."}

        cursor = editor.textCursor()
        if not cursor.hasSelection():
            return {"error": "No text is currently selected in the code editor."}

        start = cursor.selectionStart()
        cursor.beginEditBlock()
        cursor.insertText(req["text"])
        cursor.endEditBlock()
        cursor.setPosition(start, QTextCursor.KeepAnchor)
        editor.setTextCursor(cursor)
        return {"message": "Selected text replaced."}

    @classmethod
    def get_active_module_tree(cls, req):
        """Get the entire active module tree and metadata."""
        from rigBuilder.core import settings
        from rigBuilder.core.utils import relativePath

        treeWidget = cls.mainWindow.treeWidget
        rootModule = treeWidget.moduleModel.rootModule()
        selected = set(treeWidget.selectedModules())

        def module_data(module):
            """Serialize one module and its children in display order."""
            reference = module.referenceFile()
            return {
                "name": module.name(),
                "path": module.path(inclusive=True),
                "reference": relativePath(reference, settings.modulesPath).replace("\\", "/") if reference else "",
                "uid": module.uid(),
                "selected": module in selected,
                "children": [module_data(child) for child in module.children()],
            }

        return {"tree": module_data(rootModule)}

    @classmethod
    def query_module(cls, req):
        """Search for modules by name"""
        query = req.get("query", "")
        k = req.get("k", 5)
        indexer = cls.mainWindow.moduleBrowser.indexer
        
        import asyncio
        import os
        results = asyncio.run(indexer.search(query, k=k))
        
        return {
            "results": [
                {"path": p, "score": s, "name": os.path.splitext(os.path.basename(p))[0]} 
                for p, s in results
            ]
        }

    @classmethod
    def add_module(cls, req):
        """Add a new module to the tree"""
        parent_path = req.get("parent_path", "")
        module_name = req.get("name", "new_module")
        reference_path = req.get("reference_path", "")
        
        model = cls.mainWindow.treeWidget.moduleModel
        rootModule = model.rootModule()
        
        parentModule = rootModule.findModuleByPath(parent_path) if parent_path else rootModule
        if not parentModule:
            return {"error": f"Parent module not found: {parent_path}"}
            
        from rigBuilder.core import Module
        from rigBuilder.ui import AddModuleCommand, undoStack
        
        if reference_path:
            new_module = Module.loadModule(reference_path)
            if module_name and module_name != "new_module":
                new_module.setName(module_name)
        else:
            new_module = Module(module_name)
            
        cmd = AddModuleCommand(model, new_module, parentModule, -1)
        undoStack.push(cmd)
        return {"message": f"Added module {new_module.name()} to {parent_path}"}

    @classmethod
    def move_module(cls, req):
        """Move one module to a parent and position it before a sibling."""
        module_path = req.get("module_path", "")
        parent_path = req.get("target_parent_path", "")
        before_path = req.get("before_path", "")
        model = cls.mainWindow.treeWidget.moduleModel
        rootModule = model.rootModule()

        module = rootModule.findModuleByPath(module_path)
        if not module:
            return {"error": f"Module not found: {module_path}"}
        if module is rootModule:
            return {"error": "Cannot move ROOT module"}

        targetParent = rootModule.findModuleByPath(parent_path)
        if not targetParent:
            return {"error": f"Target parent not found: {parent_path}"}

        ancestor = targetParent
        while ancestor:
            if ancestor is module:
                return {"error": "Cannot move a module into itself or its descendant"}
            ancestor = ancestor.parent()

        oldParent = module.parent()
        siblings = [child for child in targetParent.children() if child is not module]
        if oldParent is not targetParent and any(child.name() == module.name() for child in siblings):
            return {"error": f"Target parent already has a module named: {module.name()}"}

        if before_path:
            beforeModule = rootModule.findModuleByPath(before_path)
            if not beforeModule or beforeModule.parent() is not targetParent or beforeModule is module:
                return {"error": f"Insert-before module must be another child of the target parent: {before_path}"}
            targetRow = siblings.index(beforeModule)
        else:
            targetRow = len(siblings)

        if oldParent is targetParent and oldParent.children().index(module) == targetRow:
            return {"message": f"Module already at requested position: {module.path(inclusive=True)}"}

        from rigBuilder.ui import MoveModulesCommand, undoStack

        undoStack.push(MoveModulesCommand(model, [module], targetParent, targetRow))
        return {"message": f"Moved {module_path} to {module.path(inclusive=True)} at row {targetRow}"}

    @classmethod
    def remove_module(cls, req):
        """Remove a module from the tree"""
        module_path = req.get("module_path", "")
        
        model = cls.mainWindow.treeWidget.moduleModel
        rootModule = model.rootModule()
        
        module = rootModule.findModuleByPath(module_path)
        if not module:
            return {"error": f"Module not found: {module_path}"}
            
        if module == rootModule:
            return {"error": "Cannot remove ROOT module"}
            
        idx = model.indexForModule(module)
        if not idx.isValid():
            return {"error": f"Invalid index for module: {module_path}"}
            
        from rigBuilder.ui import RemoveModulesCommand, undoStack
        cmd = RemoveModulesCommand(model, [module])
        undoStack.push(cmd)
        
        return {"message": f"Removed module {module_path}"}

    @classmethod
    def get_module_subtree(cls, req):
        """Get XML representation of a module in the tree"""
        rootModule = cls.mainWindow.treeWidget.moduleModel.rootModule()
        module_path = req.get("module_path", "")
        module = rootModule.findModuleByPath(module_path) if module_path else rootModule
        if not module:
            return {"error": f"Module not found: {module_path}"}
        return {"xml": module.toXml()}

    @classmethod
    def set_module_subtree(cls, req):
        """Set a module in the tree from XML."""
        model = cls.mainWindow.treeWidget.moduleModel
        rootModule = model.rootModule()
        module_path = req.get("module_path", "")
        xml_str = req.get("xml", "")
        
        existing_module = rootModule.findModuleByPath(module_path) if module_path else rootModule
        if not existing_module:
            return {"error": f"Module not found: {module_path}"}
            
        from rigBuilder.core import Module
        from rigBuilder.ui import ReplaceModuleCommand, undoStack

        try:
            new_module = Module.fromXml(xml_str)
        except Exception as e:
            return {"error": f"Error: {str(e)}"}

        undoStack.push(ReplaceModuleCommand(model, existing_module, new_module))
        cls.mainWindow.treeWidget.selectModule(new_module)
        
        return {"message": f"Successfully replaced module from XML: {new_module.path(inclusive=True)}"}

    @classmethod
    def get_module(cls, req):
        """Return only a module's own content as XML."""
        module_path = req.get("module_path", "")
        root = cls.mainWindow.treeWidget.moduleModel.rootModule()
        module = root.findModuleByPath(module_path)
        if not module:
            return {"error": f"Module not found: {module_path}"}

        return {"xml": module.copy(children=False).toXml()}

    @classmethod
    def set_module(cls, req):
        """Edit module content and attributes in place, preserving children."""
        module_path = req.get("module_path", "")
        root = cls.mainWindow.treeWidget.moduleModel.rootModule()
        module = root.findModuleByPath(module_path)
        if not module:
            return {"error": f"Module not found: {module_path}"}

        from rigBuilder.core import Module

        try:
            replacement = Module.fromXml(req.get("xml", ""))
        except (SyntaxError, ValueError, TypeError) as exc:
            return {"error": f"Invalid module XML: {exc}"}

        if replacement.name() != module.name() or replacement.uid() != module.uid():
            return {"error": "Module name and UID must match the existing module"}
        if replacement.children():
            return {"error": "Module XML must not contain children"}

        same_content = (replacement.runCode(), replacement.doc(), replacement.muted()) == (
            module.runCode(), module.doc(), module.muted()
        )
        same_attributes = [attr.toXml() for attr in replacement.attributes()] == [
            attr.toXml() for attr in module.attributes()
        ]
        if same_content and same_attributes:
            return {"message": f"Module content already matches: {module_path}"}

        from rigBuilder.ui import EditModuleContentCommand, undoStack

        cls.mainWindow.treeWidget.selectModule(module)
        undoStack.push(EditModuleContentCommand(cls.mainWindow, module, replacement))
        return {"message": f"Updated module content: {module_path}"}

    @classmethod
    def get_attribute(cls, req):
        """Return one attribute's XML from the active module tree."""
        module_path = req.get("module_path", "")
        name = req.get("name", "")
        root = cls.mainWindow.treeWidget.moduleModel.rootModule()
        module = root.findModuleByPath(module_path)
        if not module:
            return {"error": f"Module not found: {module_path}"}

        attr = module.findAttribute(name)
        if not attr:
            return {"error": f"Attribute not found: {name}"}

        return {"xml": attr.toXml()}

    @classmethod
    def add_attribute(cls, req):
        """Add one parsed attribute through the UI undo stack."""
        module_path = req.get("module_path", "")
        root = cls.mainWindow.treeWidget.moduleModel.rootModule()
        module = root.findModuleByPath(module_path)
        if not module:
            return {"error": f"Module not found: {module_path}"}

        from rigBuilder.core import Attribute

        try:
            attr = Attribute.fromXml(req.get("xml", ""))
        except (SyntaxError, ValueError, TypeError) as exc:
            return {"error": f"Invalid attribute XML: {exc}"}

        if not attr.name() or not attr.template() or not isinstance(attr.localData(), dict):
            return {"error": "Attribute requires a name, template, and JSON object data"}
        if module.findAttribute(attr.name()):
            return {"error": f"Attribute already exists: {attr.name()}"}

        before_name = req.get("before_name", "")
        before = module.findAttribute(before_name) if before_name else None
        if before_name and not before:
            return {"error": f"Insert-before attribute not found: {before_name}"}

        from rigBuilder.ui import AddAttributeCommand, undoStack

        index = module.attributes().index(before) if before else None
        cls.mainWindow.treeWidget.selectModule(module)
        undoStack.push(AddAttributeCommand(cls.mainWindow.attributesTreeView, module, attr, index))
        return {"message": f"Added attribute {attr.name()} to {module_path}"}

    @classmethod
    def set_attribute(cls, req):
        """Replace one existing attribute through the UI undo stack."""
        module_path = req.get("module_path", "")
        name = req.get("name", "")
        root = cls.mainWindow.treeWidget.moduleModel.rootModule()
        module = root.findModuleByPath(module_path)
        if not module:
            return {"error": f"Module not found: {module_path}"}

        attr = module.findAttribute(name)
        if not attr:
            return {"error": f"Attribute not found: {name}"}

        from rigBuilder.core import Attribute

        try:
            replacement = Attribute.fromXml(req.get("xml", ""))
        except (SyntaxError, ValueError, TypeError) as exc:
            return {"error": f"Invalid attribute XML: {exc}"}

        if replacement.name() != name:
            return {"error": "Replacement XML name must match the existing attribute name"}
        if not replacement.template() or not isinstance(replacement.localData(), dict):
            return {"error": "Attribute requires a template and JSON object data"}

        from rigBuilder.ui import EditAttributeCommand, undoStack

        cls.mainWindow.treeWidget.selectModule(module)
        undoStack.push(EditAttributeCommand(
            cls.mainWindow.attributesTreeView, attr, attr.toXml(), replacement.toXml(),
            f"Edit attribute '{name}'",
        ))
        return {"message": f"Updated attribute {name} in {module_path}"}

    @classmethod
    def move_attribute(cls, req):
        """Reorder one attribute through the UI undo stack."""
        module_path = req.get("module_path", "")
        name = req.get("name", "")
        before_name = req.get("before_name", "")
        root = cls.mainWindow.treeWidget.moduleModel.rootModule()
        module = root.findModuleByPath(module_path)
        if not module:
            return {"error": f"Module not found: {module_path}"}

        attr = module.findAttribute(name)
        if not attr:
            return {"error": f"Attribute not found: {name}"}

        before = module.findAttribute(before_name) if before_name else None
        if before_name and not before:
            return {"error": f"Insert-before attribute not found: {before_name}"}
        if before is attr:
            return {"error": "Cannot move an attribute before itself"}

        old_order = module.attributes()
        new_order = [item for item in old_order if item is not attr]
        index = new_order.index(before) if before else len(new_order)
        new_order.insert(index, attr)
        if new_order == old_order:
            return {"message": f"Attribute already at requested position: {name}"}

        from rigBuilder.ui import MoveAttributesCommand, undoStack

        cls.mainWindow.treeWidget.selectModule(module)
        undoStack.push(MoveAttributesCommand(
            cls.mainWindow.attributesTreeView, module, old_order, new_order
        ))
        return {"message": f"Moved attribute {name} to position {index} in {module_path}"}

    @classmethod
    def remove_attribute(cls, req):
        """Remove one attribute through the UI undo stack."""
        module_path = req.get("module_path", "")
        name = req.get("name", "")
        root = cls.mainWindow.treeWidget.moduleModel.rootModule()
        module = root.findModuleByPath(module_path)
        if not module:
            return {"error": f"Module not found: {module_path}"}

        attr = module.findAttribute(name)
        if not attr:
            return {"error": f"Attribute not found: {name}"}

        from rigBuilder.ui import RemoveAttributeCommand, undoStack

        cls.mainWindow.treeWidget.selectModule(module)
        undoStack.push(RemoveAttributeCommand(cls.mainWindow.attributesTreeView, attr))
        return {"message": f"Removed attribute {name} from {module_path}"}

    @classmethod
    def read_log(cls, req):
        """Get the contents of the log widget"""
        return {"log": cls.mainWindow.logWidget.toPlainText()}

    @classmethod
    def get_available_hosts(cls, req):
        """Get the list of available discovered hosts"""
        from rigBuilder.core.connectionManager import connectionManager
        return {"hosts": list(connectionManager.servers().keys())}

    @classmethod
    def switch_host(cls, req):
        """Switch the current host via the UI"""
        host_name = req.get("host_name", "")
        idx = cls.mainWindow.hostCombo.findText(host_name)
        if idx >= 0:
            cls.mainWindow.hostCombo.setCurrentIndex(idx)
            return {"message": f"Switched to host: {host_name}"}
        return {"message": f"Host not found: {host_name}"}

    @classmethod
    def execute_module(cls, req):
        """Execute a module by its path"""
        module_path = req.get("module_path", "")
        model = cls.mainWindow.treeWidget.moduleModel
        rootModule = model.rootModule()
        module = rootModule.findModuleByPath(module_path)
        if not module:
            return {"error": f"Module not found: {module_path}"}
            
        cls.mainWindow.treeWidget.selectModule(module)
        cls.mainWindow.runModule()
        return {"message": f"Executed module {module_path}"}

    @classmethod
    def read_module_api(cls, req):
        """Read the registered API from the main window's API browser"""
        return {"api": cls.mainWindow.apiBrowser.browser.toPlainText()}

    @classmethod
    def get_workspace_settings(cls, req):
        """Get the settings of the current active workspace"""
        import os
        from rigBuilder.core.settings import settings
        data = settings.toDict()
        data["workspaceName"] = os.path.basename(settings.workspacePath)
        return data


class ZmqServer(QObject):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.context = zmq.Context()
        self.socket = self.context.socket(zmq.REP)
        self.socket.setsockopt(zmq.LINGER, 0)
        try:
            self.socket.bind(f"tcp://127.0.0.1:{ZMQ_PORT}")
        except zmq.ZMQError as e:
            print(f"[ZMQ Server] Failed to bind to port {ZMQ_PORT}: {e}")
            return
            
        self.timer = QTimer(self)
        self.timer.timeout.connect(self._poll_zmq)
        self.timer.start(100) # Poll every 100ms
        
        self.mainWindow = None

    def close(self):
        if hasattr(self, 'timer') and self.timer.isActive():
            self.timer.stop()
        if hasattr(self, 'socket') and self.socket:
            self.socket.close()
        if hasattr(self, 'context') and self.context:
            self.context.term()

    def setMainWindow(self, mainWindow):
        self.mainWindow = mainWindow
        RigBuilderAPI.mainWindow = mainWindow

    def _poll_zmq(self):
        try:
            message = self.socket.recv_string(flags=zmq.NOBLOCK)
        except zmq.Again:
            return
            
        try:
            req = json.loads(message)
            if self.mainWindow:
                self.mainWindow.mcpLabel.showTool(req.get("action"))
            resp = self._handle_request(req)
            self.socket.send_string(json.dumps({"status": "success", "data": resp}))
        except Exception as e:
            import traceback
            traceback.print_exc()
            self.socket.send_string(json.dumps({"status": "error", "message": str(e)}))
        finally:
            if self.mainWindow:
                self.mainWindow.mcpLabel.finishTool()

    def _handle_request(self, req: dict) -> dict:
        action = req.get("action")
        
        if not RigBuilderAPI.mainWindow:
            return {"error": "MainWindow not set on ZmqServer"}

        # Disallow calling private methods
        if not action or action.startswith("_"):
            return {"error": f"Invalid action: {action}"}

        # Dispatch to RigBuilderAPI
        method = getattr(RigBuilderAPI, action, None)
        if not method or not callable(method):
            return {"error": f"Unknown action: {action}"}
            
        return method(req)
