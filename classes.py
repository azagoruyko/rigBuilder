# -*- coding: utf-8 -*-

import os
import sys
import re
import glob
import json
import uuid
import traceback
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
            v = unicode(x)
    return v

def copyJson(data):
    if type(data) in [list, tuple]:
        return [copyJson(x) for x in data]

    elif type(data) == dict:
        return {k:copyJson(data[k]) for k in data}

    elif type(data) in [int, float, bool, str, unicode]:
        return data

    else:
        raise TypeError("Data of %s type is not JSON compatible: %s"%(type(data), str(data)))

class AttributeResolverError(Exception):
    pass

class CopyJsonError(Exception):
    pass

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
               self.template == other.template and\
               self.connect == other.connect

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

class Channel(object):
    def __init__(self, module, path):
        self.module, self.attr = module.findModuleAndAttributeByPath(path)
    
    def get(self):
        return self.attr.data[self.attr.data["default"]]

    def set(self, value):
        self.attr.data[self.attr.data["default"]] = value

class Module(object):
    AttributePrefix = "attr_"

    UpdateSource = "all" # all, server, local, (empty)

    LocalUids = {}
    ServerUids = {}

    def __init__(self, name):
        self.uid = "" # unique ids are assigned while saving

        self.name = name
        self.type = ""

        self.runCode = ""

        self.parent = None
        self._children = []
        self._attributes = []

        self.muted = False
        self.loadedFrom = ""

    def copy(self):
        module = Module(self.name)
        module.uid = self.uid
        module.type = self.type
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
               self.type == other.type and\
               self.runCode == other.runCode and\
               self.parent == other.parent and\
               all([a==b for a, b in zip(self._attributes, other._attributes)]) and\
               all([a==b for a, b in zip(self._children, other._children)])

    def clearChildren(self):
        self._children = []

    def getChildren(self):
        return self._children

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

    def toXml(self, keepConnections=True):
        attrs = [("name", self.name),
                 ("type", self.type),
                 ("muted", int(self.muted)),
                 ("uid", self.uid)]

        attrsStr = " ".join(["%s=\"%s\""%(k,v) for k, v in attrs])
        template = ["<module %s>"%attrsStr]

        template.append("".join(["<run>",
                                 "<![CDATA[", self.runCode, "]]>",
                                 "</run>"]))

        template.append("<attributes>")
        template += [a.toXml(keepConnections) for a in self._attributes]
        template.append("</attributes>")

        template.append("<children>")
        template += [ch.toXml(True) for ch in self._children] # keep connections for inner modules only
        template.append("</children>")

        template.append("</module>")

        return "\n".join(template)

    @staticmethod
    def fromXml(root):
        module = Module(root.attrib["name"])
        module.uid = root.attrib.get("uid", "")
        module.type = root.attrib["type"]
        module.muted = int(root.attrib["muted"])

        module.runCode = root.findtext("run")

        for ch in root.find("attributes").findall("attr"):
            module._attributes.append(Attribute.fromXml(ch))

        for ch in root.find("children").findall("module"):
            module.addChild(Module.fromXml(ch))

        return module

    def isLoadedFromServer(self):
        return self.loadedFrom.startswith(os.path.realpath(RigBuilderPath+"/modules/"))

    def isLoadedFromLocal(self):
        return self.loadedFrom.startswith(os.path.realpath(RigBuilderLocalPath+"/modules/"))

    def isReference(self):
        return True if self.getReferenceFile() else False

    def getReferenceFile(self):
        path = Module.LocalUids.get(self.uid) or Module.ServerUids.get(self.uid)
        if path and os.path.exists(path):
            return path

    def getSavePath(self):
        if self.isLoadedFromServer():
            relativePath = os.path.relpath(self.loadedFrom, RigBuilderPath+"/modules")
            return os.path.realpath(RigBuilderLocalPath+"/modules/"+relativePath)

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
                if foundAttr and foundAttr.template == origAttr.template: # use first found
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

            self.type = origModule.type
            self.runCode = origModule.runCode
            self.loadedFrom = origModule.loadedFrom

        for ch in self._children:
            ch.update()

    def saveToFile(self, fileName):
        if not self.uid:
            self.uid = generateUid()

        with open(fileName, "w") as f:
            f.write(self.toXml(False))

        self.loadedFrom = os.path.realpath(fileName)

    @staticmethod
    def loadFromFile(fileName):
        m = Module.fromXml(ET.parse(fileName).getroot())
        m.loadedFrom = os.path.realpath(fileName)
        return m

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

    def getPath(self):
        if self.parent:
            return self.parent.getPath() + "/" + self.name

        return self.name

    def findConnectionSourceForAttribute(self, attr):
        if self.parent and attr.connect:
            srcModule, srcAttr = self.parent.findModuleAndAttributeByPath(attr.connect)
            if srcAttr:
                return srcModule.findConnectionSourceForAttribute(srcAttr)

        return attr

    def findModuleAndAttributeByPath(self, path):
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

    def resolveConnections(self):
        for attr in self._attributes:
            if not attr.connect:
                continue

            srcAttr = self.findConnectionSourceForAttribute(attr)
            if srcAttr is not attr:
                if attr.template != srcAttr.template:
                    raise AttributeResolverError(self.name + ": '%s' has incompatible connection data"%attr.name)

                try:
                    attr.data = copyJson(srcAttr.data)
                except TypeError:
                    raise AttributeResolverError(self.name + ": '%s' data is not JSON serializable"%attr.name)

            else:
                raise AttributeResolverError(self.name + ": cannot resolve connection for '%s' which is '%s'"%(attr.name, attr.connect))

    def run(self, globalsEnv, uiCallback=None):

        def printer(msg):
            print(msg)

        def setter(attr, v):
            try:
                vcopy = copyJson(v)
            except TypeError:
                raise CopyJsonError("Cannot set non-JSON data using set_%s(%s)"%(attr.name, v))
            else:
                if attr.connect and self.parent:
                    srcAttr = self.findConnectionSourceForAttribute(attr)
                    default = srcAttr.data.get("default")

                    if default:
                        srcAttr.data[default] = vcopy
                    else:
                        srcAttr.data = vcopy

                else:
                    default = attr.data.get("default")

                    if default:
                        attr.data[default] = vcopy
                    else:
                        attr.data = vcopy

                return vcopy

        if self.muted:
            return

        self.resolveConnections()

        localsEnv = {"SHOULD_RUN_CHILDREN": True,
                     "MODULE_NAME": self.name,
                     "MODULE_TYPE": self.type,
                     "SELF": self,
                     "Channel": Channel,
                     "copyJson": copyJson,
                     "error": lambda x: printer("Error: " + x),
                     "warning": lambda x: printer("Warning: " + x)}

        for k in globalsEnv:
            localsEnv[k] = globalsEnv[k]

        for attr in self._attributes:
            default = attr.data.get("default")

            localsEnv[Module.AttributePrefix + attr.name] = copyJson(attr.data[default] if default else attr.data)
            localsEnv[Module.AttributePrefix + attr.name + "_data"] = attr.data
            localsEnv[Module.AttributePrefix + "set_" + attr.name] = lambda v, attr=attr: setter(attr, v)

        print("%s is running..."%self.getPath())

        if callable(uiCallback):
            uiCallback(self)

        exec(self.runCode.replace("@", Module.AttributePrefix), localsEnv)

        if localsEnv["SHOULD_RUN_CHILDREN"]:
            for ch in self._children:
                ch.run(globalsEnv, uiCallback)

        return localsEnv

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

Module.updateUidsCache()
