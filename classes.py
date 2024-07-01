import os
import sys
import re
import glob
import json
import uuid
import xml.etree.ElementTree as ET
from xml.sax.saxutils import escape, unescape

if sys.version_info.major > 2:
    RigBuilderPath = os.path.dirname(__file__)
    RigBuilderLocalPath = os.path.expandvars("$USERPROFILE\\rigBuilder")
else:
    RigBuilderPath = os.path.dirname(__file__.decode(sys.getfilesystemencoding()))
    RigBuilderLocalPath = os.path.expandvars("$USERPROFILE\\rigBuilder").decode(sys.getfilesystemencoding())

def generateUid():
    return uuid.uuid4().hex

def getUidFromFile(path):
    if path.endswith(".xml"):
        with open(path, "r") as f:
            l = f.readline() # read first line
        r = re.search("uid=\"(\\w*)\"", l)
        if r:
            return r.group(1)

def smartConversion(x):
    v = None
    try:
        v = int(x)
    except ValueError:
        try:
            v = float(x)
        except ValueError:
            v = str(x)
    return v

def copyJson(data):
    if data is None:
        return None

    elif type(data) in [list, tuple]:
        return [copyJson(x) for x in data]

    elif type(data) == dict:
        return {k:copyJson(data[k]) for k in data}

    elif type(data) in [int, float, bool, str]:
        return data

    elif sys.version_info.major < 3 and type(data) is unicode: # compatibility with python 2.7
        return data

    else:
        raise TypeError("Data of %s type is not JSON compatible: %s"%(type(data), str(data)))

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
class ModuleNotFoundError(Exception):pass
class CopyJsonError(Exception):pass

class Attribute(object):
    def __init__(self, name, data={}, category="", template="", connect=""):
        self.name = name
        self.data = copyJson(data) # as json
        self.category = category
        self.template = template
        self.connect = connect # attribute connection, format: /a/b/c, where c is attr, a/b is a parent relative path

    def copy(self):
        return Attribute(self.name, copyJson(self.data), self.category, self.template, self.connect)

    def __eq__(self, other):
        if not isinstance(other, Attribute):
            return False

        return self.name == other.name and\
               self.data == other.data and\
               self.category == other.category and\
               self.template == other.template # don't compare connections
    
    def hasDefault(self):
        return "default" in self.data
    
    def getDefaultValue(self):
        if self.hasDefault():
            return self.data[self.data["default"]]
    
    def setDefaultValue(self, v):
        if self.hasDefault():
            self.data[self.data["default"]] = v

    def updateFromAttribute(self, otherAttr):
        # copy default value if any
        if self.hasDefault() and otherAttr.hasDefault():
            self.setDefaultValue(copyJson(otherAttr.getDefaultValue()))
        else:
            self.data = copyJson(otherAttr.data)        

    def toXml(self, keepConnections=True):
        attrs = [("name", self.name),
                 ("template", self.template),
                 ("category", self.category),
                 ("connect", self.connect if keepConnections else "")]

        attrsStr = " ".join(["%s=\"%s\""%(k,v) for k, v in attrs])

        header = "<attr {attribs}><![CDATA[{data}]]></attr>"
        return header.format(attribs=attrsStr, data=json.dumps(self.data))

    @staticmethod
    def fromXml(root):
        attr = Attribute("")
        attr.name = root.attrib["name"]
        attr.template = root.attrib["template"]
        attr.category = root.attrib["category"]
        attr.connect = root.attrib["connect"]
        attr.data = json.loads(root.text.replace("__default__", "default")) # backward compatibility
        return attr

class Module(object):
    UpdateSource = "all" # all, server, local, (empty)

    LocalUids = {}
    ServerUids = {}

    def __init__(self, name):
        self.uid = "" # unique ids are assigned while saving

        self.name = name
        self.runCode = ""

        self.parent = None
        self._children = []
        self._attributes = []

        self.muted = False
        self.loadedFrom = ""

    def copy(self):
        module = Module(self.name)
        module.uid = self.uid
        module.runCode = self.runCode
        module._attributes = [a.copy() for a in self._attributes]

        for ch in self._children:
            module.addChild(ch.copy())

        module.parent = self.parent

        module.loadedFrom = self.loadedFrom
        module.muted = self.muted
        return module

    def __eq__(self, other):
        if not isinstance(other, Module):
            return False
        return self.uid == other.uid and\
               self.name == other.name and\
               self.runCode == other.runCode and\
               self.loadedFrom == other.loadedFrom

    def clearChildren(self):
        self._children = []

    def getChildren(self):
        return list(self._children)

    def addChild(self, child):
        self.insertChild(len(self._children), child)

    def insertChild(self, idx, child):
        child.parent = self
        self._children.insert(idx, child)

    def removeChild(self, child):
        child.parent = None
        self._children.remove(child)

    def findChild(self, name):
        for ch in self._children:
            if ch.name == name:
                return ch

    def getRoot(self):
        return self.parent.getRoot() if self.parent else self

    def clearAttributes(self):
        self._attributes = []

    def addAttribute(self, attr):
        self._attributes.append(attr)

    def getAttributes(self):
        return self._attributes

    def removeAttribute(self, attr):
        self._attributes = [a for a in self._attributes if a is not attr]

    def findAttribute(self, name):
        for a in self._attributes:
            if a.name == name:
                return a

    def toXml(self, *, keepConnections=True):
        attrs = [("name", self.name),
                 ("muted", int(self.muted)),
                 ("uid", self.uid)]

        attrsStr = " ".join(["%s=\"%s\""%(k,v) for k, v in attrs])
        template = ["<module %s>"%attrsStr]

        template.append("".join(["<run>",
                                 "<![CDATA[", self.runCode, "]]>",
                                 "</run>"]))

        template.append("<attributes>")
        template += [a.toXml(keepConnections=keepConnections) for a in self._attributes]
        template.append("</attributes>")

        template.append("<children>")
        template += [ch.toXml(keepConnections=True) for ch in self._children] # keep inner connections only
        template.append("</children>")

        template.append("</module>")

        return "\n".join(template)

    @staticmethod
    def fromXml(root):
        module = Module(root.attrib["name"])
        module.uid = root.attrib.get("uid", "")
        module.muted = int(root.attrib["muted"])

        module.runCode = root.findtext("run")

        for ch in root.find("attributes").findall("attr"):
            module._attributes.append(Attribute.fromXml(ch))

        for ch in root.find("children").findall("module"):
            module.addChild(Module.fromXml(ch))

        return module

    def isLoadedFromServer(self):
        return self.loadedFrom.startswith(os.path.normpath(RigBuilderPath+"/modules/"))

    def isLoadedFromLocal(self):
        return self.loadedFrom.startswith(os.path.normpath(RigBuilderLocalPath+"/modules/"))

    def isReference(self):
        return True if self.getReferenceFile() else False

    def getReferenceFile(self):
        path = Module.LocalUids.get(self.uid) or Module.ServerUids.get(self.uid)
        if path and os.path.exists(path):
            return path

    @staticmethod
    def calculateRelativePath(path, *, relativeTo="modules"):
        norm = os.path.normpath
        path = norm(path)
        path = path.replace(norm(RigBuilderLocalPath+"\\"+relativeTo)+"\\", "")
        path = path.replace(norm(RigBuilderPath+"\\"+relativeTo)+"\\", "")
        return path

    def getRelativeLoadedPathString(self): # relative loaded path or ../folder/child/module.xml
        if not self.loadedFrom:
            return ""

        path = ""
        if self.isLoadedFromServer() or self.isLoadedFromLocal():
            path = Module.calculateRelativePath(self.loadedFrom)
        else:
            normLoadedPath = self.loadedFrom.replace("\\", "/")
            items = normLoadedPath.split("/")
            MaxPathItems = 3
            if len(items) > MaxPathItems: # c: folder child module.xml
                path = "../"+"/".join(items[-MaxPathItems:])
            else:
                path = normLoadedPath

        return path.replace(".xml", "")

    def getSavePath(self):
        if self.isLoadedFromServer():
            relativePath = os.path.relpath(self.loadedFrom, RigBuilderPath+"/modules")
            return os.path.normpath(RigBuilderLocalPath+"/modules/"+relativePath)

        else: # local or somewhere else
            return self.loadedFrom

    def update(self):
        origPath = self.getReferenceFile() or self.loadedFrom
        if origPath:
            origModule = Module.loadFromFile(origPath)

            newAttributes = []

            # keep attribute values
            for origAttr in origModule._attributes:
                foundAttr = self.findAttribute(origAttr.name)
                if origAttr.name and foundAttr and foundAttr.template == origAttr.template: # skip empty named attrs, use first found
                    origDefaultKey = origAttr.data.get("default")

                    if origDefaultKey and origAttr.data.get(origDefaultKey) and foundAttr.data.get(origDefaultKey): # copy default value only
                        origAttr.data[origDefaultKey] = foundAttr.data[origDefaultKey]
                    else:
                        origAttr.data = foundAttr.data

                    origAttr.connect = foundAttr.connect

                newAttributes.append(origAttr)

            self._attributes = newAttributes

            self._children = []
            for ch in origModule._children:
                self.addChild(ch)

            self.runCode = origModule.runCode
            self.loadedFrom = origModule.loadedFrom

        for ch in self._children:
            ch.update()

    def sendToServer(self): # save the module on server, remove locally
        if self.isLoadedFromLocal():
            savePath = os.path.normpath(RigBuilderPath+"/modules/"+self.getRelativeLoadedPathString()+".xml")
            if not os.path.exists(os.path.dirname(savePath)):
                os.makedirs(os.path.dirname(savePath))

            oldPath = self.loadedFrom
            self.saveToFile(savePath)
            os.unlink(oldPath) # remove local file

            Module.ServerUids[self.uid] = savePath
            return savePath

    def saveToFile(self, fileName):
        if not self.uid:
            self.uid = generateUid()

        with open(os.path.realpath(fileName), "w") as f: # resolve links
            f.write(self.toXml(keepConnections=False)) # don't keep outer connections

        self.loadedFrom = os.path.normpath(fileName)

    @staticmethod
    def loadFromFile(fileName):
        m = Module.fromXml(ET.parse(fileName).getroot())
        m.loadedFrom = os.path.normpath(fileName)
        m.muted = False
        return m

    @staticmethod
    def loadModule(spec): # spec can be full path, relative path or uid
        modulePath = None

        if Module.LocalUids.get(spec): # check local uid
            modulePath = Module.LocalUids[spec]

        elif Module.ServerUids.get(spec): # check server uid
            modulePath = Module.ServerUids[spec]

        else:
            specPath = os.path.expandvars(spec)

            for path in [specPath,
                         specPath+".xml",
                         RigBuilderLocalPath+"/modules/"+spec,
                         RigBuilderLocalPath+"/modules/"+spec+".xml",
                         RigBuilderPath+"/modules/"+spec,
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

    def getPath(self, inclusive=True):
        if self.parent:
            return self.parent.getPath() + ("/" + self.name if inclusive else "")
        return self.name

    def listConnections(self, srcAttr):
        def _listConnections(currentModule):
            connections = []
            for ch in currentModule._children:
                if ch is self:
                    continue

                for attr in ch._attributes:
                    if attr.connect:
                        _, a = currentModule.findModuleAndAttributeByPath(attr.connect)
                        if a is srcAttr:
                            connections.append((ch, attr))

                connections += _listConnections(ch)
            return connections

        return _listConnections(self.getRoot())

    def findConnectionSourceForAttribute(self, attr):
        if self.parent and attr.connect:
            srcModule, srcAttr = self.parent.findModuleAndAttributeByPath(attr.connect)
            if srcAttr:
                return srcModule.findConnectionSourceForAttribute(srcAttr)

        return attr

    def findModuleAndAttributeByPath(self, path):
        '''
        Returns (module, attribute) by path, where path is /a/b/c, where c is attr, a/b is a parent relative path
        '''
        def parsePath(path):
            items = path.split("/")[1:] # /a/b/c => ["", a, b, c], skip ""
            return ([], items[0]) if len(items) == 1 else (items[:-1], items[-1])

        moduleList, attr = parsePath(path)

        currentParent = self
        for module in moduleList:
            found = currentParent.findChild(module)
            if found:
                currentParent = found
            else:
                return (None, None)

        found = currentParent.findAttribute(attr)
        return (currentParent, found) if found else (currentParent, None)

    def resolveConnection(self, attr):
        if not attr.connect:
            return
        
        srcAttr = self.findConnectionSourceForAttribute(attr)
        if srcAttr is not attr:
            if attr.template != srcAttr.template:
                raise AttributeResolverError("{}: '{}' has incompatible connection template".format(self.name, attr.name))

            try:
                attr.updateFromAttribute(srcAttr)

            except TypeError:
                raise AttributeResolverError("{}: '{}' data is not JSON serializable".format(self.name, attr.name))
            
        else:
            raise AttributeResolverError("{}: cannot resolve connection for '{}' which is '{}'".format(self.name, attr.name, attr.connect))

    def run(self, env, *, uiCallback=None):
        if self.muted:
            return

        localEnv = {
            "module": ModuleWrapper(self)
        }

        for k in env:
            if k not in localEnv: # don't overwrite locals
                localEnv[k] = env[k]

        ModuleWrapper.env = dict(env) # update environment for runtime modules

        attrPrefix = "attr_"
        for attr in self._attributes:
            self.resolveConnection(attr)

            attrWrapper = AttributeWrapper(self, attr)
            localEnv[attrPrefix+attr.name] = attrWrapper.get()
            localEnv[attrPrefix+"set_"+attr.name] = attrWrapper.set
            localEnv[attrPrefix+attr.name+"_data"] = attrWrapper.data()

        print("%s is running..."%self.getPath())

        if callable(uiCallback):
            uiCallback(self)

        try:
            exec(self.runCode.replace("@", attrPrefix), localEnv)
        except ExitModuleException:
            pass

        for ch in self._children:
            ch.run(env, uiCallback=uiCallback)

        return localEnv

    @staticmethod
    def updateUidsCache(updateSource=None):
        if updateSource is not None:
            Module.UpdateSource = updateSource

        Module.ServerUids = Module.findUids(RigBuilderPath + "/modules") if Module.UpdateSource in ["all", "server"] else {}
        Module.LocalUids = Module.findUids(RigBuilderLocalPath + "/modules") if Module.UpdateSource in ["all", "local"] else {}

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

# used inside modules in scripts
class Dict(dict):
    def __init__(self):
        pass

    def __getattr__(self, name):
        return self.get(name)

    def __setattr__(self, name, value):
        self[name] = value

class AttributeWrapper(object):
    def __init__(self, module, attr):
        self._attr = attr
        self._module = module

    def set(self, v):
        try:
            vcopy = copyJson(v)
        except TypeError:
            raise CopyJsonError("Cannot set non-JSON data for '{}' attribute (got {})".format(self._attr.name, v))

        srcAttr = self._attr
        if self._attr.connect and self._module.parent:
            srcAttr = self._module.findConnectionSourceForAttribute(self._attr)

        default = srcAttr.data.get("default")
        if default:
            srcAttr.data[default] = vcopy
        else:
            srcAttr.data = vcopy

    def get(self):
        default = self._attr.data.get("default")
        return copyJson(self._attr.data[default] if default else self._attr.data)

    def data(self):
        return self._attr.data

class AttrsWrapper(object): # attributes getter/setter
    def __init__(self, module):
        self._module = module

    def __getattr__(self, name):
        module = object.__getattribute__(self, "_module")
        attr = module.findAttribute(name)
        if attr:
            return AttributeWrapper(self._module, attr)
        else:
            raise AttributeError("Attribute '%s' not found"%name)

    def __setattr__(self, name, value):
        if name == "_module":
            object.__setattr__(self, "_module", value)
        else:
            module = object.__getattribute__(self, "_module")
            attr = module.findAttribute(name)
            if attr:
                AttributeWrapper(self._module, attr).set(value)
            else:
                raise AttributeError("Attribute '%s' not found"%name)

'''
How to use wrappers inside scripts.
module.attr.someAttr.set(10)
module.attr.someAttr = 5
module.parent().attr.someAttr.set(20)
print(@attr) # module.attr.attr.get()
@set_attr(30) # module.attr.attr.set(30)
'''
class ModuleWrapper(object):
    glob = Dict() # global memory
    env = {} # default environment for module scripts

    def __init__(self, specOrModule): # spec is path or module
        if isinstance(specOrModule, str):
            self._module = Module.loadModule(specOrModule)

        elif isinstance(specOrModule, Module):
            self._module = specOrModule

        self.attr = AttrsWrapper(self._module)

    def __eq__(self, other):
        if not isinstance(other, ModuleWrapper):
            return False
        return self._module == other._module

    def name(self):
        return self._module.name

    def child(self, nameOrIndex):
        if type(nameOrIndex) == int:
            return ModuleWrapper(self._module.getChildren()[nameOrIndex])

        elif type(nameOrIndex) == str:
            m = self._module.findChild(nameOrIndex)
            if m:
                return ModuleWrapper(m)
            else:
                raise ModuleNotFoundError("Child module '%s' not found"%nameOrIndex)

    def children(self):
        return [ModuleWrapper(ch) for ch in self._module.getChildren()]

    def parent(self):
        return ModuleWrapper(self._module.parent) if self._module.parent else None

    def muted(self):
        return self._module.muted
    
    def mute(self):
        self._module.muted = True

    def unmute(self):
        self._module.muted = False

    def path(self):
        return self._module.getPath()

    def run(self):
        muted = self._module.muted        
        self._module.muted = False
        try:
            self._module.run(ModuleWrapper.env)
        except:
            raise
        finally:            
            self._module.muted = muted

def getModuleDefaultEnv():
    def printError(msg):
        raise RuntimeError(msg)

    def printWarning(msg):
        print("Warning: "+msg)

    def exitModule():
        raise ExitModuleException()

    env = {"module":None, # setup in Module.run
           "Module": ModuleWrapper,
           "copyJson": copyJson,
           "exit": exitModule,
           "error": printError,
           "warning": printWarning}

    return env

Module.updateUidsCache()
