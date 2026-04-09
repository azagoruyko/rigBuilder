import os
import re
import glob
import json
import uuid
import xml.etree.ElementTree as ET
from typing import List, Dict, Optional, Union, Any, Callable, TYPE_CHECKING
from .utils import copyJson, clamp, smartConversion, fromSmartConversion, Dict
from .widgets import core as widgets_core

if TYPE_CHECKING:
    from xml.etree.ElementTree import Element

RIG_BUILDER_PATH = os.path.dirname(__file__)
RIG_BUILDER_USER_PATH = os.path.normpath(os.path.join(os.path.expanduser("~"), "rigBuilder"))
MODULE_EXT = ".rb" # default extension for new/saved modules
MODULE_EXTS = (MODULE_EXT, ".xml")  # accepted extensions (xml for backward compat)

ATTR_PREFIX = "attr_"

def replaceAttrPrefix(code: str) -> str:
    return re.sub(r'@(\w+)', ATTR_PREFIX + r'\1', code)

def replaceAttrPrefixInverse(code: str) -> str:
    return re.sub(r'{}(\w+)'.format(ATTR_PREFIX), r'@\1', code)

class UidManager:
    _uids: Dict[str, str] = {}

    @classmethod
    def update(cls):
        """Update cached UIDs from modules directory."""
        cls._uids = cls.findUids(getModulesPath())

    @classmethod
    def get(cls, uid: str) -> Optional[str]:
        """Get file path by UID."""
        return cls._uids.get(uid)

    @classmethod
    def uids(cls) -> Dict[str, str]:
        """Get all cached UIDs."""
        return cls._uids

    @classmethod
    def resolve(cls, spec: str) -> str:
        """Resolve spec (path or uid) to module file path, or empty string if not found."""
        if not spec:
            return ""
            
        modulePath = cls.get(spec)
        if not modulePath:
            root = getModulesPath()
            spec = os.path.expandvars(spec)

            specPaths = [
                root + spec + ext
                for root in ("", f"{root}/")
                for ext in ("",) + MODULE_EXTS
            ]

            for path in specPaths:
                if os.path.exists(path):
                    modulePath = path
                    break

        return os.path.normpath(modulePath) if modulePath else ""

    @staticmethod
    def getUidFromFile(path: str) -> Optional[str]:
        """Extract UID from a module file (.rb or .xml)."""
        if any(path.endswith(ext) for ext in MODULE_EXTS):
            try:
                with open(path, "r", encoding="utf-8") as f:
                    l = f.readline()  # read first line
                r = re.search("uid=\"(\\w*)\"", l)
                if r:
                    return r.group(1)
            except Exception:
                pass
        return None

    @classmethod
    def findUids(cls, path: str) -> Dict[str, str]:
        """Find all UIDs and their file paths in directory."""
        uids = {}
        for fpath in sorted(glob.iglob(path + "/*")):
            if os.path.isdir(fpath):
                uids.update(cls.findUids(fpath))
            elif any(fpath.endswith(ext) for ext in MODULE_EXTS):
                uid = cls.getUidFromFile(fpath)
                if uid:
                    uids[uid] = fpath
        return uids


def calculateRelativePath(path: str, root: str) -> str:
    """Calculate relative path from root directory."""
    path = os.path.normpath(path)
    root = os.path.normpath(root)
    if path.lower().startswith(root.lower() + os.sep):
        return path[len(root) + 1:]
    else:
        return path

class ExitModuleException(Exception):pass
class AttributeResolverError(Exception):pass
class AttributeExpressionError(Exception):pass
class ModuleNotFoundError(Exception):pass
class CopyJsonError(Exception):pass
class APIError(Exception):pass


class APIRegistryMeta(type):
    """Metaclass enabling APIRegistry.foo and APIRegistry.foo = func convenience."""

    _reserved = frozenset({"_objects", "clear", "register", "unregister", "override", "api"})

    def __getattr__(cls, name: str):
        if name in cls._objects:
            return cls._objects[name]
        raise AttributeError(f"'{cls.__name__}' has no attribute '{name}'")

    def __setattr__(cls, name: str, value: Any):
        if name in APIRegistryMeta._reserved:
            type.__setattr__(cls, name, value)
        else:
            cls._objects[name] = value


class APIRegistry(metaclass=APIRegistryMeta):
    """Registry for functions and objects available to modules at runtime."""

    _objects: Dict[str, Any] = {}

    @staticmethod
    def clear():
        """Clear all objects from registry"""
        APIRegistry._objects.clear()

    @staticmethod
    def register(name: str, func: Optional[Any] = None):
        """Register object in API."""
        f = func if func else lambda *args, **kwargs: None
        APIRegistry._objects[name] = f

    @staticmethod
    def override(name: str, func: Any):
        """Override object in API."""
        if name not in APIRegistry._objects:
            raise APIError(f"Object '{name}' is not registered")
        APIRegistry._objects[name] = func

    @staticmethod
    def unregister(name: str):
        """"Unregister object from API"""
        if name not in APIRegistry._objects:
            raise APIError(f"Object '{name}' is not registered")
        del APIRegistry._objects[name]

    @staticmethod
    def api() -> Dict[str, Any]:
        """Get all registered objects as dictionary for exec()."""
        return Dict(APIRegistry._objects)


def legacy_convertLineEditTemplate(attr): # get rid of legacy LineEdit        
    if attr._template == "lineEdit":
        attr._template = "lineEditAndButton"
        attr._data["buttonEnabled"] = False

    if attr._template == "compound":
        templates = attr._data["templates"]
        widgets = attr._data["widgets"]
        for i, _ in enumerate(templates):
            if templates[i] == "lineEdit":
                templates[i] = "lineEditAndButton"
                widgets[i]["buttonEnabled"] = False


class Attribute(object):
    def __init__(self):
        self._name = ""
        self._category = ""
        self._template = ""
        self._connect = "" # attribute connection, format: /a/b/c, where c is attr, a/b is a parent relative path
        self._expression = "" # python code
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
        attr._module = self._module
        attr._data = copyJson(self._data)
        return attr

    def name(self) -> str:
        """Get attribute name."""
        return self._name
    def setName(self, name: str):
        """Set attribute name."""
        if name != self._name:
            self._name = name
    
    def category(self) -> str:
        """Get attribute category."""
        return self._category
    
    def setCategory(self, category: str):
        """Set attribute category."""
        if category != self._category:
            self._category = category
    
    def template(self) -> str:
        """Get attribute widget template type."""
        return self._template
    
    def setTemplate(self, template: str):
        """Set attribute widget template type."""
        if template != self._template:
            self._template = template
    
    def connect(self) -> str:
        """Get attribute connection path."""
        return self._connect
    
    def setConnect(self, connect: str):
        """Set attribute connection path."""
        if connect != self._connect:
            self._connect = connect
    
    def expression(self) -> str:
        """Get attribute Python expression."""
        return self._expression
    
    def setExpression(self, expression: str):
        """Set attribute Python expression."""
        if expression != self._expression:
            self._expression = expression
    
    def module(self) -> Optional['Module']:
        """Get parent module that owns this attribute."""
        return self._module
    
    def _defaultValue(self) -> Any:
        """Get default value from attribute data."""
        if "default" in self._data:
            return copyJson(self._data[self._data["default"]])
    
    def _setDefaultValue(self, value: Any):
        """Set default value in attribute data."""
        if "default" in self._data:
            newValue = copyJson(value)
            if newValue != self._defaultValue():
                self._data[self._data["default"]] = newValue
    
    def data(self) -> Dict[str, Any]: # return actual read-only copy of all data
        """Get read-only copy of all attribute data."""
        self.pull()
        return copyJson(self._data)
    
    def localData(self) -> Dict[str, Any]:
        """Get copy of local data without pulling from connections."""
        return copyJson(self._data)
        
    def setLocalData(self, newData: Dict[str, Any]):
        """Set local data without pushing to connections."""
        self._data = newData
    
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
        attr._name = root.attrib.get("name", "")
        attr._template = root.attrib.get("template", "")
        attr._category = root.attrib.get("category", "")
        attr._connect = root.attrib.get("connect", "")
        raw = root.text or "{}"
        attr._data = json.loads(raw) if raw.strip() else {}
        attr._expression = attr._data.pop("_expression", "")
        legacy_convertLineEditTemplate(attr)
        return attr

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


    glob = Dict() # global memory

    def __init__(self):
        self._uid = "" # unique ids are assigned while saving

        self._name = ""
        self._runCode = ""
        self._doc = ""

        self._parent = None
        self._children = []
        self._attributes = []

        self._muted = False

        self.attr = AttrsWrapper(self) # attributes accessor

    def copy(self) -> 'Module':
        """Create a deep copy of the module."""
        module = Module()
        module._name = self._name
        module._uid = self._uid
        module._runCode = self._runCode
        module._doc = self._doc

        for a in self._attributes:
            module.addAttribute(a.copy())            

        for ch in self._children:
            module.addChild(ch.copy())

        module._parent = None

        module._muted = self._muted
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

    def doc(self) -> str:
        """Get module documentation (implicitly Markdown)."""
        return self._doc

    def setDoc(self, doc: str):
        """Set module documentation (implicitly Markdown)."""
        self._doc = doc

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

    def addChild(self, child: 'Module'):
        """Add child module at the end."""
        self.insertChild(len(self._children), child)

    def removeChild(self, child: 'Module'):
        """Remove child module from children list."""
        child._parent = None
        self._children.remove(child)

    def removeChildren(self):
        """Remove all child modules."""
        for ch in self._children:
            ch._parent = None
        self._children = []

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

    def addAttribute(self, attr: Attribute):
        """Add attribute at the end."""
        self.insertAttribute(len(self._attributes), attr)

    def removeAttribute(self, attr: Attribute):
        """Remove attribute from module."""
        attr._module = None
        self._attributes.remove(attr)

    def removeAttributes(self):
        """Remove all attributes from module."""
        for a in self._attributes:
            a._module = None
        self._attributes = []

    def findAttribute(self, name: str) -> Optional[Attribute]:
        """Find attribute by name."""
        for a in self._attributes:
            if a._name == name:
                return a
            
    def ch(self, path: str, key: Optional[str] = None) -> Any:
        """Get an attribute's value or dictionary key by path."""
        attr = self.findAttributeByPath(path)
        return attr.get(key)
    
    def chdata(self, path: str) -> Dict[str, Any]:
        """Get the underlying data dictionary of an attribute."""
        attr = self.findAttributeByPath(path)
        return attr.data() # actual read-only copy
    
    def chset(self, path: str, value: Any, key: Optional[str] = None):
        """Set an attribute's value or dictionary key by path."""
        attr = self.findAttributeByPath(path)
        attr.set(value, key)       

    def toXml(self, *, keepConnections: bool = True) -> str:
        """Convert module to XML string representation."""
        attrs = [("name", self._name),
                 ("muted", int(self._muted)),
                 ("uid", self._uid)]

        attrsStr = " ".join(["{}=\"{}\"".format(k,v) for k, v in attrs])
        template = ["<module {}>".format(attrsStr)]

        if self._runCode:
            template.append("".join(["<run>",
                                     "<![CDATA[", self._runCode, "]]>",
                                     "</run>"]))

        if self._doc:
            template.append("".join(["<doc>",
                                     "<![CDATA[", self._doc, "]]>",
                                     "</doc>"]))

        if self._attributes:
            template.append("<attributes>")
            template += [a.toXml(keepConnection=keepConnections) for a in self._attributes]
            template.append("</attributes>")

        if self._children:
            template.append("<children>")
            template += [ch.toXml(keepConnections=True) for ch in self._children] # keep inner connections
            template.append("</children>")

        template.append("</module>")

        return "\n".join(template)

    @staticmethod
    def fromXml(root: 'Element') -> 'Module':
        """Create module from XML element. Tolerates missing optional elements."""
        module = Module()
        module._name = root.attrib.get("name", "")
        module._uid = root.attrib.get("uid", "")
        module._muted = int(root.attrib.get("muted", 0))
        module._runCode = root.findtext("run") or ""
        
        doc_el = root.find("doc")
        if doc_el is not None:
            module._doc = doc_el.text or ""

        attrs_el = root.find("attributes")
        if attrs_el is not None:
            for ch in attrs_el.findall("attr"):
                module.addAttribute(Attribute.fromXml(ch))

        children_el = root.find("children")
        if children_el is not None:
            for ch in children_el.findall("module"):
                module.addChild(Module.fromXml(ch))

        return module

    def loadedFromStore(self) -> bool:
        """Check if module was loaded from the modules store."""
        return self._uid in UidManager.uids()

    def referenceFile(self) -> Optional[str]:
        """Get reference file path."""
        return UidManager.get(self._uid)

    def relativePath(self) -> str:
        """Get relative path from modules directory."""
        path = UidManager.resolve(self._uid)
        if self.loadedFromStore():
            return calculateRelativePath(path, getModulesPath())
        else:
            return path

    def relativePathString(self) -> str:
        """Get display string for relative path."""
        filePath = UidManager.resolve(self._uid)
        if not filePath:
            return ""

        path = ""
        if self.loadedFromStore():
            path = self.relativePath().replace("\\", "/")
        else:
            normLoadedPath = filePath.replace("\\", "/")
            items = normLoadedPath.split("/")
            MaxPathItems = 3
            if len(items) > MaxPathItems: # c: folder child module.xml
                path = "../"+"/".join(items[-MaxPathItems:])
            else:
                path = normLoadedPath

        return os.path.splitext(path)[0]
        
    def embed(self):
        """Embed module by clearing UID."""
        self._uid = ""

    def update(self):
        """Update module from reference file."""
        refPath = self.referenceFile()
        if refPath:
            refModule = Module.loadFromFile(refPath)

            # Update attributes
            origAttrs = {a._name: a for a in self._attributes}
            self._attributes.clear()

            for origAttr in refModule._attributes:
                foundAttr = origAttrs.get(origAttr._name)
                if foundAttr:
                    if origAttr._name and foundAttr._template == origAttr._template: # shallow update
                        origAttr._setDefaultValue(foundAttr._defaultValue()) 
                        origAttr._connect = foundAttr._connect
                        origAttr._expression = foundAttr._expression

                self.addAttribute(origAttr)

            # Update children
            self._children.clear()

            for ch in refModule._children:
                self.addChild(ch)

            self._runCode = refModule._runCode
            self._doc = refModule._doc

        for ch in self._children:
            ch.update()

    def saveToFile(self, fileName: str, *, newUid: bool = False):
        """Save module to file."""
        if not self._uid or newUid:
            self._uid = uuid.uuid4().hex
        
        with open(os.path.realpath(fileName), "w", encoding="utf-8") as f:  # resolve links
            f.write(self.toXml(keepConnections=False))  # don't keep outer connections

        UidManager.update()

    @staticmethod
    def loadFromFile(fileName: str) -> 'Module':
        """Load module from XML file."""
        with open(fileName, "r", encoding="utf-8") as f:
            m = Module.fromXml(ET.parse(f).getroot())
        m._muted = False
        return m

    @staticmethod
    def loadModule(spec: str, *, update: bool = True) -> 'Module': # spec can be full path, relative path or uid
        """Load module by spec (path, relative path, or UID)."""
        modulePath = UidManager.resolve(spec)
        if not modulePath:
            raise ModuleNotFoundError("Module '{}' not found".format(spec))

        module = Module.loadFromFile(modulePath)
        if update:
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
                if any(f.endswith(ext) for ext in MODULE_EXTS):
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

    def findModuleByPath(self, path: str) -> Optional['Module']:
        """Find a module by its path string (e.g., 'Root/Child/Grandchild' or 'Child/Grandchild')."""
        if not path or path == ".":
            return self

        parts = path.split("/")
        current = self

        if parts[0] == self._name:
            parts = parts[1:]

        for part in parts:
            if not part:
                continue

            if part == "..":
                current = current._parent
                if not current:
                    return None
                continue

            elif part == ".":
                continue

            ch = current.findChild(part)
            if ch:
                current = ch
            else:
                return None

        return current

    def context(self) -> Dict[str, Any]:        
        """Get execution environment for module."""
        ctx = APIRegistry.api()
        ctx.update({
            "module": self, 
            "ch": self.ch, 
            "chdata": self.chdata, 
            "chset": self.chset})

        for attr in self._attributes:
            ctx[ATTR_PREFIX + attr._name] = attr._defaultValue()
            ctx[ATTR_PREFIX + "set_" + attr._name] = attr.set
            ctx[ATTR_PREFIX + attr._name + "_data"] = DataAccessor(attr)            

        return ctx

    def executeCode(self, code: str, context: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """Execute code in the context of the module."""
        ctx = self.context()
        ctx.update(context or {})
        
        try:
            exec(replaceAttrPrefix(code), ctx)
        except ExitModuleException:
            pass
        
        return ctx

    def run(self, *, callback: Optional[Callable[['Module'], None]] = None) -> Dict[str, Any]:
        """Execute module code and child modules."""
        if callable(callback):
            callback(self)

        for attr in self._attributes:
            attr.pull()

        ctx = self.executeCode(self._runCode)

        for ch in self._children:
            if not ch.muted():
                ch.run(callback=callback)

        return ctx


def getModulesPath() -> str:
    """Return the modules root directory, normalized."""
    path = Settings.get("modulesPath") or ""
    if path:
        return os.path.normpath(path)

    defaultRoot = os.path.join(RIG_BUILDER_PATH, "modules")
    return os.path.normpath(defaultRoot)



def getHistoryPath() -> str:
    """Return the history directory for module version history (git-tracked)."""
    path = Settings.get("historyPath") or ""
    if path:
        return os.path.normpath(path)

    return os.path.normpath(os.path.join(RIG_BUILDER_USER_PATH, "history"))


def getWorkspacesPath() -> str:
    """Return the directory where workspace files are stored."""
    return os.path.normpath(os.path.join(RIG_BUILDER_USER_PATH, "workspaces"))




# Initialize directories and settings
os.makedirs(RIG_BUILDER_USER_PATH, exist_ok=True)
settingsFile = os.path.join(RIG_BUILDER_USER_PATH, "settings.json")

Settings = {
    "vscode": "code",
    "modulesPath": "",
    "historyPath": "",
    "trackHistory": True,
    "ollamaModel": "gpt-oss:20b-cloud",
    "aiLanguage": "English",
    "currentWorkspace": ""
}

if os.path.exists(settingsFile):
    with open(settingsFile, "r", encoding="utf-8") as f:
        try:
            Settings.update(json.load(f))
        except json.JSONDecodeError:
            print("Settings file is corrupted. Using default settings.")
else:
    with open(settingsFile, "w", encoding="utf-8") as f:
        json.dump(Settings, f, indent=4, ensure_ascii=False)

def saveSettings():
    """Persist Settings to settings.json."""
    with open(settingsFile, "w", encoding="utf-8") as f:
        json.dump(Settings, f, indent=4, ensure_ascii=False)
        
os.makedirs(getModulesPath(), exist_ok=True)

UidManager.update()

# API

def printError(msg: str):
    """Raise a RuntimeError and stop execution."""
    raise RuntimeError(msg)

def printWarning(msg: str):
    """Print a warning message to the log."""
    print("Warning: "+msg)

def exitModule():
    """Immediately stop the current module's execution."""
    raise ExitModuleException()

def beginProgress(text: str, count: int, updatePercent: float = 0.01):
    """Initialize and display the main progress bar."""
    pass

def stepProgress(value: int, text: str = None):
    """Update the progress bar to a specific value."""
    pass

def endProgress():
    """Close and hide the progress bar."""
    pass

# overridden in module.run

APIRegistry.register("module", Module()) 
APIRegistry.register("ch", Module().ch)
APIRegistry.register("chdata", Module().chdata)
APIRegistry.register("chset", Module().chset)

# core functions

APIRegistry.register("Module", Module)
APIRegistry.register("copyJson", copyJson)
APIRegistry.register("exit", exitModule)
APIRegistry.register("error", printError)
APIRegistry.register("warning", printWarning)
APIRegistry.register("listLerp", widgets_core.listLerp)
APIRegistry.register("clamp", clamp)
APIRegistry.register("smartConversion", smartConversion)
APIRegistry.register("fromSmartConversion", fromSmartConversion)

# widgets functions

APIRegistry.register("curve_evaluate", widgets_core.curve_evaluate) # data based
APIRegistry.register("curve_evaluateFromX", widgets_core.curve_evaluateFromX)
APIRegistry.register("comboBox_items", widgets_core.comboBox_items)
APIRegistry.register("comboBox_setItems", widgets_core.comboBox_setItems)

APIRegistry.register("runButtonCommand", widgets_core.runButtonCommand)

# UI functions

APIRegistry.register("beginProgress", beginProgress)
APIRegistry.register("stepProgress", stepProgress)
APIRegistry.register("endProgress", endProgress)
