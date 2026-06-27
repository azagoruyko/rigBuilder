import zmq
import json
from PySide6.QtCore import QObject, QTimer, QPersistentModelIndex

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
    def get_modules(cls, req):
        """Get all modules in the tree"""
        rootModule = cls.mainWindow.treeWidget.moduleModel.rootModule()
        
        def _get_paths(module):
            paths = [module.path(inclusive=True)]
            for c in module.children():
                paths.extend(_get_paths(c))
            return paths
            
        return {"modules": _get_paths(rootModule)}

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
        template_path = req.get("template_path", "")
        
        model = cls.mainWindow.treeWidget.moduleModel
        rootModule = model.rootModule()
        
        parentModule = rootModule.findModuleByPath(parent_path) if parent_path else rootModule
        if not parentModule:
            raise Exception(f"Parent module not found: {parent_path}")
            
        parentIndex = model.indexForModule(parentModule)
        
        from rigBuilder.core import Module
        from rigBuilder.ui import AddModuleCommand
        
        if template_path:
            new_module = Module.loadModule(template_path)
            if module_name and module_name != "new_module":
                new_module.setName(module_name)
        else:
            new_module = Module(module_name)
            
        cmd = AddModuleCommand(model, new_module, parentIndex, -1)
        model.undoStack.push(cmd)
        return {"message": f"Added module {new_module.name()} to {parent_path}"}

    @classmethod
    def remove_module(cls, req):
        """Remove a module from the tree"""
        module_path = req.get("module_path", "")
        
        model = cls.mainWindow.treeWidget.moduleModel
        rootModule = model.rootModule()
        
        module = rootModule.findModuleByPath(module_path)
        if not module:
            raise Exception(f"Module not found: {module_path}")
            
        if module == rootModule:
            raise Exception("Cannot remove ROOT module")
            
        idx = model.indexForModule(module)
        if not idx.isValid():
            raise Exception(f"Invalid index for module: {module_path}")
            
        from rigBuilder.ui import RemoveModulesCommand
        cmd = RemoveModulesCommand(model, [idx])
        model.undoStack.push(cmd)
        
        return {"message": f"Removed module {module_path}"}

    @classmethod
    def get_module_xml(cls, req):
        """Get XML representation of a module in the tree"""
        rootModule = cls.mainWindow.treeWidget.moduleModel.rootModule()
        module_path = req.get("module_path", "")
        module = rootModule.findModuleByPath(module_path) if module_path else rootModule
        if not module:
            raise Exception(f"Module not found: {module_path}")
        return {"xml": module.toXml()}

    @classmethod
    def set_module_xml(cls, req):
        """Set a module in the tree from XML."""
        model = cls.mainWindow.treeWidget.moduleModel
        rootModule = model.rootModule()
        module_path = req.get("module_path", "")
        xml_str = req.get("xml", "")
        
        existing_module = rootModule.findModuleByPath(module_path) if module_path else rootModule
        if not existing_module:
            raise Exception(f"Module not found: {module_path}")
            
        from rigBuilder.core import Module
        from rigBuilder.ui import SyncModuleWithCommand
        new_module = Module.fromXml(xml_str)

        model.undoStack.push(SyncModuleWithCommand(model, existing_module, new_module))
        cls.mainWindow.treeWidget.selectModule(existing_module)
        
        return {"message": f"Successfully updated module from XML: {module_path}"}

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
        raise Exception(f"Host not found: {host_name}")

    @classmethod
    def execute_module(cls, req):
        """Execute a module by its path"""
        module_path = req.get("module_path", "")
        model = cls.mainWindow.treeWidget.moduleModel
        rootModule = model.rootModule()
        module = rootModule.findModuleByPath(module_path)
        if not module:
            raise Exception(f"Module not found: {module_path}")
            
        cls.mainWindow.treeWidget.selectModule(module)
        cls.mainWindow.runModule()
        return {"message": f"Executed module {module_path}"}

    @classmethod
    def read_module_api(cls, req):
        """Read the registered API from the main window's API browser"""
        return {"text": cls.mainWindow.apiBrowser.getPlainText()}

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
            resp = self._handle_request(req)
            self.socket.send_string(json.dumps({"status": "success", "data": resp}))
        except Exception as e:
            import traceback
            traceback.print_exc()
            self.socket.send_string(json.dumps({"status": "error", "message": str(e)}))

    def _handle_request(self, req: dict) -> dict:
        action = req.get("action")
        
        if not RigBuilderAPI.mainWindow:
            raise Exception("MainWindow not set on ZmqServer")

        # Disallow calling private methods
        if not action or action.startswith("_"):
            raise Exception(f"Invalid action: {action}")

        # Dispatch to RigBuilderAPI
        method = getattr(RigBuilderAPI, action, None)
        if not method or not callable(method):
            raise Exception(f"Unknown action: {action}")
            
        return method(req)
