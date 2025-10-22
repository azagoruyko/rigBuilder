import os
import re
import glob
import json
import uuid
import xml.etree.ElementTree as ET
from typing import List, Dict, Optional, Union, Any, Callable, TYPE_CHECKING
from .utils import copyJson, clamp, smartConversion, fromSmartConversion
from .widgets import core as widgets_core

if TYPE_CHECKING:
    from xml.etree.ElementTree import Element

API = {} # modules' runtime API

RigBuilderPath = os.path.dirname(__file__)
RigBuilderLocalPath = os.path.expandvars("$USERPROFILE\\rigBuilder")

def getUidFromFile(path: str) -> Optional[str]:
    """Extract UID from XML file."""
    if path.endswith(".xml"):
        with open(path, "r") as f:
            l = f.readline() # read first line
        r = re.search("uid=\"(\\w*)\"", l)
        if r:
            return r.group(1)

def calculateRelativePath(path: str, root: str) -> str:
    """Calculate relative path from root directory."""
    path = os.path.normpath(path)
    path = path.replace(os.path.normpath(root)+"\\", "")
    return path

class ExitModuleException(Exception):pass
class AttributeResolverError(Exception):pass
class AttributeExpressionError(Exception):pass
class ModuleNotFoundError(Exception):pass
class CopyJsonError(Exception):pass
class ModuleRuntimeError(Exception):pass

class Attribute(object):
    def __init__(self):
        self._name = ""
        self._category = ""
        self._template = ""
        self._connect = "" # attribute connection, format: /a/b/c, where c is attr, a/b is a parent relative path
        self._expression = "" # python code
        self._modified = False
        self._module = None
        self._data = {}

    def copy(self) -> 'Attribute':
        """Create a deep copy of the attribute."""
        attr = Attribute()
        attr._name = self._name
        attr._category = self._category
        attr._template = self._template
        attr._connect = self._connect
        attr._expression = self._expression
        attr._modified = self._modified
        attr._module = self._module
        attr._data = copyJson(self._data)
        return attr

    def name(self) -> str:
        """Get attribute name."""
        return self._name
    
    def setName(self, name: str):
        """Set attribute name and mark as modified."""
        if name != self._name:
            self._name = name
            self._modified = True
    
    def category(self) -> str:
        """Get attribute category."""
        return self._category
    
    def setCategory(self, category: str):
        """Set attribute category and mark as modified."""
        if category != self._category:
            self._category = category
            self._modified = True
    
    def template(self) -> str:
        """Get attribute widget template type."""
        return self._template
    
    def setTemplate(self, template: str):
        """Set attribute widget template type and mark as modified."""
        if template != self._template:
            self._template = template
            self._modified = True
    
    def connect(self) -> str:
        """Get attribute connection path."""
        return self._connect
    
    def setConnect(self, connect: str):
        """Set attribute connection path and mark as modified."""
        if connect != self._connect:
            self._connect = connect
            self._modified = True
    
    def expression(self) -> str:
        """Get attribute Python expression."""
        return self._expression
    
    def setExpression(self, expression: str):
        """Set attribute Python expression and mark as modified."""
        if expression != self._expression:
            self._expression = expression
            self._modified = True
    
    def modified(self) -> bool:
        """Check if attribute has been modified."""
        return self._modified
    
    def module(self) -> Optional['Module']:
        """Get parent module that owns this attribute."""
        return self._module
    
    def _defaultValue(self) -> Any:
        """Get default value from attribute data."""
        if "default" not in self._data:
            return
        return copyJson(self._data[self._data["default"]])
    
    def _setDefaultValue(self, value: Any):
        """Set default value in attribute data."""
        if "default" not in self._data:
            return
        newValue = copyJson(value)
        if newValue != self._defaultValue():
            self._data[self._data["default"]] = newValue
            self._modified = True
    
    def data(self) -> Dict[str, Any]: # return actual read-only copy of all data
        """Get read-only copy of all attribute data."""
        self.pull()
        return copyJson(self._data)
    
    def localData(self) -> Dict[str, Any]:
        """Get copy of local data without pulling from connections."""
        return copyJson(self._data)
    
    def setLocalData(self, data: Dict[str, Any]):
        """Set local data without pushing to connections."""
        newData = copyJson(data)
        if newData != self._data:
            self._data = newData
            self._modified = True
    
    def setData(self, data: Dict[str, Any]):
        """Set data and push to connections."""
        self.setLocalData(data)
        self.push()

    def pull(self):
        """Pull data from connection source and execute expression."""
        if self._connect:
            srcAttr = self.findConnectionSource()
            if srcAttr:
                srcAttr.pull()
                srcAttr.executeExpression()
                self._setDefaultValue(srcAttr._defaultValue())

        self.executeExpression()

    def push(self):
        """Push data to connection source."""
        if self._connect:
            srcAttr = self.findConnectionSource()
            if srcAttr:
                srcAttr._setDefaultValue(self._defaultValue())            
                srcAttr.push()

    def get(self, key: Optional[str] = None) -> Any:
        """Get attribute value or specific data key."""
        self.pull()
        return self._defaultValue() if not key else copyJson(self._data.get(key))
        
    def set(self, value: Any, key: Optional[str] = None):
        """Set attribute value or specific data key."""
        try:
            valueCopy = copyJson(value)
        except TypeError:
            raise CopyJsonError("Cannot set non-JSON data (got {})".format(value))

        if not key:
            self._setDefaultValue(valueCopy)
            self.push()          
        else:
            if self._data.get(key) != valueCopy:
                self._data[key] = valueCopy
                self._modified = True
                self.push()

    def executeExpression(self):
        """Execute Python expression on attribute data."""
        if not self._expression:
            return
        
        ctx = self._module.context()
        ctx.update({"data": self._data, "value": self._defaultValue()})

        try:
            exec(self._expression, ctx)
        except Exception as e:
            raise AttributeExpressionError("Invalid expression: {}".format(str(e)))
        else:
            self._setDefaultValue(ctx["value"])

    def findConnectionSource(self) -> Optional['Attribute']:
        """Find source attribute for connection."""
        if self._module and self._module._parent and self._connect:
            srcAttr = self._module._parent.findAttributeByPath(self._connect)
            return srcAttr

    def listConnections(self) -> List['Attribute']:
        """List all attributes that connect to this attribute."""
        def _listConnections(currentModule: 'Module') -> List['Attribute']:
            connections = []
            for ch in currentModule._children:
                if ch is not self._module: # not self
                    for attr in ch._attributes:
                        if attr._connect:
                            a = attr.findConnectionSource()
                            if a is self:
                                connections.append(attr)

                connections.extend(_listConnections(ch))
            return connections
        return _listConnections(self._module.root())           

    def toXml(self, *, keepConnection: bool = True) -> str:
        """Convert attribute to XML string representation."""
        attrs = [("name", self._name),
                 ("template", self._template),
                 ("category", self._category),
                 ("connect", self._connect if keepConnection else "")]

        attrsStr = " ".join(["{}=\"{}\"".format(k, v) for k, v in attrs])

        data = dict(self._data) # here data can have additional keys for storing custom data
        if self._expression:
            data["_expression"] = self._expression
        
        header = "<attr {attribs}><![CDATA[{data}]]></attr>"
        return header.format(attribs=attrsStr, data=json.dumps(data))
    
    @staticmethod
    def fromXml(root: 'Element') -> 'Attribute':
        """Create attribute from XML element."""
        attr = Attribute()
        attr._name = root.attrib["name"]
        attr._template = root.attrib["template"]
        attr._category = root.attrib["category"]
        attr._connect = root.attrib["connect"]
        attr._data = json.loads(root.text)

        # additional data
        attr._expression = attr._data.pop("_expression", "")
        return attr
    
class Dict(dict):
    def __init__(self):
        pass

    def __getattr__(self, name: str) -> Any:
        return self.get(name)

    def __setattr__(self, name: str, value: Any):
        self[name] = value

class AttrsWrapper(object): # attributes getter/setter
    def __init__(self, module: 'Module'):
        self._module = module

    def __getattr__(self, name: str) -> Attribute:
        module = object.__getattribute__(self, "_module")
        attr = module.findAttribute(name)
        if attr:
            return attr
        else:
            raise AttributeError("Attribute '{}' not found".format(name))

    def __setattr__(self, name: str, value: Any): # for code like 'module.attr.input = value'
        if name == "_module":
            object.__setattr__(self, "_module", value)
        else:
            module = object.__getattribute__(self, "_module")
            attr = module.findAttribute(name)
            if attr:
                attr.set(value)
            else:
                raise AttributeError("Attribute '{}' not found".format(name))

class DataAccessor(): # for accessing data with @_data suffix inside a module's code
    def __init__(self, attr: Attribute):
        self._attr = attr

    def __getitem__(self, name: str) -> Any:
        return self._attr.get(name)

    def __setitem__(self, name: str, value: Any):
        self._attr.set(value, name)

    def __str__(self) -> str:
        return json.dumps(self._attr.data())

class Module(object):
    UpdateSource = "all" # all, server, local, (empty)

    LocalUids = {}
    ServerUids = {}

    glob = Dict() # global memory

    def __init__(self):
        self._uid = "" # unique ids are assigned while saving

        self._name = ""
        self._runCode = ""

        self._parent = None
        self._children = []
        self._attributes = []

        self._muted = False
        self._filePath = ""

        self._modified = False

        self.attr = AttrsWrapper(self) # attributes accessor

    def copy(self) -> 'Module':
        """Create a deep copy of the module."""
        module = Module()
        module._name = self._name
        module._uid = self._uid
        module._runCode = self._runCode

        for a in self._attributes:
            module.addAttribute(a.copy())            

        for ch in self._children:
            module.addChild(ch.copy())

        module._parent = self._parent

        module._filePath = self._filePath
        module._muted = self._muted
        module._modified = self._modified
        return module
    
    def name(self) -> str:
        """Get module name."""
        return self._name
    
    def setName(self, name: str):
        """Set module name."""
        self._name = name

    def uid(self) -> str:
        """Get module unique identifier."""
        return self._uid
    
    def parent(self) -> Optional['Module']:
        """Get parent module in hierarchy."""
        return self._parent
    
    def filePath(self) -> str:
        """Get file path where module was loaded from."""
        return self._filePath
    
    def modified(self) -> bool:
        """Check if module has been modified."""
        return self._modified
    
    def muted(self) -> bool:
        """Check if module is muted (won't execute)."""
        return self._muted

    def mute(self):
        """Mute module to prevent execution."""
        self._muted = True

    def unmute(self):
        """Unmute module to allow execution."""
        self._muted = False

    def runCode(self) -> str:
        """Get module Python execution code."""
        return self._runCode
    
    def setRunCode(self, code: str):
        """Set module Python execution code."""
        self._runCode = code
        self._modified = True

    def root(self) -> 'Module':
        """Get root module in hierarchy."""
        return self._parent.root() if self._parent else self

    def children(self) -> List['Module']:
        """Get list of child modules."""
        return list(self._children)

    def child(self, nameOrIndex: Union[str, int]) -> Optional['Module']:
        """Get child module by name or index."""
        if type(nameOrIndex) == int:
            return self.children()[nameOrIndex]

        elif type(nameOrIndex) == str:
            return self.findChild(nameOrIndex)
            
    def insertChild(self, idx: int, child: 'Module'):
        """Insert child module at specific index."""
        child._parent = self
        self._children.insert(idx, child)
        self._modified = True

    def addChild(self, child: 'Module'):
        """Add child module at the end."""
        self.insertChild(len(self._children), child)

    def removeChild(self, child: 'Module'):
        """Remove child module from children list."""
        child._parent = None
        self._children.remove(child)
        self._modified = True

    def removeChildren(self):
        """Remove all child modules."""
        for ch in self._children:
            ch._parent = None
        self._children = []
        self._modified = True

    def findChild(self, name: str) -> Optional['Module']:
        """Find child module by name."""
        for ch in self._children:
            if ch._name == name:
                return ch

    def attributes(self) -> List[Attribute]:
        """Get list of module attributes."""
        return list(self._attributes)

    def insertAttribute(self, idx: int, attr: Attribute):
        """Insert attribute at specific index."""
        attr._module = self
        self._attributes.insert(idx, attr)
        self._modified = True

    def addAttribute(self, attr: Attribute):
        """Add attribute at the end."""
        self.insertAttribute(len(self._attributes), attr)

    def removeAttribute(self, attr: Attribute):
        """Remove attribute from module."""
        attr._module = None
        self._attributes.remove(attr)
        self._modified = True

    def removeAttributes(self):
        """Remove all attributes from module."""
        for a in self._attributes:
            a._module = None
        self._attributes = []
        self._modified = True

    def findAttribute(self, name: str) -> Optional[Attribute]:
        """Find attribute by name."""
        for a in self._attributes:
            if a._name == name:
                return a
            
    def _clearModificationFlag(self, *, modules: bool = True, attributes: bool = True, recursive: bool = True):
        """Clear modification flags for module and its components."""
        if modules:
            self._modified = False

        if attributes:
            for a in self._attributes:
                a._modified = False     

        for ch in self._children:
            if not ch._uid:
                ch._clearModificationFlag(recursive=recursive, modules=modules, attributes=attributes)
            else:
                ch._clearModificationFlag(recursive=False, modules=False, attributes=attributes)
    
    def ch(self, path: str, key: Optional[str] = None) -> Any:
        """Get attribute value by path."""
        attr = self.findAttributeByPath(path)
        return attr.get(key)
    
    def chdata(self, path: str) -> Dict[str, Any]:
        """Get attribute data by path."""
        attr = self.findAttributeByPath(path)
        return attr.data() # actual read-only copy
    
    def chset(self, path: str, value: Any, key: Optional[str] = None):
        """Set attribute value by path."""
        attr = self.findAttributeByPath(path)
        attr.set(value, key)       

    def toXml(self, *, keepConnections: bool = True) -> str:
        """Convert module to XML string representation."""
        attrs = [("name", self._name),
                 ("muted", int(self._muted)),
                 ("uid", self._uid)]

        attrsStr = " ".join(["{}=\"{}\"".format(k,v) for k, v in attrs])
        template = ["<module {}>".format(attrsStr)]

        template.append("".join(["<run>",
                                 "<![CDATA[", self._runCode, "]]>",
                                 "</run>"]))

        template.append("<attributes>")
        template += [a.toXml(keepConnection=keepConnections) for a in self._attributes]
        template.append("</attributes>")

        template.append("<children>")
        template += [ch.toXml(keepConnections=True) for ch in self._children] # keep inner connections
        template.append("</children>")

        template.append("</module>")

        return "\n".join(template)

    @staticmethod
    def fromXml(root: 'Element') -> 'Module':
        """Create module from XML element."""
        module = Module()
        module._name = root.attrib["name"]
        module._uid = root.attrib.get("uid", "")
        module._muted = int(root.attrib["muted"])

        module._runCode = root.findtext("run")

        for ch in root.find("attributes").findall("attr"):
            module.addAttribute(Attribute.fromXml(ch))

        for ch in root.find("children").findall("module"):
            module.addChild(Module.fromXml(ch))

        module._modified = False
        return module

    def loadedFromServer(self) -> bool:
        """Check if module was loaded from server."""
        return self._filePath.startswith(os.path.normpath(RigBuilderPath+"/modules/"))

    def loadedFromLocal(self) -> bool:
        """Check if module was loaded from local path."""
        return self._filePath.startswith(os.path.normpath(RigBuilderLocalPath+"/modules/"))

    def referenceFile(self, *, source: Optional[str] = None) -> Optional[str]:
        """Get reference file path based on source preference."""
        local = Module.LocalUids.get(self._uid)
        server = Module.ServerUids.get(self._uid)
        path = {"all": local or server, "server": server, "local": local, "":self._filePath}.get(source or Module.UpdateSource)
        return path

    def relativePath(self) -> str:
        """Get relative path from modules directory."""
        if self.loadedFromServer():
            return calculateRelativePath(self._filePath, RigBuilderPath+"/modules")
        elif self.loadedFromLocal():
            return calculateRelativePath(self._filePath, RigBuilderLocalPath+"/modules")
        else:
            return self._filePath

    def relativePathString(self) -> str: # relative loaded path or ../folder/child/module.xml
        """Get display string for relative path."""
        if not self._filePath:
            return ""

        path = ""
        if self.loadedFromServer() or self.loadedFromLocal():
            path = self.relativePath()
        else:
            normLoadedPath = self._filePath.replace("\\", "/")
            items = normLoadedPath.split("/")
            MaxPathItems = 3
            if len(items) > MaxPathItems: # c: folder child module.xml
                path = "../"+"/".join(items[-MaxPathItems:])
            else:
                path = normLoadedPath

        return path.replace(".xml", "")

    def getSavePath(self) -> str:
        """Get path for saving module."""
        if self.loadedFromServer():
            relativePath = os.path.relpath(self._filePath, RigBuilderPath+"/modules")
            return os.path.normpath(RigBuilderLocalPath+"/modules/"+relativePath)

        else: # local or somewhere else
            return self._filePath
        
    def embed(self):
        """Embed module by clearing UID and file path."""
        self._uid = ""
        self._filePath = ""
        self._modified = True

    def update(self):
        """Update module from reference file."""
        origPath = self.referenceFile()
        if origPath:
            origModule = Module.loadFromFile(origPath)
            
            attributes = []
            for origAttr in origModule._attributes:
                foundAttr = self.findAttribute(origAttr._name)
                if origAttr._name and foundAttr and foundAttr._template == origAttr._template: # skip empty named attrs, use first found
                    origAttr._setDefaultValue(foundAttr._defaultValue()) # keep attribute value
                    origAttr._connect = foundAttr._connect
                    origAttr._expression = foundAttr._expression
                    
                origAttr._modified = False # clear modification flag              
                attributes.append(origAttr)

            self._attributes = []
            for a in attributes:
                self.addAttribute(a)

            self._children = []
            for ch in origModule._children:
                self.addChild(ch)

            self._runCode = origModule._runCode
            self._filePath = origModule._filePath

            self._modified = False

        for ch in self._children:
            ch.update()

    def sendToServer(self) -> Optional[str]: # save the module on server, remove locally
        """Save module to server and remove local copy."""
        if self.loadedFromLocal():
            savePath = os.path.normpath(RigBuilderPath+"/modules/"+self.relativePath())
            if not os.path.exists(os.path.dirname(savePath)):
                os.makedirs(os.path.dirname(savePath))

            oldPath = self._filePath
            self.saveToFile(savePath)
            try:
                os.unlink(oldPath) # remove local file
            except OSError:
                pass  # file might already be deleted

            Module.ServerUids[self._uid] = savePath
            Module.LocalUids.pop(self._uid, None) # remove from local uids
            return savePath

    def saveToFile(self, fileName: str, *, newUid: bool = False):
        """Save module to file."""
        if not self._uid or newUid:
            self._uid = uuid.uuid4().hex
        
        with open(os.path.realpath(fileName), "w") as f: # resolve links
            f.write(self.toXml(keepConnections=False)) # don't keep outer connections

        self._filePath = os.path.normpath(fileName)
        self._clearModificationFlag()

    @staticmethod
    def loadFromFile(fileName: str) -> 'Module':
        """Load module from XML file."""
        m = Module.fromXml(ET.parse(fileName).getroot())
        m._filePath = os.path.normpath(fileName)
        m._muted = False
        return m

    @staticmethod
    def loadModule(spec: str) -> 'Module': # spec can be full path, relative path or uid
        """Load module by spec (path, relative path, or UID)."""
        modulePath = Module.LocalUids.get(spec) or Module.ServerUids.get(spec) # check local, then server uids
        
        if not modulePath: # otherwise, find by path
            specPath = os.path.expandvars(spec)

            for path in [specPath, # absolute path
                         specPath+".xml",
                         RigBuilderLocalPath+"/modules/"+spec, # local path
                         RigBuilderLocalPath+"/modules/"+spec+".xml",
                         RigBuilderPath+"/modules/"+spec, # server path
                         RigBuilderPath+"/modules/"+spec+".xml"]:

                if os.path.exists(path):
                    modulePath = path
                    break

            if not modulePath:
                raise ModuleNotFoundError("Module '{}' not found".format(spec))

        module = Module.loadFromFile(modulePath)
        module.update()
        return module

    @staticmethod
    def listModules(path: str) -> List[str]:
        """List all module files in directory recursively."""
        files = []
        for f in sorted(glob.iglob(path+"/*")):
            if os.path.isdir(f):
                files += Module.listModules(f)
            else:
                if f.endswith(".xml"):
                    files.append(f)

        return files

    def path(self, inclusive: bool = True) -> str:
        """Get full path of module in hierarchy."""
        if not self._parent:
            return self._name
        return self._parent.path() + ("/" + self._name if inclusive else "")

    def findAttributeByPath(self, path: str) -> Attribute:
        '''
        Return attribute by path, where path is /a/b/c, where c is attr, a/b is a parent relative path
        '''
        *moduleList, attrName = path.split("/")

        currentParent = self
        for module in moduleList:
            if not module:
                continue

            if module == "..":
                currentParent = currentParent._parent
                continue

            elif module == ".":
                continue

            ch = currentParent.findChild(module)
            if ch:
                currentParent = ch
            else:
                raise AttributeResolverError("Cannot resolve '{}' path".format(path))

        attr = currentParent.findAttribute(attrName)
        if not attr:
            raise AttributeResolverError("Cannot find '{}' attribute".format(path))
        
        return attr

    def context(self) -> Dict[str, Any]:        
        """Get execution environment for module."""
        ctx = {}
        ctx.update(API)
        ctx.update({
            "module": self, 
            "ch": self.ch, 
            "chdata": self.chdata, 
            "chset": self.chset})

        return ctx

    def run(self, *, callback: Optional[Callable[['Module'], None]] = None) -> Dict[str, Any]:
        """Execute module code and child modules."""
        ctx = self.context()

        attrPrefix = "attr_"
        for attr in self._attributes:
            ctx[attrPrefix+attr._name] = attr.get()
            ctx[attrPrefix+"set_"+attr._name] = attr.set
            ctx[attrPrefix+attr._name+"_data"] = DataAccessor(attr)        

        if callable(callback):
            callback(self)

        # replace @abc with prefix_abc
        attrPrefix = "attr_"
        runCode = re.sub(r'@(\w+)', attrPrefix+r'\1', self._runCode)
        
        try:
            exec(runCode, ctx)
        except ExitModuleException:
            pass
        except Exception as e:
            raise ModuleRuntimeError(f"Module '{self.name()}': {str(e)}") from e

        for ch in self._children:
            if not ch.muted():
                ch.run(callback=callback)

        return ctx

    @staticmethod
    def updateUidsCache():
        """Update cached UIDs from local and server directories."""
        Module.ServerUids = Module.findUids(RigBuilderPath + "/modules")
        Module.LocalUids = Module.findUids(RigBuilderLocalPath + "/modules")

    @staticmethod
    def findUids(path: str) -> Dict[str, str]:
        """Find all UIDs and their file paths in directory."""
        uids = {}

        for fpath in sorted(glob.iglob(path+"/*")):
            if os.path.isdir(fpath):
                dirUids = Module.findUids(fpath)
                uids.update(dirUids)

            elif fpath.endswith(".xml"):
                uid = getUidFromFile(fpath)
                if uid:
                    uids[uid] = fpath

        return uids

Module.updateUidsCache()

# API

def printError(msg: str):
    """Print error message and raise RuntimeError."""
    raise RuntimeError(msg)

def printWarning(msg: str):
    """Print warning message."""
    print("Warning: "+msg)

def exitModule():
    """Exit current module execution."""
    raise ExitModuleException()

functionPlaceholder = lambda *args, **kwargs: None

API.update({
    "Module": Module,
    "copyJson": copyJson,
    "exit": exitModule,
    "error": printError,
    "warning": printWarning,
    "listLerp": widgets_core.listLerp,
    "clamp": clamp,
    "smartConversion": smartConversion,
    "fromSmartConversion": fromSmartConversion,

    # data based
    "curve_evaluate": widgets_core.curve_evaluate,
    "curve_evaluateFromX": widgets_core.curve_evaluateFromX,
    "listBox_selected": widgets_core.listBox_selected,
    "listBox_setSelected": widgets_core.listBox_setSelected,
    "comboBox_items": widgets_core.comboBox_items,
    "comboBox_setItems": widgets_core.comboBox_setItems,
    
    # button commands
    "runButtonCommand": widgets_core.runButtonCommand,

    # ui functions
    "beginProgress": functionPlaceholder,
    "stepProgress": functionPlaceholder,
    "endrogress": functionPlaceholder,
})

# Initialize directories and settings

# Create local directory structure
os.makedirs(RigBuilderLocalPath+"/modules", exist_ok=True)

settingsFile = RigBuilderLocalPath+"/settings.json"

Settings = {
    "vscode": "code"
}

if os.path.exists(settingsFile):
    with open(settingsFile, "r") as f:
        Settings.update(json.load(f))
else:
    with open(settingsFile, "w") as f:
        json.dump(Settings, f, indent=4)