from __future__ import annotations
import json
import time
import re
import os
import subprocess
import inspect
import sys
import shutil
import logging
import textwrap
import xml.etree.ElementTree as ET
from functools import partial
from typing import Callable, Optional, List, Tuple, Union, Any, TYPE_CHECKING

from .. import __version__
from ..core import workspace
from ..ai.engine import isOllamaAvailable
from .hostExecutor import hostExecutor
from ..core import *
from ..core.connectionManager import connectionManager
from ..core.uidManager import UidManager
from ..core.logger import logger, logHandler, setupStreamRedirection, setupExcepthook
from .qt import *
from ..host.servers import AVAILABLE_HOSTS, HOST_STARTUP_TEMPLATE
from ..core.settings import settings, RIG_BUILDER_PATH, RIG_BUILDER_USER_PATH
from ..core.utils import *
from ..core.widgets import getAttributeFromValue, DEFAULT_WIDGETS_DATA
from .widgets import TemplateWidgets, EditTextDialog, EditJsonDialog, TemplateWidget
from ..core.workspace import Workspace
from .aichat import AIChatDialog
from .apiBrowser import ApiBrowser
from .diffBrowser import DiffBrowserDialog, calculateModulesDiff, DiffBrowserDialogWithConfirm
from .docBrowser import DocBrowser, DocGeneratorWorker, activeWorkers
from .editor import CodeEditorWithNumbersWidget
from .fileTracker import DirectoryWatcher
from .moduleBrowser import ModuleBrowser
from .moduleHistoryBrowser import ModuleHistoryBrowser
from .utils import *
from .widgetPresetManager import WidgetPresetManager, PresetEditorDialog
from .workspaceManager import WorkspaceWidget, getWorkspace

undoStack = QUndoStack()


class AttributeFormLabel(QLabel):
    def __init__(self, attr: Attribute, row: int, parent: AttributesGroupWidget):
        super().__init__(attr.name(), parent)
        self.parentView = parent
        self.row = row
        self.attr = attr
        self.dragStartPosition = None

        self.setStyleSheet("QLabel { margin-left: 15px; }")
        self.setContextMenuPolicy(Qt.CustomContextMenu)        
        self.setCursor(Qt.OpenHandCursor)

    def mousePressEvent(self, event):
        if event.button() == Qt.MiddleButton:
            self.dragStartPosition = event.position().toPoint()
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if not (event.buttons() & Qt.MiddleButton):
            return
        if self.dragStartPosition is None:
            return
        if (event.position().toPoint() - self.dragStartPosition).manhattanLength() < QApplication.startDragDistance():
            return

        drag = QDrag(self)
        mimeData = QMimeData()
        mimeData.setData("application/x-rigbuilder-attr-row", str(self.row).encode("utf-8"))
        drag.setMimeData(mimeData)

        # Draw a visual feedback of the label
        pixmap = self.grab()
        drag.setPixmap(pixmap)
        drag.setHotSpot(event.position().toPoint())

        self.parentView.startDrag(self.row)
        drag.exec(Qt.MoveAction)
        self.parentView.endDrag()

    def mouseDoubleClickEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.parentView.onLabelDoubleClicked(self.attr, event)
            event.accept()
        else:
            super().mouseDoubleClickEvent(event)

def updateTemplateWidgetStyle(widget: TemplateWidget):
    style = ""
    tooltip = []
    if widget.attr.connect():
        tooltip.append("Connect: " + widget.attr.connect())
    if widget.attr.expression():
        tooltip.append("Expression:\n" + widget.attr.expression())

    if widget.attr.connect() and not widget.attr.expression():
        style = "TemplateWidget { padding: 2px; border: 1px solid rgba(210, 175, 0, 0.7); border-radius: 4px; }"
    elif widget.attr.expression() and not widget.attr.connect():
        style = "TemplateWidget { padding: 2px; border: 1px solid rgba(123, 104, 238, 0.8); border-radius: 4px; }"
    elif widget.attr.expression() and widget.attr.connect():
        style = "TemplateWidget { padding: 2px; border: 1px solid rgba(180, 50, 180, 0.7); border-radius: 4px; }"

    widget.setStyleSheet(style)
    widget.setToolTip("\n".join(tooltip))

class AttributesGroupWidget(QWidget):
    Clipboard = None
    moduleChanged = Signal(object)
    moduleCodeExecutionRequested = Signal(str)

    def __init__(self, tabWidget: AttributesTabWidget, category: str, parent=None):
        super().__init__(parent)
        self.tabWidget = tabWidget
        self.category = category
        self._widgets = {} # maps attr -> (label_widget, template_widget)
        self._dragging = False
        self._dropRow = -1

        self.mainLayout = QVBoxLayout(self)
        self.mainLayout.setContentsMargins(0, 0, 0, 0)
        
        self.layout = QFormLayout()
        self.layout.setContentsMargins(0, 10, 0, 10)
        self.layout.setSpacing(10)
        self.layout.setLabelAlignment(Qt.AlignRight | Qt.AlignVCenter)
        
        self.mainLayout.addLayout(self.layout)
        self.mainLayout.addStretch()
        
        self.setAcceptDrops(True)

    def module(self) -> Module:
        return self.tabWidget.module    

    def paintEvent(self, event):
        super().paintEvent(event)
        if self._dropRow != -1:
            painter = QPainter(self)
            rowCount = self.layout.rowCount()
            if rowCount == 0:
                painter.end()
                return
                
            y = 0
            if self._dropRow < rowCount:
                lblItem = self.layout.itemAt(self._dropRow, QFormLayout.LabelRole)
                lbl = lblItem.widget() if lblItem else None
                if lbl:
                    y = lbl.y() - 5
            else:
                lblItem = self.layout.itemAt(rowCount - 1, QFormLayout.LabelRole)
                lbl = lblItem.widget() if lblItem else None
                if lbl:
                    y = lbl.y() + lbl.height() + 5
                    
            if y > 0:
                pen = QPen(QColor("#8a95a5"), 2)
                painter.setPen(pen)
                painter.setBrush(QBrush(QColor("#8a95a5")))
                painter.drawEllipse(5, y - 4, 8, 8)
                painter.drawLine(13, y, self.width(), y)
            painter.end()

    def updateAttributes(self):
        if self._dragging:
            return

        for label, widget in self._widgets.values():
            label.deleteLater()
            widget.deleteLater()
        self._widgets.clear()

        while self.layout.rowCount() > 0:
            self.layout.takeRow(0)

        if not self.module():
            return

        currentAttrs = [a for a in self.module().attributes() if a.category() == self.category]
        for row, attr in enumerate(currentAttrs):
            label, templateWidget = self.createAttributeWidgets(attr, row)
            self._widgets[attr] = (label, templateWidget)
            self.layout.addRow(label, templateWidget)

    def createAttributeWidgets(self, attr, row):
        label = AttributeFormLabel(attr, row, self)
        label.customContextMenuRequested.connect(partial(self.showAttributeContextMenu, attr, label))

        templateWidget = TemplateWidgets[attr.template()]()
        templateWidget.attr = attr
        templateWidget.templateWidget = templateWidget

        try:
            templateWidget.setJsonData(attr.data())
        except Exception as e:
            logger.error(f"{attr.module().name()}.{attr.name()}: {str(e)}")

        updateTemplateWidgetStyle(templateWidget)

        templateWidget.somethingChanged.connect(partial(self.onWidgetChanged, templateWidget))
        templateWidget.moduleCodeExecutionRequested.connect(self.moduleCodeExecutionRequested.emit)

        return label, templateWidget

    def onWidgetChanged(self, widget: TemplateWidget):
        try:
            self.updateAttributeFromTemplateWidget(widget)
        except Exception as e:
            logger.error(f"{widget.attr.module().name()}.{widget.attr.name()}: {str(e)}")

    def updateAttributeFromTemplateWidget(self, widget: TemplateWidget):
        widgetData = widget.getJsonData()
        if widget.attr.localData() == widgetData:
            return

        widget.attr.setData(widgetData)

        module = widget.attr.module()

        previousData = {id(a): a.localData() for a in module.attributes()}
        modifiedAttrs = set()
        for otherAttr in module.attributes():
            otherAttr.pull()

            if otherAttr.localData() != previousData[id(otherAttr)]:
                modifiedAttrs.add(otherAttr)

        if modifiedAttrs:
            self.moduleChanged.emit(module)

        for otherAttr, (_, otherWidget) in self._widgets.items():  # update widgets whose data changed
            if otherAttr in modifiedAttrs:
                otherWidget.setJsonData(otherAttr.data())

    def onLabelDoubleClicked(self, attr, event):
        if event.button() == Qt.LeftButton:
            newName, ok = QInputDialog.getText(self, "Rename Attribute", "New name:", QLineEdit.Normal, attr.name())
            if ok:
                newName = replaceSpecialChars(newName.strip())
                if newName != attr.name():
                    uniqueName = findUniqueName(newName, [a.name() for a in attr.module().attributes()])
                    
                    newAttr = attr.copy()
                    newAttr.setName(uniqueName)
                    
                    undoStack.push(EditAttributeCommand(
                        self.tabWidget, 
                        attr, 
                        attr.toXml(keepConnection=True), 
                        newAttr.toXml(keepConnection=True), 
                        f"Rename '{attr.name()}' to '{uniqueName}'"
                    ))

    def startDrag(self, row):
        self._dragging = True
        self._dragRow = row
        
        lblItem = self.layout.itemAt(row, QFormLayout.LabelRole)
        fldItem = self.layout.itemAt(row, QFormLayout.FieldRole)
        self._draggedLabel = lblItem.widget() if lblItem else None
        self._draggedField = fldItem.widget() if fldItem else None
        
        if self._draggedLabel:
            self._draggedLabel.setStyleSheet("QLabel { color: #3e7bd6; font-weight: bold; margin-left: 15px; }")
            
        if self._draggedField:
            opacityEffect = QGraphicsOpacityEffect(self._draggedField)
            opacityEffect.setOpacity(0.5)
            self._draggedField.setGraphicsEffect(opacityEffect)

    def dragEnterEvent(self, event: QDragEnterEvent):
        if event.mimeData().hasFormat("application/x-rigbuilder-attr-row"):
            event.acceptProposedAction()

    def dragMoveEvent(self, event: QDragMoveEvent):
        if event.mimeData().hasFormat("application/x-rigbuilder-attr-row"):
            localPos = event.position().toPoint()
            dropRow = self.dropRowAtY(localPos.y())
            if dropRow != -1 and dropRow != self._dropRow:
                self._dropRow = dropRow
                self.update()
            event.acceptProposedAction()

    def dropEvent(self, event: QDropEvent):
        if event.mimeData().hasFormat("application/x-rigbuilder-attr-row"):
            try:
                sourceRow = int(event.mimeData().data("application/x-rigbuilder-attr-row").data().decode("utf-8"))
            except (ValueError, UnicodeDecodeError):
                return
            
            targetRow = self._dropRow
            self._dropRow = -1
            self.update()
            
            # Clear dragging flags and styles before triggering refresh
            self._dragging = False
            self.endDrag()
            
            if targetRow != -1 and targetRow != sourceRow and targetRow != sourceRow + 1:
                initialOrder = self.module().attributes()[:]
                currentAttrs = [a for a in self.module().attributes() if a.category() == self.category]
                
                srcAttr = currentAttrs[sourceRow]
                srcIndexInModule = initialOrder.index(srcAttr)
                
                adjustedTargetRow = targetRow - 1 if targetRow > sourceRow else targetRow
                targetAttr = currentAttrs[adjustedTargetRow]
                
                finalOrder = initialOrder[:]
                finalOrder.pop(srcIndexInModule)
                
                targetIndexInNewOrder = finalOrder.index(targetAttr)
                insertIndex = targetIndexInNewOrder + 1 if targetRow > sourceRow else targetIndexInNewOrder
                
                finalOrder.insert(insertIndex, srcAttr)
                
                if initialOrder != finalOrder:
                    undoStack.push(MoveAttributesCommand(self.tabWidget, self.module(), initialOrder, finalOrder))
                else:
                    self.updateAttributes()
            else:
                self.updateAttributes()

            event.acceptProposedAction()

    def dragLeaveEvent(self, event: QDragLeaveEvent):
        self._dropRow = -1
        self.update()

    def endDrag(self):
        self._dragging = False
        
        if self._draggedLabel:
            self._draggedLabel.setStyleSheet("QLabel { margin-left: 15px; }")
            
        if self._draggedField:
            self._draggedField.setGraphicsEffect(None)

    def dropRowAtY(self, y: int) -> int:
        rowCount = self.layout.rowCount()
        for r in range(rowCount):
            item = self.layout.itemAt(r, QFormLayout.LabelRole)
            w = item.widget() if item else None
            if w and y < w.y() + w.height() / 2:
                return r
        return rowCount

    def showAttributeContextMenu(self, attr, label, pos):
        globalPos = label.mapToGlobal(pos)
        menu = QMenu()
        titleAction = menu.addAction(f"📝 {attr.name() or '(Unnamed)'}")
        titleAction.setEnabled(False)
        menu.addSeparator()

        if attr.module() and attr.module().parent():
            makeConnectionMenu = menu.addMenu("Connect")
            for a in attr.module().parent().attributes():
                if a.template() == attr.template() and a.name():
                    makeConnectionMenu.addAction(a.name(), partial(self.connectAttr, attr, "/"+a.name()))

            for ch in attr.module().parent().children():
                if ch is not attr.module():
                    self.connectionMenu(makeConnectionMenu, attr, ch)

        if attr.connect():
            menu.addAction("Break connection", partial(self.disconnectAttr, attr))

        menu.addSeparator()
        menu.addAction("Edit data", partial(self.editData, attr, self._widgets[attr][1]))
        menu.addSeparator()
        menu.addAction("Edit expression", partial(self.editExpression, attr, self._widgets[attr][1]))

        if attr.expression():
            def evaluateExpression():
                w = self._widgets[attr][1]
                with blockedWidgetContext(w) as widget:
                    widget.setJsonData(attr.data())

            menu.addAction("Evaluate expression", evaluateExpression)
            menu.addAction("Clear expression", partial(self.clearExpression, attr))

        menu.addAction("Reset", partial(self.resetAttr, attr))
        menu.addAction("Expose", partial(self.exposeAttr, attr))

        presetsMenu = menu.addMenu("Presets")
        presetsMenu.addAction("Manage Presets...", lambda: PresetEditorDialog(parent=self).exec())
        presetsMenu.addAction("Save as Preset...", partial(self.saveAsPreset, attr))
        
        presets = WidgetPresetManager.presets()
        compatiblePresets = {name: data for name, data in presets.items() if data.get("template") == attr.template()}
        if compatiblePresets:
            presetsMenu.addSeparator()
            for name, data in sorted(compatiblePresets.items()):
                presetsMenu.addAction(name, partial(self.applyPreset, attr, self._widgets[attr][1], data["data"]))

        menu.addSeparator()

        moveToMenu = menu.addMenu("Move To")
        moveToMenu.addAction("New Tab", partial(self.moveAttrToNewTab, attr))
        moveToMenu.addSeparator()
        
        categories = []
        for a in attr.module().attributes():
            if a.category() not in categories:
                categories.append(a.category())
            
        for tabName in categories:
            if tabName != attr.category():
                moveToMenu.addAction(tabName, partial(self.moveAttrToCategory, attr, tabName))

        menu.addAction("Copy", partial(self.copyAttribute, attr))
        menu.addAction("Cut", partial(self.cutAttribute, attr))
        menu.addAction("Remove", partial(self.removeAttribute, attr))

        menu.exec(globalPos)

    def connectionMenu(self, menu: QMenu, attr, module: Module, path: str = "/"):
        subMenu = QMenu(module.name(), self)

        for a in module.attributes():
            if a.template() == attr.template() and a.name():
                subMenu.addAction(a.name(), partial(self.connectAttr, attr, path+module.name()+"/"+a.name()))

        for ch in module.children():
            self.connectionMenu(subMenu, attr, ch, path+module.name()+"/")

        if subMenu.actions():
            menu.addMenu(subMenu)

    def connectAttr(self, attr, connect: str):
        newAttr = attr.copy()
        newAttr.setConnect(connect)
        undoStack.push(EditAttributeCommand(
            self.tabWidget, 
            attr, 
            attr.toXml(keepConnection=True), 
            newAttr.toXml(keepConnection=True), 
            f"Connect '{attr.name()}'"
        ))

    def disconnectAttr(self, attr):
        newAttr = attr.copy()
        newAttr.setConnect("")
        undoStack.push(EditAttributeCommand(
            self.tabWidget, 
            attr, 
            attr.toXml(keepConnection=True), 
            newAttr.toXml(keepConnection=True), 
            f"Disconnect '{attr.name()}'"
        ))

    def clearExpression(self, attr):
        newAttr = attr.copy()
        newAttr.setExpression("")
        undoStack.push(EditAttributeCommand(
            self.tabWidget, 
            attr, 
            attr.toXml(keepConnection=True), 
            newAttr.toXml(keepConnection=True), 
            f"Clear expression '{attr.name()}'"
        ))

    def resetAttr(self, attr):
        newAttr = attr.copy()
        newAttr.setConnect("")
        newAttr.setData(copyJson(DEFAULT_WIDGETS_DATA[attr.template()]))
        undoStack.push(EditAttributeCommand(
            self.tabWidget, 
            attr, 
            attr.toXml(keepConnection=True), 
            newAttr.toXml(keepConnection=True), 
            f"Reset '{attr.name()}'"
        ))

    def exposeAttr(self, attr):
        parentModule = attr.module().parent()

        if parentModule == attr.module().root():
            QMessageBox.warning(self, "Rig Builder", "Can't expose attribute to parent: no parent module")
            return

        doUsePrefix = QMessageBox.question(self, "Rig Builder", "Use prefix for the exposed attribute name?", QMessageBox.Yes | QMessageBox.No, QMessageBox.Yes) == QMessageBox.Yes
        prefix = attr.module().name() + "_" if doUsePrefix else ""

        newName = prefix + attr.name()
        if parentModule.findAttribute(newName):
            QMessageBox.warning(self, "Rig Builder", "Can't expose attribute to parent: attribute with name '{}' already exists".format(newName))
            return

        expAttr = attr.copy()
        parentModule.addAttribute(expAttr)
        expAttr.setName(newName)
        self.connectAttr(attr, "/"+expAttr.name())
        self.tabWidget.moduleChanged.emit(parentModule)

    def editData(self, attr, templateWidget):
        templateWidget.attr = attr
        templateWidget.templateWidget = templateWidget

        def save(w, data):
            newAttr = w.attr.copy()
            newAttr.setLocalData(data[0])
            undoStack.push(EditAttributeCommand(
                self.tabWidget, 
                w.attr, 
                w.attr.toXml(keepConnection=True), 
                newAttr.toXml(keepConnection=True), 
                f"Edit data '{w.attr.name()}'"
            ))

        w = EditJsonDialog(attr.localData(), title="Edit data", parent=self)
        w.saved.connect(partial(save, templateWidget))
        w.show()

    def editExpression(self, attr, templateWidget):
        def save(text: str):
            newAttr = attr.copy()
            newAttr.setExpression(text)
            undoStack.push(EditAttributeCommand(
                self.tabWidget, 
                attr, 
                attr.toXml(keepConnection=True), 
                newAttr.toXml(keepConnection=True), 
                f"Edit expression '{attr.name()}'"
            ))

        if not attr.module():
            return

        w = EditTextDialog(
            attr.expression(), 
            title="Edit expression for '{}'".format(attr.name()), 
            placeholder='# Example: value = ch("../someAttr") + 1 or data["items"] = [1,2,3]', 
            words=set(attr.module().context().keys()), 
            python=True,
            parent=self)

        w.saved.connect(save)
        w.show()

    def saveAsPreset(self, attr):
        name, ok = QInputDialog.getText(self, "Save Preset", "Preset name:", QLineEdit.Normal, attr.name())
        if ok and name:
            WidgetPresetManager.savePreset(name, attr.template(), attr.localData())

    def applyPreset(self, attr, templateWidget, data: dict):
        attr.setData(data)
        with blockedWidgetContext(templateWidget) as w:
            w.setJsonData(attr.data())

    def copyAttribute(self, attr):
        AttributesGroupWidget.Clipboard = attr.copy()

    def cutAttribute(self, attr):
        AttributesGroupWidget.Clipboard = attr.copy()
        undoStack.push(RemoveAttributeCommand(self.tabWidget, attr))

    def removeAttribute(self, attr):
        if QMessageBox.question(self, "Rig Builder", f"Remove '{attr.name()}' attribute?", QMessageBox.Yes | QMessageBox.No, QMessageBox.Yes) == QMessageBox.Yes:
            undoStack.push(RemoveAttributeCommand(self.tabWidget, attr))

    def moveAttrToCategory(self, attr, category: str):
        newAttr = attr.copy()
        newAttr.setCategory(category)
        undoStack.push(EditAttributeCommand(
            self.tabWidget,
            attr,
            attr.toXml(keepConnection=True),
            newAttr.toXml(keepConnection=True),
            f"Move '{attr.name()}' to '{category}'"
        ))

    def moveAttrToNewTab(self, attr):
        existingTabs = [self.tabWidget.tabText(i) for i in range(self.tabWidget.count())]
        self.moveAttrToCategory(attr, findUniqueName("NewTab", existingTabs))


class AttributesTabWidget(QTabWidget):
    moduleChanged = Signal(object) # Module
    moduleCodeExecutionRequested = Signal(str)

    def __init__(self, **kwargs):
        super().__init__(**kwargs)

        self.module = None

        self.setMovable(True)
        self.tabBar().setCursor(Qt.PointingHandCursor)
        self.tabBar().setContextMenuPolicy(Qt.CustomContextMenu)
        self.tabBar().customContextMenuRequested.connect(self._onTabContextMenu)
        self.tabBar().tabMoved.connect(self._onTabMoved)
        self.tabBar().tabBarDoubleClicked.connect(self._onRenameTab)

        self.searchAndReplaceDialog = SearchReplaceDialog(["In all tabs"], parent=self)
        self.searchAndReplaceDialog.onReplace.connect(self._onReplace)

        self.currentChanged.connect(self._onCurrentChanged)

    def _onCurrentChanged(self, idx):
        if idx == -1:
            return

        w = self.widget(idx)
        w.widget().updateAttributes()

    def _onTabContextMenu(self, pos: QPoint):
        idx = self.tabBar().tabAt(pos)
        menu = QMenu(self)
        
        menu.addAction("New", self._onNewTab)
        if idx != -1:
            menu.addSeparator()
            menu.addAction("Remove", partial(self._onRemoveTab, idx))
            
        menu.popup(self.tabBar().mapToGlobal(pos))

    def _onNewTab(self):
        name, ok = QInputDialog.getText(self, "Rig Builder", "New tab name:", QLineEdit.Normal, "NewTab")
        if ok and name:
            existingTabs = [self.tabText(i) for i in range(self.count())]
            uniqueName = findUniqueName(name, existingTabs)

            scroll = self.makeTabWidget(uniqueName)
            self.addTab(scroll, uniqueName)
            self.setCurrentIndex(self.count() - 1)        

    def _onRenameTab(self, idx: int):
        oldName = self.tabText(idx)
        newName, ok = QInputDialog.getText(self, "Rig Builder", "New name", QLineEdit.Normal, oldName)
        if ok and newName:
            newName = replaceSpecialChars(newName)
            
            if newName == oldName:
                return
                
            existingTabs = [self.tabText(i) for i in range(self.count())]
            uniqueName = findUniqueName(newName, existingTabs)

            undoStack.beginMacro(f"Rename Tab '{oldName}'")
            for a in self.module.attributes():
                if a.category() == oldName:
                    newAttr = a.copy()
                    newAttr.setCategory(uniqueName)
                    undoStack.push(EditAttributeCommand(
                        self, 
                        a, 
                        a.toXml(keepConnection=True), 
                        newAttr.toXml(keepConnection=True), 
                        f"Move attribute '{a.name()}' to '{uniqueName}'"
                    ))
            undoStack.endMacro()

    def _onRemoveTab(self, idx: int):
        if QMessageBox.question(self, "Rig Builder", f"Remove '{self.tabText(idx)}' tab?", QMessageBox.Yes | QMessageBox.No, QMessageBox.Yes) == QMessageBox.Yes:
            category = self.tabText(idx)
            toRemove = [a for a in self.module.attributes() if a.category() == category]
            
            undoStack.beginMacro(f"Remove Tab '{category}'")
            for a in toRemove:
                undoStack.push(RemoveAttributeCommand(self, a))
            undoStack.endMacro()

    def _onTabMoved(self, from_idx: int, to_idx: int):
        visualCategories = [self.tabText(i) for i in range(self.count())]
        newAttrs = []
        for cat in visualCategories:
            newAttrs.extend([a for a in self.module.attributes() if a.category() == cat])
        for a in self.module.attributes():
            if a not in newAttrs:
                newAttrs.append(a)

        oldOrder = self.module.attributes()
        undoStack.push(MoveAttributesCommand(self, self.module, oldOrder, newAttrs))

    def contextMenuEvent(self, event: QContextMenuEvent):
        menu = QMenu(self)

        if self.module:
            addAttrMenu = menu.addMenu("Add attribute")
            addAttrMenu.addAction("Browse...", self.addTemplateAttribute)
            addAttrMenu.addSeparator()
            for templateName in sorted(TemplateWidgets.keys()):
                addAttrMenu.addAction(templateName, partial(self._onQuickAddAttribute, templateName))

            if AttributesGroupWidget.Clipboard:
                menu.addAction(f"Paste attribute ({AttributesGroupWidget.Clipboard.template()})", self._onPasteAttribute)

            menu.addSeparator()
            menu.addAction("Replace in values", self.searchAndReplaceDialog.exec)

        menu.popup(event.globalPos())

    def _onPasteAttribute(self):
        if not AttributesGroupWidget.Clipboard:
            return
            
        newAttr = AttributesGroupWidget.Clipboard.copy()
        newAttr.setCategory(self.tabText(self.currentIndex()))
        
        newName = newAttr.name()
        if newName:
            newName = findUniqueName(newAttr.name(), [a.name() for a in self.module.attributes()])
        newAttr.setName(newName)
        
        undoStack.push(AddAttributeCommand(self, self.module, newAttr))

    def addTemplateAttribute(self):
        selector = TemplateSelectorDialog(parent=self)
        selector.selectedTemplate.connect(self._onQuickAddAttribute)
        selector.exec()

    def _onQuickAddAttribute(self, template: str):
        name = findUniqueName("attr", [a.name() for a in self.module.attributes()])

        category = self.tabText(self.currentIndex()) if self.count() > 0 else "General"
        newAttr = Attribute(name=name, template=template, category=category)
        
        if template in DEFAULT_WIDGETS_DATA:
            newAttr.setData(copyJson(DEFAULT_WIDGETS_DATA[template]))

        undoStack.push(AddAttributeCommand(self, self.module, newAttr))

    def _onReplace(self, old: str, new: str, opts: dict[str, bool]):
        def replaceStringInData(data: object, old: str, new: str) -> object:
            try:
                return json.loads(json.dumps(data).replace(old,new))
            except ValueError:
                return data

        if opts.get("In all tabs"):
            attributes = self.module.attributes()
        else:
            category = self.tabText(self.currentIndex())
            attributes = [a for a in self.module.attributes() if a.category() == category]

        undoStack.beginMacro("Search and Replace in values")

        for attr in attributes:
            v = replaceStringInData(attr.get(), old, new)
            if v != attr.get():
                newAttr = attr.copy()
                newAttr.set(v)
                undoStack.push(EditAttributeCommand(self, attr, attr.toXml(keepConnection=True), newAttr.toXml(keepConnection=True), f"Replace in '{attr.name()}'"))
        undoStack.endMacro()

    def updateTabs(self):
        categories = []
        if self.module:
            for a in self.module.attributes():
                if a.category() not in categories:
                    categories.append(a.category())

        currentTabText = self.tabText(self.currentIndex())

        # Clear existing tabs
        while self.count():
            w = self.widget(0)
            self.removeTab(0)
            w.deleteLater()

        if not self.module:
            return

        for cat in categories:
            w = self.makeTabWidget(cat)
            self.addTab(w, cat)

        # Restore current tab index
        for i in range(self.count()):
            if self.tabText(i) == currentTabText:
                self.setCurrentIndex(i)
                break

    def makeTabWidget(self, cat: str) -> QWidget:
        widget = AttributesGroupWidget(self, cat)
        widget.moduleChanged.connect(self.moduleChanged.emit)
        widget.moduleCodeExecutionRequested.connect(self.moduleCodeExecutionRequested.emit)
        
        scroll = QScrollArea(self)
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setWidget(widget)
        return scroll

class ModuleTracker(QObject):
    """
    Handles tracking of module files on disk.
    Loads and caches original module definitions by UID and monitors file changes.
    """
    moduleChanged = Signal(str) # uid

    def __init__(self, parent: Optional[QObject] = None):
        super().__init__(parent)
        self._cache: dict[str, Module] = {}
        self._watcher = QFileSystemWatcher(self)
        self._watcher.fileChanged.connect(self._onFileChanged)

    def getModule(self, uid: str) -> Optional[Module]:
        """Get the cached reference module by UID, loading it if necessary."""
        if not uid:
            return None
            
        if uid not in self._cache:
            self.loadModule(uid)
            
        return self._cache.get(uid)

    def loadModule(self, uid: str):
        """Load module from disk and add its file to the watcher."""
        path = UidManager.resolve(uid)
        if not path or not os.path.exists(path):
            self._cache[uid] = None
            return

        try:
            # Get the module from disk (synced)
            refModule = Module.loadModule(path)
            self._cache[uid] = refModule
            
            # Start watching the file for changes if not already watched
            if path not in self._watcher.files():
                self._watcher.addPath(path)
                
        except Exception as e:
            mainWindow.logger.error(f"ModuleTracker: Failed to load module for {uid}: {str(e)}")
            self._cache[uid] = None

    def _onFileChanged(self, path: str):
        """Handle file change event from QFileSystemWatcher."""
        if not os.path.exists(path):
            return
            
        uid = UidManager.getUidFromFile(path)
        if uid and uid in self._cache:
            self.loadModule(uid)
            self.moduleChanged.emit(uid)

        # resync dependent modules in cache
        for m in self._cache.values():
            if m.dependsOn(uid):
                m.sync()
                self.moduleChanged.emit(m._uid)

    def refresh(self):
        """Force-reload all cached reference modules."""
        for uid in list(self._cache.keys()):
            self.loadModule(uid)

    def clearCache(self):
        """Clear all loaded modules and stop watching files."""
        self._cache.clear()
        if self._watcher.files():
            self._watcher.removePaths(self._watcher.files())

class RenameModuleCommand(QUndoCommand):
    def __init__(self, model: ModuleModel, module: Module, oldName: str, newName: str):
        super().__init__(f"Rename '{oldName}' to '{newName}'")
        self.model = model
        self.module = module
        self.oldName = oldName
        self.newName = newName

    def redo(self):
        connections = self.model._saveConnections(self.module)
        self.module.setName(self.newName)
        self.model._updateConnections(connections)
        idx = self.model.indexForModule(self.module)
        self.model.dataChanged.emit(idx, idx)

    def undo(self):
        connections = self.model._saveConnections(self.module)
        self.module.setName(self.oldName)
        self.model._updateConnections(connections)
        idx = self.model.indexForModule(self.module)
        self.model.dataChanged.emit(idx, idx)

class AddModuleCommand(QUndoCommand):
    def __init__(self, model: ModuleModel, module: Module, parentIndex: QModelIndex, row: int):
        super().__init__(f"Add Module: {module.name()}")
        self.model = model
        self.module = module
        self.parentIndex = QPersistentModelIndex(parentIndex)
        self.row = row

    def redo(self):
        parentModule = self.model.getModule(QModelIndex(self.parentIndex)) or self.model.rootModule()
        
        # Ensure unique name within parent
        existingNames = {ch.name() for ch in parentModule.children() if ch is not self.module}
        self.module.setName(findUniqueName(self.module.name(), existingNames))

        if self.row < 0:
            self.row = len(parentModule.children())
        
        self.model.beginInsertRows(QModelIndex(self.parentIndex), self.row, self.row)
        parentModule.insertChild(self.row, self.module)
        self.model.endInsertRows()

    def undo(self):
        parentModule = self.module.parent() or self.model.rootModule()
        try:
            row = parentModule.children().index(self.module)
        except ValueError:
            return # Module already removed or hierarchy out of sync
            
        parentIdx = self.model.indexForModule(parentModule)
        
        self.model.beginRemoveRows(parentIdx, row, row)
        parentModule.removeChild(self.module)
        self.model.endRemoveRows()

class RemoveModulesCommand(QUndoCommand):
    def __init__(self, model: ModuleModel, indices: List[QModelIndex]):
        super().__init__("Remove Module(s)")
        self.model = model
        # Store modules and their positions
        self.items = []
        for idx in sorted(indices, key=lambda x: x.row(), reverse=True):
            m = model.getModule(idx)
            p = m.parent() or model.rootModule()
            row = p.children().index(m)
            self.items.append((m, QPersistentModelIndex(model.indexForModule(p)), row))

    def redo(self):
        for m, p_idx, row in self.items:
            self.model.beginRemoveRows(QModelIndex(p_idx), row, row)
            (m.parent() or self.model.rootModule()).removeChild(m)
            self.model.endRemoveRows()

    def undo(self):
        for m, p_idx, row in reversed(self.items):
            self.model.beginInsertRows(QModelIndex(p_idx), row, row)
            (self.model.getModule(QModelIndex(p_idx)) or self.model.rootModule()).insertChild(row, m)
            self.model.endInsertRows()

class MuteModuleCommand(QUndoCommand):
    def __init__(self, model: ModuleModel, indices: List[QModelIndex]):
        super().__init__("Mute/Unmute Module(s)")
        self.model = model
        self.modules = [model.getModule(idx) for idx in indices]
        self.oldStates = [m.muted() for m in self.modules]

    def redo(self):
        for m in self.modules:
            if m.muted(): m.unmute()
            else: m.mute()
        self.model.layoutChanged.emit()

    def undo(self):
        for m, state in zip(self.modules, self.oldStates):
            if state: m.mute()
            else: m.unmute()
        self.model.layoutChanged.emit()

class EmbedModuleCommand(QUndoCommand):
    def __init__(self, model: ModuleModel, indices: List[QModelIndex]):
        super().__init__("Embed Module(s)")
        self.model = model
        self.modules = [model.getModule(idx) for idx in indices]
        self.oldUids = [m.uid() for m in self.modules]

    def redo(self):
        for m in self.modules:
            m.embed()
        self.model.layoutChanged.emit()

    def undo(self):
        for m, uid in zip(self.modules, self.oldUids):
            m._uid = uid
        self.model.layoutChanged.emit()

class MoveModulesCommand(QUndoCommand):
    def __init__(self, model: ModuleModel, modules: List[Module], targetParentIdx: QModelIndex, targetRow: int):
        super().__init__("Move Module(s)")
        self.model = model
        self.targetParentIdx = QPersistentModelIndex(targetParentIdx)
        self.targetRow = targetRow
        self.items = [] # (module, oldParentIdx, oldRow)
        for m in modules:
            p = m.parent() or model.rootModule()
            row = p.children().index(m)
            self.items.append((m, QPersistentModelIndex(model.indexForModule(p)), row))

    def redo(self):
        targetParent = self.model.getModule(QModelIndex(self.targetParentIdx)) or self.model.rootModule()
        currTargetRow = self.targetRow
        for m, oldParentIdx, oldRow in self.items:
            oldParent = m.parent() or self.model.rootModule()
            actualTargetRow = currTargetRow
            
            # Adjust row if moving within the same parent
            if oldParent == targetParent and oldRow < currTargetRow:
                actualTargetRow -= 1
                
            if self.model.beginMoveRows(QModelIndex(oldParentIdx), oldRow, oldRow, QModelIndex(self.targetParentIdx), currTargetRow):
                oldParent.removeChild(m)
                targetParent.insertChild(actualTargetRow, m)
                self.model.endMoveRows()
                currTargetRow = actualTargetRow + 1 # Next item goes after this one

    def undo(self):
        for m, oldParentIdx, oldRow in reversed(self.items):
            currParent = m.parent() or self.model.rootModule()
            currRow = currParent.children().index(m)
            
            if self.model.beginMoveRows(self.model.indexForModule(currParent), currRow, currRow, QModelIndex(oldParentIdx), oldRow):
                currParent.removeChild(m)
                oldParent = self.model.getModule(QModelIndex(oldParentIdx)) or self.model.rootModule()
                oldParent.insertChild(oldRow, m)
                self.model.endMoveRows()
                

class SyncModulesCommand(QUndoCommand):
    def __init__(self, model: ModuleModel, modules: List[Module]):
        super().__init__("Sync Module(s)")
        self.model = model
        self.modules = modules
        
        # Save old state to be able to fully restore
        self.oldStates = [m.toXml(keepConnections=True) for m in modules]

    def redo(self):
        self.model.beginResetModel()
        for m in self.modules:
            m.sync()
        self.model.endResetModel()

    def undo(self):
        self.model.beginResetModel()
        for m, oldState in zip(self.modules, self.oldStates):
            # Deserialize old state
            oldModule = Module.fromXml(oldState)
            
            # Restore state using syncWith
            m.syncWith(oldModule)
        self.model.endResetModel()

class SyncModuleWithCommand(QUndoCommand):
    def __init__(self, model: ModuleModel, module: Module, referenceModule: Module):
        super().__init__(f"Sync '{module.name()}'")
        self.model = model
        self.module = module
        self.referenceModule = referenceModule
        
        # Save old state to be able to fully restore
        self.oldState = module.toXml(keepConnections=True)

    def redo(self):
        self.model.beginResetModel()
        self.module.syncWith(self.referenceModule)
        self.model.endResetModel()

    def undo(self):
        self.model.beginResetModel()
        
        # Deserialize old state
        oldModule = Module.fromXml(self.oldState)
        
        # Restore state using syncWith
        self.module.syncWith(oldModule)
        self.model.endResetModel()

class AddAttributeCommand(QUndoCommand):
    def __init__(self, tabWidget: AttributesTabWidget, module: Module, attr: Attribute):
        super().__init__(f"Add attribute '{attr.name()}'")
        self.module = module
        self.attr = attr
        self.tabWidget = tabWidget

    def redo(self):
        self.module.addAttribute(self.attr)
        self.tabWidget.updateTabs()
        self.tabWidget.moduleChanged.emit(self.module)

    def undo(self):
        self.module.removeAttribute(self.attr)
        self.tabWidget.updateTabs()
        self.tabWidget.moduleChanged.emit(self.module)

class RemoveAttributeCommand(QUndoCommand):
    def __init__(self, tabWidget: AttributesTabWidget, attr: Attribute):
        super().__init__(f"Remove attribute '{attr.name()}'")
        self.module = attr.module()
        self.attr = attr
        self.index = self.module.attributes().index(attr)
        self.tabWidget = tabWidget

    def redo(self):
        self.module.removeAttribute(self.attr)
        self.tabWidget.updateTabs()
        self.tabWidget.moduleChanged.emit(self.module)

    def undo(self):
        self.module.insertAttribute(self.index, self.attr)
        self.tabWidget.updateTabs()
        self.tabWidget.moduleChanged.emit(self.module)

class EditAttributeCommand(QUndoCommand):
    def __init__(self, tabWidget: AttributesTabWidget, attr: Attribute, oldState: str, newState: str, text: str):
        super().__init__(text)
        self.attr = attr
        self.module = attr.module()
        self.oldState = oldState
        self.newState = newState
        self.tabWidget = tabWidget

    def redo(self):
        newAttr = Attribute.fromXml(self.newState)
        if self.attr.name() != newAttr.name():
            self.attr.setName(newAttr.name())
        self.attr.setCategory(newAttr.category())
        self.attr.setTemplate(newAttr.template())
        self.attr.setConnect(newAttr.connect())
        self.attr.setExpression(newAttr.expression())
        self.attr.setLocalData(newAttr.localData())
        
        self.tabWidget.updateTabs()
        self.tabWidget.moduleChanged.emit(self.module)

    def undo(self):
        oldAttr = Attribute.fromXml(self.oldState)
        if self.attr.name() != oldAttr.name():
            self.attr.setName(oldAttr.name())
        self.attr.setCategory(oldAttr.category())
        self.attr.setTemplate(oldAttr.template())
        self.attr.setConnect(oldAttr.connect())
        self.attr.setExpression(oldAttr.expression())
        self.attr.setLocalData(oldAttr.localData())
        
        self.tabWidget.updateTabs()
        self.tabWidget.moduleChanged.emit(self.module)

class MoveAttributesCommand(QUndoCommand):
    def __init__(self, tabWidget: AttributesTabWidget, module: Module, oldOrder: list, newOrder: list):
        super().__init__("Reorder attributes")
        self.module = module
        self.oldOrder = oldOrder
        self.newOrder = newOrder
        self.tabWidget = tabWidget

    def redo(self):
        if self.module.attributes() != self.newOrder:
            self.module.removeAttributes()
            for a in self.newOrder:
                self.module.addAttribute(a)
                
        self.tabWidget.updateTabs()
        self.tabWidget.moduleChanged.emit(self.module)

    def undo(self):
        self.module.removeAttributes()
        for a in self.oldOrder:
            self.module.addAttribute(a)
        self.tabWidget.updateTabs()
        self.tabWidget.moduleChanged.emit(self.module)


class ModuleModel(QAbstractItemModel):
    """
    Qt Model for Module hierarchy.
    Enables MVC pattern where Module is the single source of truth.
    """
    def __init__(self, rootModule: Optional[Module] = None, parent=None):
        super().__init__(parent)
        self._rootModule = rootModule or Module()
        self._rootModule.setName("ROOT")
        self._draggedModules = [] # Temporary storage for internal drag and drop
        
        self.moduleTracker = ModuleTracker(self)
        self.moduleTracker.moduleChanged.connect(self._onModuleTrackerChanged)

    def rootModule(self) -> Module:
        return self._rootModule

    def getModule(self, index: QModelIndex) -> Optional[Module]:
        """Convert a QModelIndex to a Module object safely."""
        if index.isValid():
            return index.internalPointer()
        return None

    def index(self, row, column, parent=QModelIndex()):
        if not self.hasIndex(row, column, parent):
            return QModelIndex()

        if not parent.isValid():
            parentModule = self._rootModule
        else:
            parentModule = parent.internalPointer()

        if row < 0 or row >= len(parentModule.children()):
            return QModelIndex()

        childModule = parentModule.children()[row]
        return self.createIndex(row, column, childModule)

    def parent(self, index):
        if not index.isValid():
            return QModelIndex()

        childModule = index.internalPointer()
        parentModule = childModule.parent()

        if parentModule == self._rootModule or parentModule is None:
            return QModelIndex()

        grandParent = parentModule.parent()
        if grandParent is None: # Should not happen if parentModule != rootModule
            return QModelIndex()
            
        try:
            row = grandParent.children().index(parentModule)
        except ValueError:
            return QModelIndex()

        return self.createIndex(row, 0, parentModule)

    def rowCount(self, parent=QModelIndex()):
        if parent.column() > 0:
            return 0

        if not parent.isValid():
            parentModule = self._rootModule
        else:
            parentModule = parent.internalPointer()

        return len(parentModule.children())

    def columnCount(self, parent=QModelIndex()):
        return 3 # Name, Path, UID

    def data(self, index, role=Qt.DisplayRole):
        if not index.isValid():
            return None

        module = index.internalPointer()
        column = index.column()

        if role == Qt.DisplayRole:
            if column == 0:
                icon = ""
                if module.referenceFile():
                    icon = "📦 "
                elif self.isInsideReferenceModule(module):
                    icon = "🔒 "
                
                name = module.name()
                refModule = self.moduleTracker.getModule(module.uid())
                if refModule and module.isSyncRequired(refModule):
                    name += "*"
                else:
                    name += " " # space placeholder

                return icon + name

            elif column == 1:
                ref = module.referenceFile()
                if ref:
                    path = relativePath(ref, settings.modulesPath).replace("\\", "/")
                    return os.path.splitext(path)[0]
                else:
                    return ""

            elif column == 2:
                return module.uid()[:8]

        elif role == Qt.EditRole:
            if column == 0:
                return module.name()
            return "n/a"

        elif role == Qt.ForegroundRole:
            # Check if self or any parent is muted
            isMuted = module.muted()
            p = module.parent()
            while p:
                if p.muted():
                    isMuted = True
                    break
                p = p.parent()

            if column == 0:
                color = QColor(200, 200, 200)
                if isMuted:
                    color = QColor(100, 100, 100)
                elif self.isInsideReferenceModule(module):
                    color = QColor(230, 230, 100) # Yellow for reference modules
                return color

            elif column == 1:
                return QColor(100, 100, 100) if isMuted else QColor(125, 125, 125)

            elif column == 2:
                return QColor(100, 100, 150) if isMuted else QColor(125, 125, 170)

        elif role == Qt.BackgroundRole:
            if column == 0:
                if not re.match("\\w*", module.name()):
                    return QColor(170, 50, 50)
                
                p = module.parent()
                if p and len([ch for ch in p.children() if ch.name() == module.name()]) > 1:
                    return QColor(170, 50, 50)

    def setData(self, index, value, role=Qt.EditRole):
        if index.isValid() and role == Qt.EditRole:
            module = index.internalPointer()
            column = index.column()
            if column == 0:
                oldName = module.name()
                newName = replaceSpecialChars(str(value)).strip()
                if not newName or newName == oldName:
                    return False

                undoStack.push(RenameModuleCommand(self, module, oldName, newName))
                return True
        return False

    def _saveConnections(self, currentModule: Module):
        connections = []
        for a in currentModule.attributes():
            connections.append({"attr":a, "module": currentModule, "connections":a.listConnections()})
        for ch in currentModule.children():
            connections += self._saveConnections(ch)
        return connections

    def _updateConnections(self, connections: list[dict]):
        for data in connections:
            srcAttr = data["attr"]
            module = data["module"]
            for a in data["connections"]:
                c = module.path().replace(a.module().path(inclusive=False), "") + "/" + srcAttr.name()
                a.setConnect(c)

    def headerData(self, section, orientation, role=Qt.DisplayRole):
        if orientation == Qt.Horizontal and role == Qt.DisplayRole:
            return ["Name", "Path", "UID"][section]
        return None

    def flags(self, index):
        if not index.isValid():
            return Qt.ItemIsDropEnabled
        
        f = Qt.ItemIsSelectable | Qt.ItemIsEnabled | Qt.ItemIsDragEnabled | Qt.ItemIsDropEnabled
        return f | Qt.ItemIsEditable

    # Helpers for structural changes
    def addModuleAt(self, module: Module, parentIndex: QModelIndex = QModelIndex(), row: int = -1):
        undoStack.push(AddModuleCommand(self, module, parentIndex, row))
        return self.indexForModule(module)

        parentModule = self.getModule(parentIndex) or self._rootModule
        
        # Ensure unique name within parent
        existingNames = {ch.name() for ch in parentModule.children()}
        module.setName(findUniqueName(module.name(), existingNames))

        if row < 0:
            row = len(parentModule.children())
        
        self.beginInsertRows(parentIndex, row, row)
        parentModule.insertChild(row, module)
        self.endInsertRows()
        return self.index(row, 0, parentIndex)

    def indexForModule(self, module: Module, parent=QModelIndex()) -> QModelIndex:
        """Find the QModelIndex for a given Module instance."""
        if not module:
             return QModelIndex()
             
        for row in range(self.rowCount(parent)):
            idx = self.index(row, 0, parent)
            if idx.internalPointer() == module:
                return idx
            
            # Recursive search
            childIdx = self.indexForModule(module, idx)
            if childIdx.isValid():
                return childIdx
        return QModelIndex()

    def mimeTypes(self) -> List[str]:
        return ["text/uri-list", "application/x-rigbuilder-module-internal"]

    def mimeData(self, indexes: List[QModelIndex]) -> QMimeData:
        mimeData = QMimeData()
        
        self._draggedModules = []
        for idx in indexes:
            if idx.column() == 0:
                m = self.getModule(idx)
                if m:
                    self._draggedModules.append(m)
        
        if self._draggedModules:
            # We just need to signal that we have internal modules
            mimeData.setData("application/x-rigbuilder-module-internal", b"true")
        return mimeData

    def supportedDropActions(self) -> Qt.DropActions:
        return Qt.CopyAction | Qt.MoveAction

    def canDropMimeData(self, data: QMimeData, action: Qt.DropAction, row: int, column: int, parent: QModelIndex) -> bool:
        return data.hasFormat("application/x-rigbuilder-module-internal") or data.hasUrls()

    def dropMimeData(self, data: QMimeData, action: Qt.DropAction, row: int, column: int, parent: QModelIndex) -> bool:
        if action == Qt.IgnoreAction:
            return True

        if not data.hasFormat("application/x-rigbuilder-module-internal") and not data.hasUrls():
            return False

        undoStack.beginMacro("Drop Module(s)")

        parentModule = self.getModule(parent) or self._rootModule
        if row < 0:
            row = len(parentModule.children())

        try:
            # External drops (from browser)
            if data.hasUrls():
                for url in data.urls():
                    filePath = url.toLocalFile()
                    if not filePath or not os.path.exists(filePath): continue
                    if any(filePath.endswith(ext) for ext in MODULE_EXTS):
                        m = Module.loadModule(filePath)
                        self.addModuleAt(m, parent, row); row += 1
                return True
            # Internal move
            if data.hasFormat("application/x-rigbuilder-module-internal"):
                if not self._draggedModules: return False
                undoStack.push(MoveModulesCommand(self, self._draggedModules, parent, row))
                self._draggedModules = []
                return True
        finally:
            undoStack.endMacro()
        return False
        
    def isInsideReferenceModule(self, module: Module) -> bool:
        """Recursive helper to find the reference counterpart (source definition) of a module."""
        if module.referenceFile():
            return True

        parent = module.parent()
        return self.isInsideReferenceModule(parent) if parent else False

    def _onModuleTrackerChanged(self, uid: str):
        """Handle signal from ModuleTracker when a tracked file changes."""
        self.layoutChanged.emit() # Refresh all

    def replaceModule(self, index: QModelIndex, newModule: Module):
        """Replace a module instance at the given index with a new one."""
        oldModule = self.getModule(index)
        if not oldModule:
            return
        
        parentModule = oldModule.parent() or self._rootModule
        
        try:
            row = parentModule.children().index(oldModule)
        except ValueError:
            return
            
        self.beginResetModel()
        parentModule.removeChild(oldModule)
        parentModule.insertChild(row, newModule)
        self.endResetModel()

    def clear(self):
        """Clear all modules from the model."""
        self.beginResetModel()
        self.moduleTracker.clearCache()
        self._rootModule.removeChildren()
        self.endResetModel()

class ModuleTreeWidget(QTreeView):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)

        self.clipboard = []  # Module clipboard for copy/paste
        self.middlePressPos = QPoint()
        
        self.moduleModel = ModuleModel()
        self.setModel(self.moduleModel)

        self.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.header().setSectionResizeMode(QHeaderView.ResizeToContents)

        self.setDragEnabled(False) # Handle manually via middle button
        self.setAcceptDrops(True)
        self.setDropIndicatorShown(True)

        self.setIndentation(16)
        self.setEditTriggers(QAbstractItemView.DoubleClicked | QAbstractItemView.EditKeyPressed)

    def clear(self):
        """Clear the tree by resetting the model."""
        self.moduleModel.clear()

    def paintEvent(self, event: QPaintEvent):
        super().paintEvent(event)
        painter = QPainter()
        if painter.begin(self.viewport()):
            painter.setPen(QColor("#7a8699"))
            font = self.font()
            font.setItalic(True)
            painter.setFont(font)
            viewportRect = self.viewport().rect()
            paddedRect = QRect(viewportRect.x(), viewportRect.y(), viewportRect.width(), viewportRect.height() - 5)
            painter.drawText(paddedRect, Qt.AlignBottom | Qt.AlignHCenter, "Press TAB to add modules")
            painter.end()

    def mousePressEvent(self, event: QMouseEvent):
        if event.button() == Qt.MiddleButton:
            self.middlePressPos = event.pos()
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event: QMouseEvent):
        if event.buttons() & Qt.MiddleButton:
            if (event.pos() - self.middlePressPos).manhattanLength() >= QApplication.startDragDistance():
                self._startDrag()
                self.middlePressPos = QPoint()
                event.accept()
                return
        super().mouseMoveEvent(event)

    def _startDrag(self):
        selectedIndices = self.selectionModel().selectedRows()
        if not selectedIndices: return

        mimeData = self.moduleModel.mimeData(selectedIndices)
        drag = QDrag(self)
        drag.setMimeData(mimeData)
        drag.exec(Qt.MoveAction)

    def dropEvent(self, event: QDropEvent):
        if event.source() == self:
            event.setDropAction(Qt.CopyAction) # Prevents Qt from double-removing items
        super().dropEvent(event)

    def drawRow(self, painter: QPainter, option: QStyleOptionViewItem, index: QModelIndex):
        if self.selectionModel().isSelected(index):
            fullRowRect = QRect(0, option.rect.y(), self.viewport().width(), option.rect.height())
            painter.fillRect(fullRowRect, self.palette().highlight())
            option.palette.setBrush(QPalette.Highlight, QBrush(Qt.transparent, Qt.NoBrush))
        else:
            option.palette.setBrush(QPalette.Highlight, self.palette().highlight())
        super().drawRow(painter, option, index)

    def wheelEvent(self, event: QWheelEvent):
        ctrl = event.modifiers() & Qt.ControlModifier

        if ctrl:
            delta = event.angleDelta().y()
            if delta == 0:
                return
                
            d = delta / abs(delta)
            font = self.font()
            sz = clamp(fontSize(font) + d, 6, 20)
            setFontSize(font, sz)
            self.setFont(font)
            
            # Scale indentation proportionally
            self.setIndentation(sz * 1.5)
            event.accept()
        else:
            super().wheelEvent(event)


    def contextMenuEvent(self, event: QContextMenuEvent):
        mainWindow.menu().popup(event.globalPos())

    def selectedModules(self) -> List[Module]:
        return [self.moduleModel.getModule(idx) for idx in self.selectionModel().selectedRows()]

    def currentModule(self) -> Optional[Module]:
        selectedIndices = self.selectionModel().selectedRows()
        if not selectedIndices:
            return None
        
        # If current index is among selected, return it.
        # Otherwise return the first selected one.
        curr = self.currentIndex()
        if curr.isValid() and self.selectionModel().isSelected(curr):
            return self.moduleModel.getModule(curr)
        
        return self.moduleModel.getModule(selectedIndices[0])

    def _getTreeState(self) -> dict:
        """Collect expansion paths, selection paths, and current index path in a single pass."""
        state = {
            "expanded": set(),
            "selected": [],
            "current": None
        }
        
        # Save current index path
        curr = self.currentIndex()
        if curr.isValid():
            path = []
            tmp = curr
            while tmp.isValid():
                m = self.moduleModel.getModule(tmp)
                if m: path.insert(0, m.name())
                tmp = tmp.parent()
            state["current"] = tuple(path)

        def walk(index: QModelIndex, path: Tuple[str, ...]):
            if self.isExpanded(index):
                state["expanded"].add(path)
            if self.selectionModel().isSelected(index):
                state["selected"].append(path)
            
            for row in range(self.moduleModel.rowCount(index)):
                childIdx = self.moduleModel.index(row, 0, index)
                m = self.moduleModel.getModule(childIdx)
                if m:
                    walk(childIdx, path + (m.name(),))

        for row in range(self.moduleModel.rowCount()):
            idx = self.moduleModel.index(row, 0)
            m = self.moduleModel.getModule(idx)
            if m:
                walk(idx, (m.name(),))
        
        return state

    def _setTreeState(self, state: dict):
        """Restore tree state (expansion, selection, current index) in a single pass."""
        self.selectionModel().clearSelection()
        selection = QItemSelection()
        expanded = state.get("expanded", set())
        selected = state.get("selected", [])
        currentPath = state.get("current")

        def walk(index: QModelIndex, path: Tuple[str, ...]):
            if path in expanded:
                self.setExpanded(index, True)
            if path in selected:
                selection.select(index, index)
            if currentPath == path:
                self.setCurrentIndex(index)

            for row in range(self.moduleModel.rowCount(index)):
                childIdx = self.moduleModel.index(row, 0, index)
                m = self.moduleModel.getModule(childIdx)
                if m:
                    walk(childIdx, path + (m.name(),))

        for row in range(self.moduleModel.rowCount()):
            idx = self.moduleModel.index(row, 0)
            m = self.moduleModel.getModule(idx)
            if m:
                walk(idx, (m.name(),))
        
        if not selection.isEmpty():
            self.selectionModel().select(selection, QItemSelectionModel.Select | QItemSelectionModel.Rows)
        
    def replaceModule(self, index: QModelIndex, newModule: Module):
        """Replace a module instance at the given index, preserving expansion and selection state."""
        if not index.isValid():
            return
        
        state = self._getTreeState()
        self.moduleModel.replaceModule(index, newModule)
        self._setTreeState(state)

    def insertModule(self):
        m = Module()
        m.setName("module")
        
        # Add to root if nothing selected or current index is invalid
        parentIdx = self.currentIndex()
        if not self.selectionModel().hasSelection() or not parentIdx.isValid():
             parentIdx = QModelIndex()
        
        newIdx = self.moduleModel.addModuleAt(m, parentIdx)
        if parentIdx.isValid():
            self.setExpanded(parentIdx, True)
        self.setCurrentIndex(newIdx)
        self.scrollTo(newIdx)

    def importModule(self):
        filePath, _ = QFileDialog.getOpenFileName(mainWindow, "Import", settings.modulesPath, "Module files (*.rb *.xml);;All files (*)")
        if not filePath:
            return

        try:
            m = Module.loadModule(filePath)
            self.moduleModel.addModuleAt(m)
        except ET.ParseError:
            logger.error(f"'{filePath}': invalid module")
            mainWindow.showLog()

    def importScript(self):
        filePath, _ = QFileDialog.getOpenFileName(mainWindow, "Import script", settings.modulesPath, "Python (*.py);;All files (*)")
        if not filePath:
            return

        with open(filePath, "r", encoding="utf-8") as f:
            code = f.read()

        name = os.path.splitext(os.path.basename(filePath))[0]
        m = Module()
        m.setName(name)
        m.setRunCode(code)
        
        newIdx = self.moduleModel.addModuleAt(m)
        self.setCurrentIndex(newIdx)

    def saveModules(self, forceDialog: bool = False, generateNewUids: bool = False):
        selectedIndices = self.selectionModel().selectedRows()
        if not selectedIndices:
            return

        saveData = [] # List of (module, outputPath, index)

        # 1. Collect target paths and show file dialogs if needed
        for idx in selectedIndices:
            module = self.moduleModel.getModule(idx)
            outputPath = None
            
            if not forceDialog:
                outputPath = module.referenceFile()

            if not outputPath:
                initialPath = os.path.join(settings.modulesPath, module.name())
                title = "Save as " + module.name() if forceDialog else "Save " + module.name()
                outputPath, _ = QFileDialog.getSaveFileName(mainWindow, title, initialPath, "Module files (*.rb *.xml)")

            if outputPath:
                saveData.append((module, outputPath, idx))

        if not saveData:
            return

        # 2. Confirmation / Commit message
        historyWidget = mainWindow.moduleHistoryBrowser
        historyEnabled = historyWidget.isHistoryTrackingEnabled()
        commitMessage = ""

        # Build list for description
        desc = "Save modules?\n" + "\n".join(["{} -> {}".format(m.name(), relativePath(p, settings.modulesPath)) for m, p, _ in saveData])

        if historyEnabled:
            modulesToSave = [m for m, _, _ in saveData]
            accepted, commitMessage = historyWidget.showCommitMessageDialog(
                diffText=calculateModulesDiff(modulesToSave),
                description=desc
            )
            if not accepted:
                return
        else:
            if QMessageBox.question(mainWindow, "Rig Builder", desc, QMessageBox.Yes | QMessageBox.No, QMessageBox.Yes) != QMessageBox.Yes:
                return

        # 3. Perform the actual save
        for module, outputPath, idx in saveData:
            dirname = os.path.dirname(outputPath)
            if not os.path.exists(dirname):
                os.makedirs(dirname)

            try:
                module.saveToFile(outputPath, newUid=generateNewUids)
            except Exception as e:
                QMessageBox.critical(mainWindow, "Rig Builder", "Can't save module '{}': {}".format(module.name(), str(e)))
            else:
                if historyEnabled:
                    if not moduleHistoryBrowser.recordModuleSave(module, commitMessage):
                        QMessageBox.critical(mainWindow, "Rig Builder", "Can't save history for '{}'".format(module.name()))
                
                self.moduleModel.dataChanged.emit(idx, idx) # refresh display

        mainWindow.moduleHistoryBrowser.syncModuleHistory()

    def embedModule(self):
        modules = self.selectedModules()
        if not modules:
            return

        msg = "\n".join([m.name() for m in modules])

        if QMessageBox.question(mainWindow, "Rig Builder", "Embed modules?\n"+msg, QMessageBox.Yes | QMessageBox.No, QMessageBox.Yes) != QMessageBox.Yes:
            return

        undoStack.push(EmbedModuleCommand(self.moduleModel, self.selectionModel().selectedRows()))

    def syncAllModules(self):
        """Full refresh of the entire tree from disk while preserving expansion state."""
        state = self._getTreeState()

        undoStack.push(SyncModulesCommand(self.moduleModel, [self.moduleModel.rootModule()]))
        
        self._setTreeState(state)

    def syncSelectedModules(self):
        """Sync selected modules with the files on disk with confirmation."""
        selectedIndices = self.selectionModel().selectedRows()
        if not selectedIndices:
            return

        msg = "Sync selected modules with the files on disk?\n\nYou may lose unsaved changes for those modules.\n\nContinue?"
        if QMessageBox.question(mainWindow, "Rig Builder", msg, QMessageBox.Yes | QMessageBox.No, QMessageBox.Yes) != QMessageBox.Yes:
            return

        state = self._getTreeState()
        
        modules = []
        for idx in selectedIndices:
            module = self.moduleModel.getModule(idx)
            if module:
                modules.append(module)
                
        if modules:
            undoStack.push(SyncModulesCommand(self.moduleModel, modules))
        self._setTreeState(state)

    def muteModule(self):
        selectedIndices = self.selectionModel().selectedRows()
        if not selectedIndices:
            return

        undoStack.push(MuteModuleCommand(self.moduleModel, selectedIndices))
    def duplicateModule(self):
        # Sort indices by row descending to avoid index shifting issues during insertion
        rows = sorted(self.selectionModel().selectedRows(0), key=lambda x: x.row(), reverse=True)
        if not rows:
            return

        undoStack.beginMacro("Duplicate Module(s)")

        newIndices = []
        try:
            for idx in rows:
                module = self.moduleModel.getModule(idx)
                if not module: continue
                newModule = module.copy()
                parentIdx = idx.parent()
                newIdx = self.moduleModel.addModuleAt(newModule, parentIdx, idx.row() + 1)
                if newIdx.isValid():
                    newIndices.append(newIdx)
                    if parentIdx.isValid(): self.setExpanded(parentIdx, True)
        finally:
            undoStack.endMacro()

        # Select all newly created modules
        if newIndices:
            self.selectionModel().clearSelection()
            for idx in newIndices:
                self.selectionModel().select(idx, QItemSelectionModel.Select | QItemSelectionModel.Rows)

    def copyModules(self):
        """Copy selected modules to clipboard."""
        modules = self.selectedModules()
        if not modules:
            return
            
        self.clipboard = [m.copy() for m in modules]
        
    def cutModules(self):
        """Cut selected modules to clipboard."""
        modules = self.selectedModules()
        if not modules:
            return

        self.clipboard = [m.copy() for m in modules]
        
        self.removeModule(askConfirmation=False)

    def pasteModules(self):
        """Paste modules from clipboard."""
        if not self.clipboard:
            QMessageBox.warning(self, "Rig Builder", "Clipboard is empty.")
            return

        parentIdx = self.currentIndex()
        if not self.selectionModel().hasSelection() or not parentIdx.isValid():
            parentIdx = QModelIndex()
            
        parentModule = self.moduleModel.getModule(parentIdx) or self.moduleModel.rootModule()

        if parentIdx.isValid():
            self.setExpanded(parentIdx, True)

        undoStack.beginMacro("Paste Module(s)")

        pastedIndices = []
        try:
            for module in self.clipboard:
                newModule = module.copy()
                newIdx = self.moduleModel.addModuleAt(newModule, parentIdx)
                pastedIndices.append(newIdx)
        finally:
            undoStack.endMacro()
        
        # Select pasted items
        self.selectionModel().clearSelection()
        for idx in pastedIndices:
            self.selectionModel().select(idx, QItemSelectionModel.Select | QItemSelectionModel.Rows)
            
    def removeModule(self, *, askConfirmation: bool = True):
        selectedIndices = self.selectionModel().selectedRows()
        if not selectedIndices:
            return

        if askConfirmation:
            modules = self.selectedModules()
            msg = "\n".join([m.name() for m in modules])
            if QMessageBox.question(mainWindow, "Rig Builder", "Remove modules?\n"+msg, QMessageBox.Yes | QMessageBox.No, QMessageBox.Yes) != QMessageBox.Yes:
                return

        undoStack.push(RemoveModulesCommand(self.moduleModel, selectedIndices))
    def addModule(self, module: "Module") -> "Module":
        """Adds top level module."""
        self.moduleModel.addModuleAt(module)
        return module

    def selectModule(self, module: Module):
        """Find and select a module in the tree view."""
        if not module:
             return
        idx = self.moduleModel.indexForModule(module)
        if idx.isValid():
            self.setCurrentIndex(idx)
            self.scrollTo(idx)


class TemplateSelectorDialog(QDialog):
    selectedTemplate = Signal(str)

    def __init__(self, **kwargs):
        super().__init__(**kwargs)

        self.setWindowTitle("Template Selector")
        self.setGeometry(0, 0, 700, 500)

        layout = QVBoxLayout()
        self.setLayout(layout)

        scrollWidget = QWidget()
        scrollArea = QScrollArea()
        scrollArea.setWidget(scrollWidget)
        scrollArea.setWidgetResizable(True)

        self.gridLayout = QGridLayout()
        scrollWidget.setLayout(self.gridLayout)

        self.gridLayout.setDefaultPositioning(3, Qt.Horizontal)
        self.gridLayout.setColumnStretch(1, 1)

        layout.addWidget(scrollArea)

        self.refreshTemplates()
        centerWindow(self)

    def selectTemplate(self, t: str):
        self.selectedTemplate.emit(t)
        self.done(0)

    def refreshTemplates(self):
        """Rebuild template grid."""
        clearLayout(self.gridLayout)

        for t in sorted(TemplateWidgets.keys()):
            self.gridLayout.addWidget(QLabel(t))
            w  = TemplateWidgets[t]()
            w.setJsonData(w.getDefaultData())
            self.gridLayout.addWidget(w)

            selectBtn = QPushButton("✅ Select")
            selectBtn.clicked.connect(partial(self.selectTemplate, t))
            self.gridLayout.addWidget(selectBtn)

class CodeEditorWidget(CodeEditorWithNumbersWidget):
    def __init__(self, module: Optional[Module] = None, **kwargs):
        super().__init__(**kwargs)

        self.module = module
        self._skipSaving = False

        self.editorWidget.textChanged.connect(self._onCodeChanged)

    def _onCodeChanged(self):
        if not self.module or self._skipSaving:
            return

        self.module.setRunCode(self.editorWidget.toPlainText())

    def updateState(self):
        self.editorWidget.ignoreStates = True
        self._skipSaving = True
        self.editorWidget.setText(self.module.runCode() if self.module else "")
        self._skipSaving = False
        self.editorWidget.ignoreStates = False

        self.editorWidget.document().clearUndoRedoStacks()

        if not self.module:
            return

        self.generateCompletionWords()

        self.editorWidget.preset = self.module.path()
        self.editorWidget.loadState()

    def generateCompletionWords(self):
        words = set(self.module.context().keys())

        for a in self.module.attributes():
            words.add("@" + a.name())
            words.add("@" + a.name() + "_data")
            words.add("@set_" + a.name())

        self.editorWidget.words = words

class LogHighligher(QSyntaxHighlighter):
    def __init__(self, parent: QTextDocument):
        super().__init__(parent)

        self.highlightingRules = []

        warningFormat = QTextCharFormat()
        warningFormat.setForeground(QColor(250, 150, 90))
        self.highlightingRules.append(("(?i)\\b\\w*warning\\b", warningFormat))

        errorFormat = QTextCharFormat()
        errorFormat.setForeground(QColor(250, 90, 90))
        self.highlightingRules.append(("(?i)\\b\\w*error\\b", errorFormat))

    def highlightBlock(self, text: str):
        for pattern, format in self.highlightingRules:
            if not pattern:
                continue

            expression = QRegularExpression(pattern)
            iterator = expression.globalMatch(text)
            while iterator.hasNext():
                match = iterator.next()
                self.setFormat(match.capturedStart(), match.capturedLength(), format)

        self.setCurrentBlockState(0)

class LogWidget(QTextEdit):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)

        self.syntax = LogHighligher(self.document())
        self.setPlaceholderText("Output and errors or warnings...")
        self.setReadOnly(True)


    def contextMenuEvent(self, event: QContextMenuEvent):
        menu = self.createStandardContextMenu()
        menu.addSeparator()
        menu.addAction("Clear log", self.clear)
        menu.popup(event.globalPos())

    def write(self, txt: str):
        self.moveCursor(QTextCursor.End)
        self.insertPlainText(txt)
        self.ensureCursorVisible()

    def flush(self):
        return


class REPLWidget(QLineEdit):
    executionRequested = Signal(str)

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.setPlaceholderText("Python REPL (host side)...")
        self._history = []
        self._historyIndex = -1
        self._currentText = ""

    def keyPressEvent(self, event: QKeyEvent):
        if event.key() == Qt.Key_Return or event.key() == Qt.Key_Enter:
            code = self.text().strip()
            if code:
                if not self._history or self._history[-1] != code:
                    self._history.append(code)
                self._historyIndex = -1
                self.executionRequested.emit(code)
                self.clear()
            return

        if event.key() == Qt.Key_Up:
            if not self._history:
                return
            if self._historyIndex == -1:
                self._currentText = self.text()
                self._historyIndex = len(self._history) - 1
            elif self._historyIndex > 0:
                self._historyIndex -= 1
            
            self.setText(self._history[self._historyIndex])
            return

        if event.key() == Qt.Key_Down:
            if self._historyIndex == -1:
                return
            
            if self._historyIndex < len(self._history) - 1:
                self._historyIndex += 1
                self.setText(self._history[self._historyIndex])
            else:
                self._historyIndex = -1
                self.setText(self._currentText)
            return

        super().keyPressEvent(event)


class WideSplitterHandle(QSplitterHandle):
    def __init__(self, orientation: Qt.Orientation, parent: QWidget, **kwargs):
        super().__init__(orientation, parent, **kwargs)
        self.hovered = False

    def enterEvent(self, event: QEvent):
        self.hovered = True
        self.update()
        super().enterEvent(event)

    def leaveEvent(self, event: QEvent):
        self.hovered = False
        self.update()
        super().leaveEvent(event)

    def paintEvent(self, event: QPaintEvent):
        if not self.hovered:
            return

        painter = QPainter()
        if painter.begin(self):
            try:
                # Solid accent color on hover, no patterns
                painter.fillRect(event.rect(), QColor(110, 167, 255, 60))
            finally:
                painter.end()

class WideSplitter(QSplitter):
    def __init__(self, orientation: Qt.Orientation, width: int = 8, **kwargs):
        super().__init__(orientation, **kwargs)
        self.setHandleWidth(width)

    def createHandle(self) -> QSplitterHandle:
        return WideSplitterHandle(self.orientation(), self)

class MyProgressBar(QWidget):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)

        self.queue = []
        self.labelSize = 25

        layout = QHBoxLayout()
        self.setLayout(layout)
        layout.setContentsMargins(0, 0, 0, 0)

        self.labelWidget = QLabel()
        self.progressBarWidget = QProgressBar()
        layout.addWidget(self.labelWidget)
        layout.addWidget(self.progressBarWidget)

    def initialize(self):
        self.queue = []

    def updateWithState(self, state: dict[str, object]):
        trimText = lambda text, size: "..." + text[-size+3:]  if len(text) > size else " "*(size-len(text)) + text
        self.labelWidget.setText(trimText(state["text"], self.labelSize))
        self.progressBarWidget.setValue(state["value"])
        self.progressBarWidget.setMaximum(state["max"])

    def beginProgress(self, text: str, count: int, updatePercent: float = 0.01):
        q = {"text": text, "max": count, "value": 0, "updatePercent":updatePercent}
        self.queue.append(q)
        self.updateWithState(q)
        self.show()

    def stepProgress(self, value: int, text: Optional[str] = None):
        if not self.queue:
            return
        q = self.queue[-1]
        q["value"] = value

        updateValue = int(clamp(q["max"] * q["updatePercent"], 1, q["max"]))

        if not q["updatePercent"] or value % updateValue == 0:
            if text:
                q["text"] = text
            self.updateWithState(q)
            QApplication.processEvents()

    def endProgress(self):
        if not self.queue:
            return
        self.queue.pop()
        if not self.queue:
            self.hide()
        else:
            q = self.queue[-1] # get latest state
            self.updateWithState(q)

# --- Host Settings Dialog ---
class HostManagerDialog(QDialog):
    hostsChanged = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Host Manager")
        self.resize(500, 480)
        
        mainLayout = QVBoxLayout(self)
        mainLayout.setSpacing(15)
        mainLayout.setContentsMargins(20, 20, 20, 20)

        # 1. Discovery Server Settings
        discoveryGroup = QGroupBox("Discovery Server")
        discoveryLayout = QVBoxLayout(discoveryGroup)
        discoveryLayout.setSpacing(10)
        
        infoLabel = QLabel("Rig Builder listens on this port for host registrations.")
        infoLabel.setStyleSheet("color: #888; font-size: 10px;")
        discoveryLayout.addWidget(infoLabel)

        portRow = QHBoxLayout()
        portRow.addWidget(QLabel("Discovery Port:"))
        self.discoveryPortEdit = QLineEdit(str(connectionManager.discoveryPort))
        self.discoveryPortEdit.setValidator(QIntValidator(1, 65535))
        self.discoveryPortEdit.setFixedWidth(80)
        portRow.addWidget(self.discoveryPortEdit)
        portRow.addStretch()
        
        self.savePortBtn = QPushButton("Save && Restart")
        self.savePortBtn.setFixedWidth(120)
        self.savePortBtn.clicked.connect(self._saveDiscoveryPort)
        portRow.addWidget(self.savePortBtn)
        discoveryLayout.addLayout(portRow)
        
        mainLayout.addWidget(discoveryGroup)

        # 2. Startup Code Generator
        generatorGroup = QGroupBox("Host Startup Code Generator")
        generatorLayout = QVBoxLayout(generatorGroup)
        generatorLayout.setSpacing(10)
        
        genInfoLabel = QLabel("Select a host type to generate the initialization snippet.")
        genInfoLabel.setStyleSheet("color: #888; font-size: 10px;")
        generatorLayout.addWidget(genInfoLabel)

        hostRow = QHBoxLayout()
        hostRow.addWidget(QLabel("Target Host:"))

        self.hostCombo = QComboBox()
        for host in AVAILABLE_HOSTS:
            iconPath = os.path.join(RIG_BUILDER_PATH, "ui", "images", f"{host}.png")
            if os.path.exists(iconPath):
                self.hostCombo.addItem(QIcon(iconPath), host.capitalize())
            else:
                self.hostCombo.addItem(host.capitalize())

        self.hostCombo.currentIndexChanged.connect(self._refreshCode)
        hostRow.addWidget(self.hostCombo)
        hostRow.addStretch()
        generatorLayout.addLayout(hostRow)

        codeHeader = QHBoxLayout()
        codeHeader.addWidget(QLabel("Startup Script:"))
        codeHeader.addStretch()
        self.copyBtn = QPushButton("📋")
        self.copyBtn.setFixedWidth(40)
        self.copyBtn.clicked.connect(self._copyCode)
        codeHeader.addWidget(self.copyBtn)
        generatorLayout.addLayout(codeHeader)

        self.codeEdit = QPlainTextEdit()
        self.codeEdit.setReadOnly(True)

        self.codeEdit.setStyleSheet("background-color: #1e1e1e; color: #d4d4d4; border: 1px solid #333; border-radius: 4px;")
        generatorLayout.addWidget(self.codeEdit)
        
        mainLayout.addWidget(generatorGroup)

        # Bottom Buttons
        buttonBox = QDialogButtonBox(QDialogButtonBox.Close)
        buttonBox.rejected.connect(self.reject)
        mainLayout.addWidget(buttonBox)

        self._refreshCode()

    def _saveDiscoveryPort(self):
        port_str = self.discoveryPortEdit.text()
        if not port_str:
            return
            
        port = int(port_str)
        connectionManager.setDiscoveryPort(port)
        
        # Visual feedback
        self.savePortBtn.setText("✅ Saved")
        self.savePortBtn.setStyleSheet("color: #4CAF50; font-weight: bold;")
        QTimer.singleShot(2000, self._resetSaveBtn)
        
        self.hostsChanged.emit()
        self._refreshCode()

    def _resetSaveBtn(self):
        self.savePortBtn.setText("Save && Restart")
        self.savePortBtn.setStyleSheet("")

    def _copyCode(self):
        QApplication.clipboard().setText(self.codeEdit.toPlainText())
        self.copyBtn.setText("✅")
        self.copyBtn.setStyleSheet("color: #4CAF50; font-weight: bold;")
        QTimer.singleShot(2000, self._resetCopyBtn)

    def _resetCopyBtn(self):
        self.copyBtn.setText("📋")
        self.copyBtn.setStyleSheet("")

    def _refreshCode(self):
        host = self.hostCombo.currentText().lower()
        HostClass = host.capitalize() + "Server"
        discoveryPort = self.discoveryPortEdit.text() or str(DEFAULT_DISCOVERY_PORT)

        code = HOST_STARTUP_TEMPLATE.format(
            HostClass=HostClass,
            host=host,
            RIG_BUILDER_PATH=os.path.dirname(RIG_BUILDER_PATH),
            discoveryPort=discoveryPort
        )
        self.codeEdit.setPlainText(code)


class TabEventFilter(QObject):
    def __init__(self, mainWindow, parent=None):
        super().__init__(parent)
        self.mainWindow = mainWindow

    def eventFilter(self, watched, event):
        if event.type() == QEvent.KeyPress:
            if event.key() == Qt.Key_Tab:
                activeWin = QApplication.activeWindow()
                if activeWin and (activeWin == self.mainWindow or self.mainWindow.isAncestorOf(activeWin)):
                    if not self.mainWindow.moduleBrowser.isVisible():
                        focused = QApplication.focusWidget()
                        if not focused or not isinstance(focused, (QLineEdit, QTextEdit, QPlainTextEdit, QAbstractSpinBox, QComboBox)):
                            self.mainWindow.showModulePopup()
                            return True
        return super().eventFilter(watched, event)


class RigBuilderWindow(QFrame):
    def __init__(self):
        super().__init__()

        self.tabEventFilter = TabEventFilter(self)
        QApplication.instance().installEventFilter(self.tabEventFilter)

        self.logger = logger
        self._refreshingUI = False
        self._progressCounter = 0
        
        self.setWindowTitle("Rig Builder {}".format(__version__))
        self.setGeometry(0, 0, 1300, 900)

        self.setWindowFlags(Qt.Window | Qt.WindowCloseButtonHint | Qt.WindowMinMaxButtonsHint)

        layout = QVBoxLayout()
        self.setLayout(layout)

        # --- Host picker row ---
        self.hostCombo = QComboBox()
        self.hostCombo.setPlaceholderText("No host")
        self.hostCombo.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.hostCombo.currentIndexChanged.connect(self._onHostComboChanged)
        hostExecutor.hostDiscovered.connect(self._refreshHostCombo)

        self.hostManageBtn = QPushButton("⚙️")
        self.hostManageBtn.setToolTip("Manage hosts")
        self.hostManageBtn.clicked.connect(self._onManageHosts)

        self.syncBtn = QPushButton("🔄")
        self.syncBtn.setToolTip("Sync all modules (reset local changes)")
        self.syncBtn.clicked.connect(self._onSyncRequested)

        self.aiChatBtn = QPushButton("🤖")
        self.aiChatBtn.setToolTip("AI Chat (Ollama)")
        self.aiChatBtn.clicked.connect(self._onOpenAIChat)
 
        self.workspaceWidget = WorkspaceWidget(parent=self)
        self.workspaceWidget.workspaceChanged.connect(self._onWorkspaceChanged)
        self.workspaceWidget.aboutToChangeWorkspace.connect(self._onAboutToChangeWorkspace)

        self.autoSaveTimer = QTimer(self)
        self.autoSaveTimer.timeout.connect(self._onAutoSaveTimer)

        self.windowPinBtn = QPushButton("📌")
        self.windowPinBtn.setCheckable(True)
        self.windowPinBtn.setToolTip("Pin window (stays on top)")
        self.windowPinBtn.clicked.connect(self.pinWindow)
        self.windowPinBtn.setStyleSheet("QPushButton:checked { background-color: #3e7bd6; border-color: #6ea7ff; color: #ffffff; }")

        headerRow = QHBoxLayout()
        headerRow.addWidget(self.workspaceWidget)
        headerRow.addWidget(self.syncBtn)
        headerRow.addStretch()
        if isOllamaAvailable():
            headerRow.addWidget(self.aiChatBtn)
            headerRow.addStretch()
        headerRow.addWidget(self.hostCombo)
        headerRow.addWidget(self.hostManageBtn)
        headerRow.addWidget(self.windowPinBtn)
        layout.addLayout(headerRow)

        self.treeWidget = ModuleTreeWidget()
        self.treeWidget.selectionModel().selectionChanged.connect(self._onTreeSelectionChanged)
        self.treeWidget.addActions(getActions(self.menu()))
        self.treeWidget.setContextMenuPolicy(Qt.CustomContextMenu)
        self.treeWidget.customContextMenuRequested.connect(self._onTreeContextMenu)
        setActionsLocalShortcut(self.treeWidget)

        self.codeEditorWidget = CodeEditorWidget()
        self.codeEditorWidget.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Ignored)
        self.codeEditorWidget.editorWidget.setPlaceholderText("Your module code...")
        self.codeEditorWidget.setEnabled(False)

        for label, func, hotkey in [
            ("Execute", self._onExecuteCode, "Ctrl+Enter")]:            
            action = QAction(label, self.codeEditorWidget.editorWidget)
            action.setShortcut(hotkey)
            action.triggered.connect(lambda *_, f=func: f())
            self.codeEditorWidget.editorWidget.addCustomAction(action)
        
        self.vscodeBtn = QPushButton("🧙‍♂️ Edit in VSCode")
        self.vscodeBtn.clicked.connect(self.editInVSCode)

        self.apiBrowser = ApiBrowser()

        self.attributesTabWidget = AttributesTabWidget()
        self.attributesTabWidget.moduleChanged.connect(self._onModuleChanged)
        self.attributesTabWidget.moduleCodeExecutionRequested.connect(self._onModuleExecutionRequested)
        self.attributesTabWidget.setEnabled(False)

        self.runBtn = QPushButton("🚀 Run")
        self.runBtn.setToolTip("Execute selected module inside the current host.")
        self.runBtn.setStyleSheet("background-color: #3e4f89")
        self.runBtn.clicked.connect(self.runModule)
        self.runBtn.setEnabled(False)

        self.moduleHistoryBrowser = ModuleHistoryBrowser()
        self.moduleHistoryBrowser.moduleAdditionRequested.connect(self._onModuleAdditionRequested)

        self.docBrowser = DocBrowser()
        self.docBrowser.moduleRequested.connect(self.addModuleBySpec)
        self.docBrowser.editRequested.connect(self._onEditDocRequested)
        self.docBrowser.generationRequested.connect(self._onGenerationDocRequested)
        self.docBrowser.setEnabled(False)

        self.moduleBrowser = ModuleBrowser(parent=self)
        self.moduleBrowser.moduleRequested.connect(self.addModuleBySpec)
        self.moduleBrowser.modulesAutoReloadWatcher.fileChanged.connect(self._onModuleFileChanged)
        
        self.workspaceWidget.updateRequested.connect(self.moduleBrowser.refreshModules)

        self.logWidget = LogWidget()
        self.logWidget.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Ignored)

        self.replWidget = REPLWidget()
        self.replWidget.executionRequested.connect(self._onReplExecute)

        self.progressBarWidget = MyProgressBar()
        self.progressBarWidget.hide()        

        self.aiChatDialog = AIChatDialog(parent=self)
        self.aiChatDialog.beforeSendMessage.connect(self.prepareContextForChat)

        # layout

        treeWithBtnWidget = QWidget()        
        treeWithBtnWidget.setLayout(QVBoxLayout())
        treeWithBtnWidget.layout().setContentsMargins(0, 0, 0, 0)
        treeWithBtnWidget.layout().addWidget(self.vscodeBtn)
        treeWithBtnWidget.layout().addWidget(self.treeWidget)
        treeWithBtnWidget.layout().addWidget(self.runBtn)

        centerSplitter = WideSplitter(Qt.Vertical)
        centerSplitter.addWidget(self.attributesTabWidget)
        centerSplitter.addWidget(self.codeEditorWidget)
        centerSplitter.setSizes([500, 300])

        self.rightTabWidget = QTabWidget()
        self.rightTabWidget.addTab(self.docBrowser, "Doc")
        self.rightTabWidget.addTab(self.apiBrowser, "API")
        self.rightTabWidget.addTab(self.moduleHistoryBrowser, "History")

        centerRightSplitter = WideSplitter(Qt.Horizontal)
        centerRightSplitter.addWidget(centerSplitter)
        centerRightSplitter.addWidget(self.rightTabWidget)
        centerRightSplitter.setSizes([500, 200])

        mainSplitter = WideSplitter(Qt.Horizontal)
        mainSplitter.addWidget(treeWithBtnWidget)
        mainSplitter.addWidget(centerRightSplitter)
        mainSplitter.setSizes([200, 500])

        layoutSplitter = WideSplitter(Qt.Vertical)
        layoutSplitter.addWidget(mainSplitter)
        
        logContainer = QWidget()
        logContainerLayout = QVBoxLayout(logContainer)
        logContainerLayout.setContentsMargins(0, 0, 0, 0)
        logContainerLayout.setSpacing(2)
        logContainerLayout.addWidget(self.logWidget)
        logContainerLayout.addWidget(self.replWidget)
        
        layoutSplitter.addWidget(logContainer)
        layoutSplitter.setSizes([500, 100])

        layout.addWidget(layoutSplitter)
        layout.addWidget(self.progressBarWidget)

        centerWindow(self)

        self.moduleBrowser.modulesAutoReloadWatcher.setRoots([settings.modulesPath])

        self._splitters = {
            "version": 4,
            "widgets": [
                layoutSplitter,
                mainSplitter,
                centerSplitter,
                centerRightSplitter,
            ]
        }
        
        self.loadAppSettings()        
        hostExecutor.hostDiscovered.connect(self._refreshHostCombo)
        self._refreshHostCombo()

    def _onTreeContextMenu(self, pos):
        self.menu().exec(self.treeWidget.mapToGlobal(pos))

    def _onModuleChanged(self, module: Module):
        self.treeWidget.moduleModel.layoutChanged.emit() # refresh tree        
        self.codeEditorWidget.updateState()

    def _onModuleExecutionRequested(self, code: str):
        module = self.treeWidget.currentModule()
        if not module:
            return

        newModule = hostExecutor.executeModuleCode(module, code)
        if newModule is None:
            return

        idx = self.treeWidget.moduleModel.indexForModule(module)
        if idx.isValid():
            self.treeWidget.replaceModule(idx, newModule)

    def _onReplExecute(self, code: str):
        """Execute general code from REPL on host."""
        if not code:
            return

        self.showLog()
        logger.info(f">> {code}")

        hostExecutor.executeCode(code)

    def _onExecuteCode(self):
        """Execute lines interactively with accumulated context."""        
        module = self.treeWidget.currentModule()
        if not module:
            return

        cursor = self.codeEditorWidget.editorWidget.textCursor()
        code = cursor.selectedText().replace("\u2029", "\n").strip()
        if not code:
            code = self.codeEditorWidget.editorWidget.toPlainText().strip()
        if not code:
            return

        self.showLog()
        
        maxLines = 5
        lines = code.splitlines()
        log = [f">> {line}" for line in lines[:maxLines]]
        if len(lines) > maxLines:
            if len(lines) > maxLines + 1:
                log.append(">> ...")
            log.append(f">> {lines[-1]}") # last line is always shown
            
        logger.info("\n".join(log))

        newModule = hostExecutor.executeModuleCode(module, code)
        if newModule is None:
            return

        idx = self.treeWidget.moduleModel.indexForModule(module)
        if idx.isValid():
            self.treeWidget.replaceModule(idx, newModule)

    def _refreshHostCombo(self):
        """Update host selection dropdown based on discovered servers."""
        prevData = self.hostCombo.currentData()

        self.hostCombo.blockSignals(True)
        self.hostCombo.clear()

        # Get discovered hosts
        servers = connectionManager.servers()
        entries = sorted(servers.items(), key=lambda x: x[0].lower())
        
        for _, entry in entries:
            # Use icon for discovered hosts
            iconPath = os.path.join(RIG_BUILDER_PATH, "ui", "images", f"{entry['host']}.png")
            if os.path.exists(iconPath):
                self.hostCombo.addItem(QIcon(iconPath), entry["name"], userData=entry)
            else:
                label = "📡 {} ({})".format(entry["name"], entry["host"])
                self.hostCombo.addItem(label, userData=entry)

        if not servers:
            self.hostCombo.setPlaceholderText("No hosts discovered")
        
        # Try to restore selection
        if prevData:
            for i in range(self.hostCombo.count()):
                itemData = self.hostCombo.itemData(i)
                if itemData["cmdPort"] == prevData["cmdPort"]:
                    self.hostCombo.setCurrentIndex(i)
                    break
        
        # when no host restored
        if self.hostCombo.count() > 0 and self.hostCombo.currentIndex() == -1:
            self.hostCombo.setCurrentIndex(0) # select the first
        
        self.hostCombo.blockSignals(False)

        if self.hostCombo.currentIndex() >= 0 and not connectionManager.isActive():
            self._onHostComboChanged(self.hostCombo.currentIndex())

    def _onHostComboChanged(self, index):
        """Automatically connect to the selected host."""
        entry = self.hostCombo.currentData()
        
        if not entry:
            connectionManager.disconnect()
            self.hostCombo.setStyleSheet("")
            return

        try:
            conn = connectionManager.connect(entry["name"])
            
        except Exception as e:
            self.hostCombo.setStyleSheet("color: #ff6b6b;")
            connectionManager.disconnect()
        else:
            self.hostCombo.setStyleSheet("color: #6ea7ff; font-weight: bold;")
            ws = self.workspaceWidget.currentWorkspace()
            hostExecutor.switchWorkspace(ws.name)

    def _onHostConnectionLost(self, reason: str):
        connectionManager.disconnect()
        self.hostCombo.setStyleSheet("")
        logger.warning(f"Connection to host lost: {reason}")
        # Refresh to show dead hosts are gone (heartbeat should handle this anyway)
        self._refreshHostCombo()

    def _onSyncRequested(self):
        msg = "Sync all modules with the files on disk?\n\nYou may lose unsaved changes for those modules.\n\nContinue?"
        if QMessageBox.question(self, "Rig Builder", msg, QMessageBox.Yes | QMessageBox.No, QMessageBox.Yes) == QMessageBox.Yes:
            self.treeWidget.syncAllModules()

    def _onManageHosts(self):
        """Open a dialog to configure host discovery and networking."""
        dialog = HostManagerDialog(parent=self)
        dialog.hostsChanged.connect(self._refreshHostCombo)
        dialog.exec()

    def prepareContextForChat(self):
        """Prepare tools for AI to avoid threading issues."""
        m = self.treeWidget.currentModule()
        editor = self.codeEditorWidget.editorWidget
        
        self.aiChatDialog.aiToolsContext = {
            "code": editor.toPlainText(),
            "selectedCode":editor.textCursor().selectedText(),
            "host":self.hostCombo.currentData(),
            "workspace":self.workspaceWidget.currentWorkspace().name,
            "selectedModule":m
        }

    def _onModuleFileChanged(self, path):
        if not os.path.isfile(path):
            return
            
        relpath = os.path.splitext(relativePath(path, settings.modulesPath))[0]
        uid = UidManager.getUidFromFile(path)
        logger.warning(f"Module is updated on disk: {relpath} ({uid[:8]})")

    def _onOpenAIChat(self):
        """Open the AI Chat dialog."""
        self.aiChatDialog.show()
        self.aiChatDialog.raise_()
        self.aiChatDialog.activateWindow()

    def pinWindow(self, state: bool):
        """Toggle 'Stay on Top' window flag."""
        self.setWindowFlag(Qt.WindowStaysOnTopHint, state)
        self.show()

    def menu(self):
        menu = QMenu(self)

        undoAction = undoStack.createUndoAction(self, "Undo")
        undoAction.setShortcut(QKeySequence.Undo)
        menu.addAction(undoAction)

        redoAction = undoStack.createRedoAction(self, "Redo")
        redoAction.setShortcut(QKeySequence.Redo)
        menu.addAction(redoAction)

        menu.addSeparator()

        menu.addAction("New", self.treeWidget.insertModule, "Insert")
        menu.addAction("Import", self.treeWidget.importModule, "Ctrl+I")
        menu.addAction("Import script", self.treeWidget.importScript)
        menu.addSeparator()
        menu.addAction("Save", self.treeWidget.saveModules, "Ctrl+S")
        menu.addAction("Save as", partial(self.treeWidget.saveModules, forceDialog=True, generateNewUids=True))
        menu.addAction("Show in Explorer", self.browseModuleFile)
        menu.addAction("View edit history", self.showModuleInHistory, "Ctrl+H")
        menu.addAction("Diff vs File", self.diffModule, "Alt+D")        
        menu.addSeparator()
        menu.addAction("Duplicate", self.treeWidget.duplicateModule, "Ctrl+D")
        menu.addAction("Copy", self.treeWidget.copyModules, "Ctrl+C")
        menu.addAction("Cut", self.treeWidget.cutModules, "Ctrl+X")
        menu.addAction("Paste", self.treeWidget.pasteModules, "Ctrl+V")

        menu.addSeparator()
        menu.addAction("Sync with file", self.treeWidget.syncSelectedModules, "Ctrl+R")
        menu.addAction("Embed", self.treeWidget.embedModule)
        menu.addAction("Mute", self.treeWidget.muteModule, "M")
        menu.addAction("Remove", self.treeWidget.removeModule, "Delete")

        menu.addSeparator()
        menu.addAction("Remove all", self.removeAllModules)
        menu.addSeparator()
        menu.addAction("Open User folder", self.openUserFolder)

        return menu

    def addModule(self, module: Module) -> Optional[Module]:
        """Add a module to the tree and return it."""
        idx = self.treeWidget.moduleModel.addModuleAt(module)
        if idx.isValid():
            return self.treeWidget.moduleModel.getModule(idx)
        return None

    def addModuleBySpec(self, spec: str):
        """Load and select module by spec (UID, relative or full path)."""
        try:
            module = Module.loadModule(spec)
        except ModuleNotFoundError:
            logger.warning("Module not found: {}".format(spec))
            return
        self.treeWidget.addModule(module)
        self.treeWidget.selectModule(module)

    def editInVSCode(self):
        if not shutil.which(settings.vscode):
            msg = "Editor executable not found: {}\n\nPlease install the editor or update the VSCode command in the Workspace Manager.".format(settings.vscode)
            QMessageBox.warning(self,"Editor Error", msg)
            return
   
        mcp_config = {
            "mcpServers": {
                "rigBuilder": {
                    "command": os.path.join(RIG_BUILDER_PATH, ".venv", "Scripts", "python.exe"),
                    "args": ["-u", os.path.join(RIG_BUILDER_PATH, "mcp_server", "server.py")]
                }
            }
        }
            
        config_str = json.dumps(mcp_config, indent=4)
        QApplication.clipboard().setText(config_str)

        msg = "The Rig Builder MCP configuration has been copied to your clipboard.\n\nPlease manually install it for your editor!\n\nHappy coding!"
        QMessageBox.information(self, "Edit in VSCode", msg)

        try:
            subprocess.Popen([settings.vscode, settings.workspacePath], shell=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        except Exception as e:
            QMessageBox.warning(self, "Editor Error", f"Failed to launch editor: {str(e)}")

    def diffModule(self):
        module = self.treeWidget.currentModule()
        if not module:
            return

        refPath = module.referenceFile()
        if not refPath:
            QMessageBox.warning(self, "Rig Builder", "This module has no reference file.")
            return

        if not os.path.exists(refPath):
            QMessageBox.warning(self, "Rig Builder", "Can't find reference file: {}".format(refPath))
            return

        currentXml = module.toXml()
        originalXml = Module.loadModule(refPath).toXml()

        if originalXml == currentXml:
            QMessageBox.information(self, "Rig Builder", "No changes detected.")
            return

        DiffBrowserDialog(originalXml, currentXml, refPath, "Current", parent=self).exec()
                    
    def removeAllModules(self):
        if QMessageBox.question(self, "Rig Builder", "Remove all modules?", QMessageBox.Yes | QMessageBox.No, QMessageBox.Yes) == QMessageBox.Yes:
            model = self.treeWidget.moduleModel
            rootIndices = [model.index(i, 0) for i in range(model.rowCount())]
            
            if not rootIndices:
                return

            if model.undoStack:
                model.undoStack.push(RemoveModulesCommand(model, rootIndices))
            else:
                self.treeWidget.clear()

    def _onModuleAdditionRequested(self, module: Module):
        """Handle module addition from external browsers."""
        added = self.addModule(module)
        self.show()
        self.raise_()
        self.activateWindow()
        if added:
            self.treeWidget.selectModule(added)

    def browseModuleFile(self):
        for module in self.treeWidget.selectedModules():
            path = UidManager.resolve(module.uid())
            if module and os.path.exists(path):
                subprocess.call("explorer /select,\"{}\"".format(os.path.normpath(path)))

    def openUserFolder(self):
        subprocess.call("explorer \"{}\"".format(RIG_BUILDER_USER_PATH))

    def _onTreeSelectionChanged(self, selected, deselected):

        module = self.treeWidget.currentModule()
        en = module is not None
        
        self.runBtn.setEnabled(en) 
        self.docBrowser.setEnabled(en)
        self.attributesTabWidget.setEnabled(en)
        self.codeEditorWidget.setEnabled(en)

        self.moduleHistoryBrowser.filterEdit.setText(module.uid() if module else "")

        self.docBrowser.setDoc(module.doc() if module else "")

        self.attributesTabWidget.module = module
        self.attributesTabWidget.updateTabs()
        self.codeEditorWidget.module = module
        self.codeEditorWidget.updateState()

    def showLog(self):
        self.logWidget.ensureCursorVisible()

    def flushUndo(self):
        """Clear the undo/redo history."""
        undoStack.clear()

    def onConnectionErrorCallback(self, text: str):
        QMessageBox.warning(self, "Rig Builder", text)
        connectionManager.disconnect()
        self.hostCombo.setStyleSheet("")
        self.cleanupRun()

    def onErrorCallback(self, text: str, tb: str):
        logger.error(f"{text}\n{tb}" if tb else text)
        self.showLog()
        self.cleanupRun()

    def onPrintCallback(self, text: str):
        logger.info(text)

    def cleanupRun(self):
        logHandler.flush()
        self.progressBarWidget.endProgress()
        self.runBtn.setEnabled(True)  

    def onRunCallback(self, path: str):
        logger.info(f"{path} is running...")
        self.progressBarWidget.stepProgress(self._progressCounter, path)
        self._progressCounter += 1

    def runModule(self):
        """Run module on the host server."""
        def getChildrenCount(m: Module) -> int:
            return sum(1 + getChildrenCount(ch) for ch in m.children())

        currentModule = self.treeWidget.currentModule()
        if not currentModule:
            return

        if not connectionManager.activeConnection():
            QMessageBox.warning(self, "Rig Builder", "Not connected to host server")
            return

        self.setFocus()
        self.showLog()
        self.runBtn.setEnabled(False)

        count = getChildrenCount(currentModule)
        self.progressBarWidget.initialize()
        self.progressBarWidget.beginProgress(currentModule.path(), count + 1)
        self._progressCounter = 0

        ts = time.strftime("%H:%M:%S")
        logger.info(f"Running on {connectionManager.activeServerName()} at {ts}")

        newModule = hostExecutor.runModule(currentModule)

        if newModule is not None:
            idx = self.treeWidget.moduleModel.indexForModule(currentModule)
            if idx.isValid():
                self.treeWidget.replaceModule(idx, newModule)
            else:            
                QMessageBox.warning(self, "Rig Builder", "Could not find module in tree")
        
        self.cleanupRun()

        logger.info("Running done.\n")

    def showModuleInHistory(self):
        """Put selected module UID into history browser filter and clear selection so user can view history."""
        module = self.treeWidget.currentModule()
        if not module:
            return

        if not module.uid():
            return
            
        self.moduleHistoryBrowser.filterEdit.setText(module.uid())
        self.rightTabWidget.setCurrentIndex(2)

    def _onAboutToChangeWorkspace(self):
        """Handle about to change workspace event."""
        if self.workspaceWidget.currentWorkspace():
            self.saveToWorkspace()
 
    def _onWorkspaceChanged(self, ws: workspace.Workspace):
        """Handle workspace change event."""
        self.loadFromWorkspace(ws)
        self.flushUndo()
        self.aiChatDialog.loadChat()
        self._updateAutoSaveInterval()
        self._refreshHostCombo()
        self.moduleBrowser.modulesAutoReloadWatcher.setRoots([ws.settings.modulesPath])
        self.moduleBrowser.refreshModules()

        hostExecutor.switchWorkspace(ws.name)

        logger.info(f"Workspace changed: {ws.name}")
        
    def saveToWorkspace(self):
        """Save UI state to active workspace."""
        ws = self.workspaceWidget.currentWorkspace()
        
        # Sync current global settings into workspace settings before saving
        ws.settings.fromDict(settings.toDict())
        
        tree = self.treeWidget
        rootModules = tree.moduleModel.rootModule().children()
        allModules = workspace.flattenModules(rootModules)
        
        ws.file.modules = rootModules
        ws.file.expanded = [bool(tree.isExpanded(tree.moduleModel.indexForModule(m))) for m in allModules]
        ws.save()

    def loadFromWorkspace(self, ws: workspace.Workspace):
        """Populate UI from the Workspace object."""
        # Update workspace combo if it's not already correct
        self.workspaceWidget.combo.blockSignals(True)

        idx = self.workspaceWidget.combo.findData(ws)
        if idx >= 0:
            self.workspaceWidget.combo.setCurrentIndex(idx)
        self.workspaceWidget.combo.blockSignals(False)

        self.treeWidget.clear()

        for module in ws.file.modules:
            self.treeWidget.moduleModel.addModuleAt(module)

        if ws.file.expanded:
            rootModules = self.treeWidget.moduleModel.rootModule().children()
            allModules = workspace.flattenModules(rootModules)
            for m, isExpanded in zip(allModules, ws.file.expanded):
                if isExpanded:
                    idx = self.treeWidget.moduleModel.indexForModule(m)
                    if idx.isValid():
                        self.treeWidget.setExpanded(idx, True)

    def _updateAutoSaveInterval(self):
        """Update timer interval from global settings."""
        interval_ms = settings.autoSaveInterval * 60 * 1000
        self.autoSaveTimer.start(interval_ms)

    def saveAppSettings(self):
        """Save app-specific settings like active workspace and window geometry."""
        appSettings = QSettings("RigBuilder")
        appSettings.setValue("activeWorkspace", self.workspaceWidget.currentWorkspace().name)
        appSettings.setValue("geometry", self.saveGeometry())
        appSettings.setValue("pinned", self.windowPinBtn.isChecked())
        
        # Save splitter states
        for idx, splitter in enumerate(self._splitters["widgets"]):
            appSettings.setValue(f"splitter{idx}", splitter.saveState())
        appSettings.setValue(f"splitterVersion", self._splitters["version"])        
        appSettings.sync()

    def loadAppSettings(self):
        """Load app-specific settings."""
        appSettings = QSettings("RigBuilder")
        
        # Restore window geometry
        geometry = appSettings.value("geometry")
        if geometry:
            self.restoreGeometry(geometry)

        pinned = appSettings.value("pinned", False, type=bool)
        self.windowPinBtn.setChecked(pinned)
        self.pinWindow(pinned)
        
        # Restore splitter states
        splittersVersion = appSettings.value("splitterVersion", 0, type=int)
        if splittersVersion == self._splitters["version"]: # restore only if versions match
            for idx, splitter in enumerate(self._splitters["widgets"]):
                state = appSettings.value(f"splitter{idx}")
                if state:
                    splitter.restoreState(state)

        # Restore workspace
        workspaceName = appSettings.value("activeWorkspace", "default")
        if not Workspace.exists(workspaceName):
            logger.warning(f"Workspace '{workspaceName}' not found, switching to default.")
            workspaceName = "default"
        self.workspaceWidget.switchWorkspace(workspaceName)

    def _onAutoSaveTimer(self):
        """Handle periodic autosave."""
        self.saveToWorkspace()
        ws = self.workspaceWidget.currentWorkspace()
        timestamp = time.strftime("%H:%M")
        print(f"Workspace '{ws.name}' autosaved at {timestamp}")

    def showModulePopup(self):
        """Show the module browser popup at the current cursor position."""
        # Use last size if user resized it, otherwise default
        popupSize = self.moduleBrowser.size()
        w = popupSize.width() if popupSize.width() > 100 else 760
        h = popupSize.height() if popupSize.height() > 100 else 460
        self.moduleBrowser.resize(w, h)
        
        # Position at the current cursor position (top-left corner of the dialog at mouse pos)
        cursorPos = QCursor.pos()
        x = cursorPos.x()
        y = cursorPos.y()
        
        # Ensure it stays on screen
        screen = QGuiApplication.primaryScreen().availableGeometry()
        x = clamp(x, screen.x(), screen.x() + screen.width() - w)
        y = clamp(y, screen.y(), screen.y() + screen.height() - h)
        
        # Show first, then move to guarantee position is applied correctly by the OS window manager
        self.moduleBrowser.show()
        self.moduleBrowser.move(x, y)
        self.moduleBrowser.raise_()
        self.moduleBrowser.activateWindow()
        self.moduleBrowser.searchWidget.setFocus()
        self.moduleBrowser.searchWidget.selectAll()

    def _onEditDocRequested(self):
        module = self.treeWidget.currentModule()
        if not module:
            return

        def save(text):
            module.setDoc(text)
            self.docBrowser.setDoc(text)

        w = EditTextDialog(
            module.doc(),
            title="Edit documentation",
            placeholder="Enter documentation here...",
            words=set(),
            python=False,
            parent=self)

        w.saved.connect(save)
        w.show()

    def _onGenerationDocRequested(self):
        module = self.treeWidget.currentModule()
        if not module:
            return

        # Prepare children documentation context
        childrenDocs = []
        for ch in module.children():
            doc = ch.doc().strip()
            if doc:
                childrenDocs.append(f"### {ch.name()}\n{doc}")
        
        childrenDocsStr = "\n\n".join(childrenDocs)

        code = module.runCode()
        if not code and not childrenDocsStr:
            QMessageBox.warning(self, "Rig Builder", "Module has no run code and no children documentation to analyze.")
            return

        self.docBrowser.setGenerating(True)
        
        # Create worker without parent so it's not destroyed with the widget
        worker = DocGeneratorWorker(code, childrenDocsStr)
        activeWorkers.append(worker)
        
        def onFinished(summary: str):
            if worker in activeWorkers:
                activeWorkers.remove(worker)
            self.docBrowser.setGenerating(False)
            if summary:
                module.setDoc(summary)
                # Only refresh UI if this module is still selected
                current = self.treeWidget.currentModule()
                if current == module:
                    self.docBrowser.setDoc(summary)
            else:
                QMessageBox.warning(self, "Rig Builder", "AI failed to generate documentation.")
                current = self.treeWidget.currentModule()
                if current == module:
                    self.docBrowser.setDoc(module.doc())

        worker.finished.connect(onFinished)
        worker.start()

    def closeEvent(self, event):
        self.saveAppSettings()
        self.saveToWorkspace()

        # Call parent close event
        super().closeEvent(event)

def updatePalette(app: QApplication):
    # Set global link color
    palette = app.palette()
    palette.setColor(QPalette.Link, QColor("#55aaee"))
    palette.setColor(QPalette.LinkVisited, QColor("#55aaee"))
    app.setPalette(palette)

def applyStylesheet(widget):
    """Load and apply stylesheet."""
    stylesheetPath = os.path.join(RIG_BUILDER_PATH, "ui", "stylesheet.css")
    with open(stylesheetPath, "r", encoding="utf-8") as f:
        content = f.read()

    rootPath = os.path.join(RIG_BUILDER_PATH, "ui").replace("\\", "/")
    content = content.replace("{ROOT}", rootPath)
    widget.setStyleSheet(content)

# initialize

app = QApplication([])
app.setWindowIcon(QIcon(os.path.join(RIG_BUILDER_PATH, "icon.png")))
applyStylesheet(app)
updatePalette(app)

setupStreamRedirection()
setupExcepthook()

mainWindow = RigBuilderWindow()
logHandler.setTarget(mainWindow.logWidget)

logTimer = QTimer()
logTimer.timeout.connect(logHandler.flush)
logTimer.start(100)

hostExecutor.onConnectionError.connect(mainWindow.onConnectionErrorCallback)
hostExecutor.onPrint.connect(mainWindow.onPrintCallback)
hostExecutor.onError.connect(mainWindow.onErrorCallback)
hostExecutor.onRunCallback.connect(mainWindow.onRunCallback)
hostExecutor.beginProgress.connect(mainWindow.progressBarWidget.beginProgress)
hostExecutor.stepProgress.connect(mainWindow.progressBarWidget.stepProgress)
hostExecutor.endProgress.connect(mainWindow.progressBarWidget.endProgress)
hostExecutor.onConnectionLost.connect(mainWindow._onHostConnectionLost)
