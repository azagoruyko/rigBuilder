from .base import *

import math
import time

def listLerp(lst1, lst2, coeff):
    return [p1*(1-coeff) + p2*coeff for p1, p2 in zip(lst1, lst2)]

def evaluateBezierCurve(cvs, param):    
    absParam = param * (math.floor((len(cvs) + 2) / 3.0) - 1)

    offset = int(math.floor(absParam - 1e-5))
    if offset < 0:
        offset = 0

    t = absParam - offset

    p1 = cvs[offset * 3]
    p2 = cvs[offset * 3 + 1]
    p3 = cvs[offset * 3 + 2]
    p4 = cvs[offset * 3 + 3]

    return evaluateBezier(p1, p2, p3, p4, t)

def evaluateBezier(p1, p2, p3, p4, param): # De Casteljau's algorithm
    p1_p2 = listLerp(p1, p2, param)
    p2_p3 = listLerp(p2, p3, param)
    p3_p4 = listLerp(p3, p4, param)

    p1_p2_p2_p3 = listLerp(p1_p2, p2_p3, param)
    p2_p3_p3_p4 = listLerp(p2_p3, p3_p4, param)
    return listLerp(p1_p2_p2_p3, p2_p3_p3_p4, param)

def bezierSplit(p1, p2, p3, p4, at=0.5):
    p1_p2 = listLerp(p1, p2, at)
    p2_p3 = listLerp(p2, p3, at)
    p3_p4 = listLerp(p3, p4, at)

    p1_p2_p2_p3 = listLerp(p1_p2, p2_p3, at)
    p2_p3_p3_p4 = listLerp(p2_p3, p3_p4, at)
    p = listLerp(p1_p2_p2_p3, p2_p3_p3_p4, at)

    return (p1, p1_p2, p1_p2_p2_p3, p), (p, p2_p3_p3_p4, p3_p4, p4)

def findFromX(p1, p2, p3, p4, x):
    cvs1, cvs2 = bezierSplit(p1, p2, p3, p4)
    midp = cvs2[0]

    if abs(midp[0] - x) < 1e-3:
        return midp
    elif x < midp[0]:
        return findFromX(cvs1[0], cvs1[1], cvs1[2], cvs1[3], x)
    else:
        return findFromX(cvs2[0], cvs2[1], cvs2[2], cvs2[3], x)

def evaluateBezierCurveFromX(cvs, x):
    for i in range(0, len(cvs), 3):
        if cvs[i][0] > x:
            break

    return findFromX(cvs[i-3], cvs[i-2], cvs[i-1], cvs[i], x)

def normalizedPoint(p, minX, maxX, minY, maxY):
    x = (p[0] - minX) / (maxX - minX)
    y = (p[1] - minY) / (maxY - minY)
    return (x, y)

class CurvePointItem(QGraphicsItem):
    Size = 10
    def __init__(self, **kwargs):
        super(CurvePointItem, self).__init__(**kwargs)

        self.setFlags(QGraphicsItem.ItemIsMovable | QGraphicsItem.ItemIsSelectable | QGraphicsItem.ItemSendsGeometryChanges)

        self.fixedX = None

    def boundingRect(self):
        size = CurvePointItem.Size
        return QRectF(-size/2, -size/2, size, size)
     
    def paint(self, painter, option, widget):
        size = CurvePointItem.Size

        if self.isSelected():
            painter.setBrush(QBrush(QColor(100, 200, 100)))

        painter.setPen(QColor(250, 250, 250))
        painter.drawRect(-size/2, -size/2, size, size)
    
    def itemChange(self, change, value):
        if not self.scene():
            return super(CurvePointItem, self).itemChange(change, value)

        if change == QGraphicsItem.GraphicsItemChange.ItemPositionChange:
            if self.fixedX is not None:
                value.setX(self.fixedX)

            if CurveScene.MaxX > 0:
                if value.x() < 0:
                    value.setX(0)

                elif value.x() > CurveScene.MaxX:
                    value.setX(CurveScene.MaxX)

            else:
                if value.x() > 0:
                    value.setX(0)
                    
                elif value.x() < CurveScene.MaxX:
                    value.setX(CurveScene.MaxX)
            # y
            if CurveScene.MaxY > 0:
                if value.y() < 0:
                    value.setY(0)

                elif value.y() > CurveScene.MaxY:
                    value.setY(CurveScene.MaxY)

            else:
                if value.y() > 0:
                    value.setY(0)
                    
                elif value.y() < CurveScene.MaxY:
                    value.setY(CurveScene.MaxY)

        if change == QGraphicsItem.GraphicsItemChange.ItemPositionHasChanged:
            scene = self.scene()
            scene.calculateCVs()
            for view in scene.views():
                if type(view) == CurveView:
                    view.somethingChanged.emit()

        return super(CurvePointItem, self).itemChange(change, value)

class CurveScene(QGraphicsScene):
    MaxX = 300
    MaxY = -100
    DrawCurveSamples = 33
    def __init__(self, **kwargs):
        super(CurveScene, self).__init__(**kwargs)

        self.cvs = []

        item1 = CurvePointItem()
        item1.setPos(0, CurveScene.MaxY)
        item1.fixedX = 0
        self.addItem(item1)

        item2 = CurvePointItem()
        item2.setPos(CurveScene.MaxX / 2, 0)
        self.addItem(item2)

        item3 = CurvePointItem()
        item3.fixedX = CurveScene.MaxX
        item3.setPos(CurveScene.MaxX, CurveScene.MaxY)
        self.addItem(item3)

    def mouseDoubleClickEvent(self, event):
        pos = event.scenePos()

        if CurveScene.MaxX > 0 and (pos.x() < 0 or pos.x() > CurveScene.MaxX):
            return

        if CurveScene.MaxX < 0 and (pos.x() > 0 or pos.x() < CurveScene.MaxX):
            return

        if CurveScene.MaxY > 0 and (pos.y() < 0 or pos.y() > CurveScene.MaxY):
            return

        if CurveScene.MaxY < 0 and (pos.y() > 0 or pos.y() < CurveScene.MaxY):
            return

        item = CurvePointItem()
        item.setPos(pos)
        self.addItem(item)

        self.calculateCVs()

        for view in self.views():
            if type(view) == CurveView:
                view.somethingChanged.emit()

    def mousePressEvent(self, event):
        if event.button() == Qt.RightButton:
            somethingChanged = False
            for item in self.selectedItems():
                if item.fixedX is None: # don't remove tips
                    self.removeItem(item)
                    somethingChanged = True

            if somethingChanged:
                self.calculateCVs()

                for view in self.views():
                    if type(view) == CurveView:
                        view.somethingChanged.emit()

            event.accept()
        else:
            super(CurveScene,self).mousePressEvent(event)

    def calculateCVs(self):
        self.cvs = []

        if len(self.items()) < 2:
            return

        items = sorted(self.items(), key=lambda item: item.pos().x()) # sorted by x position

        tangents = []
        for i, item in enumerate(items): # calculate tangents
            if i == 0:
                tangents.append(QVector2D(items[i+1].pos() - items[i].pos()).normalized())
            elif i == len(items) - 1:
                tangents.append(QVector2D(items[i].pos() - items[i-1].pos()).normalized())
            else:
                tg = (QVector2D(items[i+1].pos() - items[i].pos()) / (items[i+1].pos().x() - items[i].pos().x()) +
                      QVector2D(items[i].pos() - items[i-1].pos()) / (items[i].pos().x() - items[i-1].pos().x())) / 2.0

                tangents.append(tg)

        for i, item in enumerate(items):
            if i == 0:
                continue

            p1 = items[i-1].pos()
            p4 = items[i].pos()
            d = (p4.x() - p1.x()) / 3
            p2 = p1 + tangents[i-1].toPointF() * d
            p3 = p4 - tangents[i].toPointF() * d

            self.cvs.append(normalizedPoint([p1.x(), p1.y()], 0, CurveScene.MaxX, 0, CurveScene.MaxY))
            self.cvs.append(normalizedPoint([p2.x(), p2.y()], 0, CurveScene.MaxX, 0, CurveScene.MaxY))
            self.cvs.append(normalizedPoint([p3.x(), p3.y()], 0, CurveScene.MaxX, 0, CurveScene.MaxY))

        self.cvs.append(normalizedPoint([p4.x(), p4.y()], 0, CurveScene.MaxX, 0, CurveScene.MaxY))

    def drawBackground(self, painter, rect):
        painter.fillRect(QRect(0,0,CurveScene.MaxX,CurveScene.MaxY), QColor(140, 140, 140))
        painter.setPen(QColor(0, 0, 0))
        painter.drawRect(QRect(0,0,CurveScene.MaxX,CurveScene.MaxY))

        self.calculateCVs()

        font = painter.font()
        if font.pointSize() > 2:
            font.setPointSize(font.pointSize()-2)
            painter.setFont(font)

        GridSize = 4
        TextOffset = 3
        xstep = CurveScene.MaxX / GridSize
        ystep = CurveScene.MaxY / GridSize

        for i in range(GridSize):
            painter.setPen(QColor(40,40,40, 50))
            painter.drawLine(i*xstep, 0, i*xstep, CurveScene.MaxY)
            painter.drawLine(0, i*ystep, CurveScene.MaxX, i*ystep)

            painter.setPen(QColor(0, 0, 0))

            v = "%.2f"%(i/float(GridSize))
            painter.drawText(i*xstep + TextOffset, -TextOffset, v) # X axis

            if i > 0:
                painter.drawText(TextOffset, i*ystep - TextOffset, v) # Y axis

        xFactor = 1.0 / CurveScene.MaxX
        yFactor = 1.0 / CurveScene.MaxY

        if not self.cvs:
            return

        pen = QPen()
        pen.setWidth(2)
        pen.setColor(QColor(40,40,150))
        painter.setPen(pen)

        path = QPainterPath()

        p = normalizedPoint(evaluateBezierCurve(self.cvs, 0), 0, xFactor, 0, yFactor)
        path.moveTo(p[0], p[1])

        N = CurveScene.DrawCurveSamples
        for i in range(N):
            param = i / float(N - 1)
            p = normalizedPoint(evaluateBezierCurve(self.cvs, param), 0, xFactor, 0, yFactor)

            path.lineTo(p[0], p[1])
            path.moveTo(p[0], p[1])

        p = normalizedPoint(evaluateBezierCurve(self.cvs, 1), 0, xFactor, 0, yFactor)
        path.lineTo(p[0], p[1])

        painter.drawPath(path) 

class CurveView(QGraphicsView):
    somethingChanged = Signal()

    def __init__(self, **kwargs):
        super(CurveView, self).__init__(**kwargs)

        self.setRenderHint(QPainter.Antialiasing, True)
        self.setRenderHint(QPainter.TextAntialiasing, True)
        self.setRenderHint(QPainter.HighQualityAntialiasing, True)
        #self.setRenderHint(QPainter.SmoothPixmapTransform, True)
        #self.setRenderHint(QPainter.NonCosmeticDefaultPen, True)
        self.setViewportUpdateMode(QGraphicsView.FullViewportUpdate)
        self.setTransformationAnchor(QGraphicsView.AnchorUnderMouse)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)

        self.setContextMenuPolicy(Qt.DefaultContextMenu)
        self.setScene(CurveScene())

    def contextMenuEvent(self, event):
        event.accept()

    def resizeEvent(self, event):
        self.fitInView(self.scene().sceneRect(), Qt.KeepAspectRatio)

class CurveTemplateWidget(TemplateWidget):
    def __init__(self, **kwargs):
        super(CurveTemplateWidget, self).__init__(**kwargs)

        layout = QVBoxLayout()
        layout.setContentsMargins(0, 0, 0, 0) 
        self.setLayout(layout)

        self.curveView = CurveView()
        self.curveView.somethingChanged.connect(self.somethingChanged)
        layout.addWidget(self.curveView)

    def getDefaultData(self):
        return {'default': 'cvs', 'cvs': [(0.0, 1.0), (0.13973423457023273, 0.722154453101879), (0.3352803473835302, -0.0019584480764515554), (0.5029205210752953, -0.0), (0.6686136807168636, 0.0019357021806590401), (0.8623842449806401, 0.7231513901834298), (1.0, 1.0)]}

    def getJsonData(self):
        return {"cvs": self.curveView.scene().cvs, "default": "cvs"}

    def setJsonData(self, value):
        scene = self.curveView.scene()
        scene.clear()

        for i, (x, y) in enumerate(value["cvs"]):
            if i % 3 == 0: # ignore tangents
                item = CurvePointItem()
                item.setPos(x * CurveScene.MaxX, y * CurveScene.MaxY)
                scene.addItem(item)

                if i == 0 or i == len(value["cvs"]) - 1:
                    item.fixedX = item.pos().x()

class TestWindow(QFrame):
    def __init__(self, **kwargs):
        super(TestWindow, self).__init__(**kwargs)     

        layout = QVBoxLayout()
        self.setLayout(layout)

        self.curveWidget = CurveTemplateWidget()
        layout.addWidget(self.curveWidget)

'''
def ch():print w.curveWidget.getJsonData()
app = QApplication([])
w = TestWindow()
#w.curveWidget.setJsonData({'default': 'cvs', 'cvs': [(0.0, 1.0), (0.26378156124386887, 0.7561018134940005), (0.5520518358531318, -0.25269205675784256), (0.8280777537796977, 0.234341252699784), (0.885385169186465, 0.33545719279583786), (0.9679829706641048, 0.857411613217183), (1.0, 1.0)]})
w.curveWidget.setJsonData(w.curveWidget.getDefaultData())
#w.curveWidget.somethingChanged.connect(ch)
w.show()
app.exec_()

'''