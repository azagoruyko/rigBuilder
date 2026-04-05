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

RigBuilderPath = os.path.dirname(__file__)
RigBuilderPrivatePath = os.path.normpath(os.path.join(os.path.expanduser("~"), "rigBuilder"))
MODULE_EXT = ".rb"            # default extension for new/saved modules
MODULE_EXTS = (MODULE_EXT, ".xml")  # accepted extensions (xml for backward compat)

ATTR_PREFIX = "attr_"

def replaceAttrPrefix(code: str) -> str:
    return re.sub(r'@(\w+)', ATTR_PREFIX + r'\1', code)

def replaceAttrPrefixInverse(code: str) -> str:
    return re.sub(r'{}(\w+)'.format(ATTR_PREFIX), r'@\1', code)

def getUidFromFile(path: str) -> Optional[str]:
    """Extract UID from a module file (.rb or .xml)."""
    if any(path.endswith(ext) for ext in MODULE_EXTS):
        with open(path, "r", encoding="utf-8") as f:
            l = f.readline()  # read first line
        r = re.search("uid=\"(\\w*)\"", l)
        if r:
            return r.group(1)

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
            self._markModified()
    
    def category(self) -> str:
        """Get attribute category."""
        return self._category
    
    def setCategory(self, category: str):
        """Set attribute category and mark as modified."""
        if category != self._category:
            self._category = category
            self._markModified()
    
    def template(self) -> str:
        """Get attribute widget template type."""
        return self._template
    
    def setTemplate(self, template: str):
        """Set attribute widget template type and mark as modified."""
        if template != self._template:
            self._template = template
            self._markModified()
    
    def connect(self) -> str:
        """Get attribute connection path."""
        return self._connect
    
    def setConnect(self, connect: str):
        """Set attribute connection path and mark as modified."""
        if connect != self._connect:
            self._connect = connect
            self._markModified()
    
    def expression(self) -> str:
        """Get attribute Python expression."""
        return self._expression
    
    def setExpression(self, expression: str):
        """Set attribute Python expression and mark as modified."""
        if expression != self._expression:
            self._expression = expression
            self._markModified()
    
    def modified(self) -> bool:
        """Check if attribute has been modified."""
        return self._modified

    def _markModified(self):
        """Mark attribute and parent module as modified."""
        self._modified = True
        if self._module:
            self._module._modified = True

    def module(self) -> Optional['Module']:
        """Get parent module that owns this attribute."""
        return self._module
    
    def _defaultValue(self) -> Any:
        """Get default value from attribute data."""
        if "default" in self._data:
            return copyJson(self._data[self._data["default"]])
    
    def _setDefaultValue(self, value: Any):
        """Set default value in attribute data. Does not mark modified (preserved by update)."""
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
    
    def setLocalData(self, data: Dict[str, Any]):
        """Set local data without pushing to connections. Marks modified only if change is not solely the default value."""
        newData = copyJson(data)

        if newData == self._data:
            return
            
        oldData = self._data
        defaultKey = oldData.get("default") or newData.get("default")
        
        onlyDefaultValueChanged = (
            set(oldData.keys()) == set(newData.keys())
            and oldData.get("default") == newData.get("default")
            and all(
                oldData.get(k) == newData.get(k)
                for k in oldData
                if k != defaultKey
            )
        )

        self._data = newData
        if not onlyDefaultValueChanged:
            self._markModified()
    
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
                if key != self._data.get("default"):
                    self._markModified()
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
                 ("connect", self._connect if keepConnection else ""),
                 ("modified", int(self._modified))]

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
        attr._modified = bool(int(root.attrib.get("modified", 0)))
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
    UpdateSource = "all" # all, public, private, (empty)

    PrivateUids = {}
    PublicUids = {}

    glob = Dict() # global memory

    def __init__(self):
        self._uid = "" # unique ids are assigned while saving

        self._name = ""
        self._runCode = ""
        self._doc = ""
        self._docFormat = "html"

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
        module._doc = self._doc
        module._docFormat = self._docFormat

        for a in self._attributes:
            module.addAttribute(a.copy())            

        for ch in self._children:
            module.addChild(ch.copy())

        module._parent = None

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

    def doc(self) -> str:
        """Get module documentation (raw HTML or Markdown depending on docFormat)."""
        return self._doc

    def setDoc(self, doc: str):
        """Set module documentation (raw HTML or Markdown depending on docFormat)."""
        self._doc = doc
        self._modified = True

    def docFormat(self) -> str:
        """Get documentation format: 'html' or 'markdown'."""
        return self._docFormat

    def setDocFormat(self, fmt: str):
        """Set documentation format to 'html' or 'markdown'."""
        if fmt not in ("html", "markdown"):
            raise ValueError("docFormat must be 'html' or 'markdown', got: {}".format(fmt))
        self._docFormat = fmt
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
                 ("uid", self._uid),
                 ("modified", int(self._modified)),
                 ("filePath", self._filePath)]

        attrsStr = " ".join(["{}=\"{}\"".format(k,v) for k, v in attrs])
        template = ["<module {}>".format(attrsStr)]

        template.append("".join(["<run>",
                                 "<![CDATA[", self._runCode, "]]>",
                                 "</run>"]))

        if self._doc:
            template.append("".join(["<doc format=\"{}\">".format(self._docFormat),
                                     "<![CDATA[", self._doc, "]]>",
                                     "</doc>"]))

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
        """Create module from XML element. Tolerates missing optional elements."""
        module = Module()
        module._name = root.attrib.get("name", "")
        module._uid = root.attrib.get("uid", "")
        module._muted = int(root.attrib.get("muted", 0))
        module._filePath = root.attrib.get("filePath", "")
        module._runCode = root.findtext("run") or ""
        
        doc_el = root.find("doc")
        if doc_el is not None:
            module._doc = doc_el.text or ""
            module._docFormat = doc_el.attrib.get("format", "html")

        attrs_el = root.find("attributes")
        if attrs_el is not None:
            for ch in attrs_el.findall("attr"):
                module.addAttribute(Attribute.fromXml(ch))

        children_el = root.find("children")
        if children_el is not None:
            for ch in children_el.findall("module"):
                module.addChild(Module.fromXml(ch))

        module._modified = bool(int(root.attrib.get("modified", 0))) # set modified flag after all children/attributes are added
        return module

    def loadedFromPublic(self) -> bool:
        """Check if module was loaded from public path."""
        filePath = os.path.normpath(self._filePath or "")
        publicRoot = getPublicModulesPath()
        return filePath.lower().startswith(publicRoot.lower() + os.sep)

    def loadedFromPrivate(self) -> bool:
        """Check if module was loaded from private path."""        
        filePath = os.path.normpath(self._filePath or "")
        privateRoot = getPrivateModulesPath()
        return filePath.lower().startswith(privateRoot.lower() + os.sep)

    def referenceFile(self, *, source: Optional[str] = None) -> Optional[str]:
        """Get reference file path based on source preference."""
        private = Module.PrivateUids.get(self._uid)
        public = Module.PublicUids.get(self._uid)
        path = {"all": private or public, "public": public, "private": private, "":self._filePath}.get(source or Module.UpdateSource)
        return path

    def relativePath(self) -> str:
        """Get relative path from modules directory."""
        if self.loadedFromPublic():
            return calculateRelativePath(self._filePath, getPublicModulesPath())
        elif self.loadedFromPrivate():
            return calculateRelativePath(self._filePath, getPrivateModulesPath())
        else:
            return self._filePath

    def relativePathString(self) -> str: # relative loaded path or ../folder/child/module.xml
        """Get display string for relative path."""
        if not self._filePath:
            return ""

        path = ""
        if self.loadedFromPublic() or self.loadedFromPrivate():
            path = self.relativePath()
        else:
            normLoadedPath = self._filePath.replace("\\", "/")
            items = normLoadedPath.split("/")
            MaxPathItems = 3
            if len(items) > MaxPathItems: # c: folder child module.xml
                path = "../"+"/".join(items[-MaxPathItems:])
            else:
                path = normLoadedPath

        return os.path.splitext(path)[0]

    def getSavePath(self) -> str:
        """Get path for saving module."""
        if self.loadedFromPublic():
            relativePath = os.path.relpath(self._filePath, getPublicModulesPath())
            return os.path.join(getPrivateModulesPath(), relativePath)

        else: # private or somewhere else
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
            self._doc = origModule._doc
            self._docFormat = origModule._docFormat
            self._filePath = origModule._filePath

            self._modified = False

        for ch in self._children:
            ch.update()

    def publish(self) -> Optional[str]: # save the module on public path, remove from private
        """Save module to public path and remove private copy."""
        if self.loadedFromPrivate():
            savePath = os.path.join(getPublicModulesPath(), self.relativePath())
            if not os.path.exists(os.path.dirname(savePath)):
                os.makedirs(os.path.dirname(savePath))

            oldPath = self._filePath
            self.saveToFile(savePath)
            try:
                os.unlink(oldPath) # remove private file
            except OSError:
                pass  # file might already be deleted

            Module.PublicUids[self._uid] = savePath
            Module.PrivateUids.pop(self._uid, None) # remove from private uids
            return savePath

    def saveToFile(self, fileName: str, *, newUid: bool = False):
        """Save module to file."""
        if not self._uid or newUid:
            self._uid = uuid.uuid4().hex
        
        self._clearModificationFlag()
        
        with open(os.path.realpath(fileName), "w", encoding="utf-8") as f:  # resolve links
            f.write(self.toXml(keepConnections=False))  # don't keep outer connections

        self._filePath = os.path.normpath(fileName)

    @staticmethod
    def loadFromFile(fileName: str) -> 'Module':
        """Load module from XML file."""
        with open(fileName, "r", encoding="utf-8") as f:
            m = Module.fromXml(ET.parse(f).getroot())
        m._filePath = os.path.normpath(fileName)
        m._muted = False
        return m

    @staticmethod
    def loadModule(spec: str, *, update: bool = True) -> 'Module': # spec can be full path, relative path or uid
        """Load module by spec (path, relative path, or UID)."""
        modulePath = resolveModuleSpec(spec)
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

    @staticmethod
    def updateUidsCache():
        """Update cached UIDs from private and public directories."""
        Module.PublicUids = Module.findUids(getPublicModulesPath())
        Module.PrivateUids = Module.findUids(getPrivateModulesPath())

    @staticmethod
    def findUids(path: str) -> Dict[str, str]:
        """Find all UIDs and their file paths in directory."""
        uids = {}

        for fpath in sorted(glob.iglob(path+"/*")):
            if os.path.isdir(fpath):
                dirUids = Module.findUids(fpath)
                uids.update(dirUids)

            elif any(fpath.endswith(ext) for ext in MODULE_EXTS):
                uid = getUidFromFile(fpath)
                if uid:
                    uids[uid] = fpath

        return uids

def getPrivateModulesPath() -> str:
    """Return the private modules root directory, normalized."""
    privateModulesRoot = os.path.join(RigBuilderPrivatePath, "modules")
    return os.path.normpath(privateModulesRoot)

def getPublicModulesPath() -> str:
    """Return the public modules root directory, normalized."""
    path = Settings.get("publicModulesPath") or ""
    if path:
        return os.path.normpath(path)

    defaultPublicRoot = os.path.join(RigBuilderPath, "modules")
    return os.path.normpath(defaultPublicRoot)


def getHistoryPath() -> str:
    """Return the history directory for module version history (git-tracked)."""
    return os.path.normpath(os.path.join(RigBuilderPrivatePath, "history"))


def resolveModuleSpec(spec: str) -> str:
    """Resolve spec (path or uid) to module file path, or empty string if not found."""
    if not spec:
        return ""
    modulePath = Module.PrivateUids.get(spec) or Module.PublicUids.get(spec)
    if not modulePath:
        private, public = getPrivateModulesPath(), getPublicModulesPath()
        spec = os.path.expandvars(spec)

        specPaths = [
            root + spec + ext
            for root in ("", f"{private}/", f"{public}/")
            for ext in ("",) + MODULE_EXTS
        ]

        for path in specPaths:
            if os.path.exists(path):
                modulePath = path
                break

    return os.path.normpath(modulePath) if modulePath else ""


# Initialize directories and settings
os.makedirs(RigBuilderPrivatePath, exist_ok=True)
settingsFile = os.path.join(RigBuilderPrivatePath, "settings.json")

Settings = {
    "vscode": "code",
    "publicModulesPath": "",
    "trackHistory": True
}

if os.path.exists(settingsFile):
    with open(settingsFile, "r") as f:
        Settings.update(json.load(f))
else:
    with open(settingsFile, "w") as f:
        json.dump(Settings, f, indent=4)

def saveSettings():
    """Persist Settings to settings.json."""
    with open(settingsFile, "w") as f:
        json.dump(Settings, f, indent=4)
        
os.makedirs(getPrivateModulesPath(), exist_ok=True)
os.makedirs(getHistoryPath(), exist_ok=True)

Module.updateUidsCache()

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
APIRegistry.register("listBox_selected", widgets_core.listBox_selected)
APIRegistry.register("listBox_setSelected", widgets_core.listBox_setSelected)
APIRegistry.register("comboBox_items", widgets_core.comboBox_items)
APIRegistry.register("comboBox_setItems", widgets_core.comboBox_setItems)

APIRegistry.register("runButtonCommand", widgets_core.runButtonCommand)

# UI functions

APIRegistry.register("beginProgress", beginProgress)
APIRegistry.register("stepProgress", stepProgress)
APIRegistry.register("endProgress", endProgress)
