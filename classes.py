import os
import sys
import re
import glob
import json
import uuid
import xml.etree.ElementTree as ET
from .utils import copyJson

ModulesAPI = {} # updated at the end

if sys.version_info.major > 2:
    RigBuilderPath = os.path.dirname(__file__)
    RigBuilderLocalPath = os.path.expandvars("$USERPROFILE\\rigBuilder")
else:
    RigBuilderPath = os.path.dirname(__file__.decode(sys.getfilesystemencoding()))
    RigBuilderLocalPath = os.path.expandvars("$USERPROFILE\\rigBuilder").decode(sys.getfilesystemencoding())

def getUidFromFile(path):
    if path.endswith(".xml"):
        with open(path, "r") as f:
            l = f.readline() # read first line
        r = re.search("uid=\"(\\w*)\"", l)
        if r:
            return r.group(1)

def calculateRelativePath(path, root):
    path = os.path.normpath(path)
    path = path.replace(os.path.normpath(root)+"\\", "")
    return path

def categorizeFilesByModTime(files):
    from datetime import datetime, timedelta
    now = datetime.now()

    categories = {
        "Less 1 day ago": [],
        "Less 1 week ago": [],
        "Others": []
    }

    count = 0
    for file in files:
        mod_time = datetime.fromtimestamp(os.path.getmtime(file))
        time_diff = now - mod_time

        count += 1
        if time_diff <= timedelta(days=1):
            categories["Less 1 day ago"].append(file)
        elif time_diff <= timedelta(weeks=1):
            categories["Less 1 week ago"].append(file)
        else:
            categories["Others"].append(file)
            count -= 1

    return categories, count

class ExitModuleException(Exception):pass
class AttributeResolverError(Exception):pass
class AttributeExpressionError(Exception):pass
class ModuleNotFoundError(Exception):pass
class CopyJsonError(Exception):pass

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

    def copy(self):
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

    def name(self):
        return self._name
    
    def setName(self, name):
        if name != self._name:
            self._name = name
            self._modified = True
    
    def category(self):
        return self._category
    
    def setCategory(self, category):
        if category != self._category:
            self._category = category
            self._modified = True
    
    def template(self):
        return self._template
    
    def setTemplate(self, template):
        if template != self._template:
            self._template = template
            self._modified = True
    
    def connect(self):
        return self._connect
    
    def setConnect(self, connect):
        if connect != self._connect:
            self._connect = connect
            self._modified = True
    
    def expression(self):
        return self._expression
    
    def setExpression(self, expression):
        if expression != self._expression:
            self._expression = expression
            self._modified = True
    
    def modified(self):
        return self._modified
    
    def module(self):
        return self._module
    
    def _defaultValue(self):
        return copyJson(self._data[self._data["default"]])
    
    def _setDefaultValue(self, value):
        newValue = copyJson(value)
        if newValue != self._defaultValue():
            self._data[self._data["default"]] = newValue
            self._modified = True
    
    def data(self): # return actual read-only copy of all data
        self.pull()
        return copyJson(self._data)
    
    def localData(self):
        return copyJson(self._data)
    
    def setLocalData(self, data):
        newData = copyJson(data)
        if newData != self._data:
            self._data = newData
            self._modified = True
    
    def setData(self, data):
        self.setLocalData(data)
        self.push()

    def pull(self):
        if self._connect:
            srcAttr = self.findConnectionSource()
            if srcAttr:
                srcAttr.pull()
                srcAttr.executeExpression()
                self._setDefaultValue(srcAttr._defaultValue())

        self.executeExpression()

    def push(self):
        if self._connect:
            srcAttr = self.findConnectionSource()
            if srcAttr:
                srcAttr._setDefaultValue(self._defaultValue())            
                srcAttr.push()

    def get(self, key=None):
        self.pull()
        return self._defaultValue() if not key else copyJson(self._data.get(key))
        
    def set(self, value, key=None):
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
        if not self._expression:
            return
        
        localEnv = dict(self._module.getEnv())
        localEnv.update({"data": self._data, "value": self._defaultValue()})

        try:
            exec(self._expression, localEnv)
        except Exception as e:
            raise AttributeExpressionError("Invalid expression: {}".format(str(e)))
        else:
            self._setDefaultValue(localEnv["value"])

    def findConnectionSource(self):
        if self._module and self._module._parent and self._connect:
            srcAttr = self._module._parent.findAttributeByPath(self._connect)
            return srcAttr

    def listConnections(self):
        def _listConnections(currentModule):
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

    def toXml(self, *, keepConnection=True):
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
    def fromXml(root):
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

    def __getattr__(self, name):
        return self.get(name)

    def __setattr__(self, name, value):
        self[name] = value

class AttrsWrapper(object): # attributes getter/setter
    def __init__(self, module):
        self._module = module

    def __getattr__(self, name):
        module = object.__getattribute__(self, "_module")
        attr = module.findAttribute(name)
        if attr:
            return attr
        else:
            raise AttributeError("Attribute '{}' not found".format(name))

    def __setattr__(self, name, value): # for code like 'module.attr.input = value'
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
    def __init__(self, attr):
        self._attr = attr

    def __getitem__(self, name):
        return self._attr.get(name)

    def __setitem__(self, name, value):
        self._attr.set(value, name)

    def __str__(self):
        return json.dumps(self._attr.data())

class Module(object):
    UpdateSource = "all" # all, server, local, (empty)

    LocalUids = {}
    ServerUids = {}

    glob = Dict() # global memory
    env = {}

    def __init__(self, spec=None):
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

        if spec:
            self = Module.loadModule(spec)

    def copy(self):
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
    
    def name(self):
        return self._name
    
    def setName(self, name):
        self._name = name

    def uid(self):
        return self._uid
    
    def parent(self):
        return self._parent
    
    def filePath(self):
        return self._filePath
    
    def modified(self):
        return self._modified
    
    def muted(self):
        return self._muted

    def mute(self):
        self._muted = True

    def unmute(self):
        self._muted = False

    def runCode(self):
        return self._runCode
    
    def setRunCode(self, code):
        self._runCode = code
        self._modified = True

    def root(self):
        return self._parent.root() if self._parent else self

    def children(self):
        return list(self._children)

    def child(self, nameOrIndex):
        if type(nameOrIndex) == int:
            return self.children()[nameOrIndex]

        elif type(nameOrIndex) == str:
            return self.findChild(nameOrIndex)
            
    def insertChild(self, idx, child):
        child._parent = self
        self._children.insert(idx, child)
        self._modified = True

    def addChild(self, child):
        self.insertChild(len(self._children), child)

    def removeChild(self, child):
        child._parent = None
        self._children.remove(child)
        self._modified = True

    def removeChildren(self):
        for ch in self._children:
            ch._parent = None
        self._children = []
        self._modified = True

    def findChild(self, name):
        for ch in self._children:
            if ch._name == name:
                return ch

    def attributes(self):
        return list(self._attributes)

    def insertAttribute(self, idx, attr):
        attr._module = self
        self._attributes.insert(idx, attr)
        self._modified = True

    def addAttribute(self, attr):
        self.insertAttribute(len(self._attributes), attr)

    def removeAttribute(self, attr):
        attr._module = None
        self._attributes.remove(attr)
        self._modified = True

    def removeAttributes(self):
        for a in self._attributes:
            a._module = None
        self._attributes = []
        self._modified = True

    def findAttribute(self, name):
        for a in self._attributes:
            if a._name == name:
                return a
            
    def _clearModificationFlag(self, *, modules=True, attributes=True, recursive=True):
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
    
    def ch(self, path, key=None):
        attr = self.findAttributeByPath(path)
        return attr.get(key)
    
    def chdata(self, path):
        attr = self.findAttributeByPath(path)
        return attr.data() # actual read-only copy
    
    def chset(self, path, value, key=None):
        attr = self.findAttributeByPath(path)
        attr.set(value, key)       

    def toXml(self, *, keepConnections=True):
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
    def fromXml(root):
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

    def loadedFromServer(self):
        return self._filePath.startswith(os.path.normpath(RigBuilderPath+"/modules/"))

    def loadedFromLocal(self):
        return self._filePath.startswith(os.path.normpath(RigBuilderLocalPath+"/modules/"))

    def referenceFile(self):
        local = Module.LocalUids.get(self._uid)
        server = Module.ServerUids.get(self._uid)
        path = {"all": local or server, "server": server, "local": local, "":self._filePath}.get(Module.UpdateSource)
        return path

    def relativePath(self):
        if self.loadedFromServer():
            return calculateRelativePath(self._filePath, RigBuilderPath+"/modules")
        elif self.loadedFromLocal():
            return calculateRelativePath(self._filePath, RigBuilderLocalPath+"/modules")
        else:
            return self._filePath

    def relativePathString(self): # relative loaded path or ../folder/child/module.xml
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

    def getSavePath(self):
        if self.loadedFromServer():
            relativePath = os.path.relpath(self._filePath, RigBuilderPath+"/modules")
            return os.path.normpath(RigBuilderLocalPath+"/modules/"+relativePath)

        else: # local or somewhere else
            return self._filePath
        
    def embed(self):
        self._uid = ""
        self._filePath = ""
        self._modified = True

    def update(self):
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

    def sendToServer(self): # save the module on server, remove locally
        if self.loadedFromLocal():
            savePath = os.path.normpath(RigBuilderPath+"/modules/"+self.relativePath())
            if not os.path.exists(os.path.dirname(savePath)):
                os.makedirs(os.path.dirname(savePath))

            oldPath = self._filePath
            self.saveToFile(savePath)
            os.unlink(oldPath) # remove local file

            Module.ServerUids[self._uid] = savePath
            Module.LocalUids.pop(self._uid, None) # remove from local uids
            return savePath

    def saveToFile(self, fileName, *, newUid=False):
        if not self._uid or newUid:
            self._uid = uuid.uuid4().hex
        
        with open(os.path.realpath(fileName), "w") as f: # resolve links
            f.write(self.toXml(keepConnections=False)) # don't keep outer connections

        self._filePath = os.path.normpath(fileName)
        self._clearModificationFlag()

    @staticmethod
    def loadFromFile(fileName):
        m = Module.fromXml(ET.parse(fileName).getroot())
        m._filePath = os.path.normpath(fileName)
        m._muted = False
        return m

    @staticmethod
    def loadModule(spec): # spec can be full path, relative path or uid
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
    def listModules(path):
        files = []
        for f in sorted(glob.iglob(path+"/*")):
            if os.path.isdir(f):
                files += Module.listModules(f)
            else:
                if f.endswith(".xml"):
                    files.append(f)

        return files

    def path(self, inclusive=True):
        if not self._parent:
            return self._name
        return self._parent.path() + ("/" + self._name if inclusive else "")

    def findAttributeByPath(self, path):
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

    def getEnv(self):        
        env = dict(ModulesAPI)
        env.update({"module": self, 
                    "ch": self.ch, 
                    "chdata": self.chdata, 
                    "chset": self.chset})
        return env

    def run(self, *, uiCallback=None):
        localEnv = dict(Module.env or {})
        localEnv.update(self.getEnv())

        attrPrefix = "attr_"
        for attr in self._attributes:
            localEnv[attrPrefix+attr._name] = attr.get()
            localEnv[attrPrefix+"set_"+attr._name] = attr.set
            localEnv[attrPrefix+attr._name+"_data"] = DataAccessor(attr)

        print("{} is running...".format(self.path()))

        if callable(uiCallback):
            uiCallback(self)

        try:
            exec(self._runCode.replace("@", attrPrefix), localEnv)
        except ExitModuleException:
            pass

        for ch in self._children:
            if not ch.muted():
                ch.run(uiCallback=uiCallback)

        return localEnv

    @staticmethod
    def updateUidsCache():
        Module.ServerUids = Module.findUids(RigBuilderPath + "/modules")
        Module.LocalUids = Module.findUids(RigBuilderLocalPath + "/modules")

    @staticmethod
    def findUids(path):
        uids = {}

        for fpath in sorted(glob.iglob(path+"/*")):
            if os.path.isdir(fpath):
                dirUids = Module.findUids(fpath)
                for k in dirUids:
                    uids[k] = dirUids[k]

            elif fpath.endswith(".xml"):
                uid = getUidFromFile(fpath)
                if uid:
                    uids[uid] = fpath

        return uids

def printError(msg):
    raise RuntimeError(msg)

def printWarning(msg):
    print("Warning: "+msg)

def exitModule():
    raise ExitModuleException()

ModulesAPI.update({
    "module":None, # updated at runtime
    "Module": Module,
    "ch": None, # updated at runtime
    "chdata": None, # updated at runtime
    "chset": None, # updated at runtime
    "copyJson": copyJson,
    "exit": exitModule,
    "error": printError,
    "warning": printWarning})

Module.updateUidsCache()
