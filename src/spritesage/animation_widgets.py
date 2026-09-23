"""Pixel-aware canvases and a horizontal, reorderable animation timeline."""

from PySide6 import QtCore, QtGui, QtWidgets
from PySide6.QtCore import Qt


def checker_brush(palette, size=8):
    tile = QtGui.QPixmap(size * 2, size * 2)
    tile.fill(QtGui.QColor(palette.get("canvas_bg", "#25282C")))
    painter = QtGui.QPainter(tile)
    color = QtGui.QColor(palette.get("checker_bg", "#30343A"))
    painter.fillRect(0, 0, size, size, color)
    painter.fillRect(size, size, size, size, color)
    painter.end()
    return QtGui.QBrush(tile)


class PixelCanvas(QtWidgets.QLabel):
    """Keep source pixels intact; scale only at paint time, even after resizing."""

    def __init__(self, palette, text="", parent=None):
        super().__init__(text, parent)
        self.app_palette = palette
        self.pixel_art = True
        self.checkerboard = True
        self.zoom = 0  # Fit; enlargement uses whole pixels in pixel-art mode.
        self.canvas_size = QtCore.QSize()
        self._checker = checker_brush(palette)
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setSizePolicy(
            QtWidgets.QSizePolicy.Policy.Ignored, QtWidgets.QSizePolicy.Policy.Ignored
        )
        self.setMinimumSize(100, 100)
        self.setAccessibleName("Image preview")

    def sizeHint(self):
        return QtCore.QSize(240, 180)

    def set_zoom(self, zoom):
        self.zoom = max(0, int(zoom))
        self._update_minimum()
        self.update()

    def setPixmap(self, pixmap):
        super().setPixmap(pixmap)
        self._update_minimum()

    def _update_minimum(self):
        size = self.canvas_size if self.canvas_size.isValid() else self.pixmap().size()
        if self.zoom and not size.isEmpty():
            self.setMinimumSize(
                (size * self.zoom + QtCore.QSize(24, 24)).expandedTo(QtCore.QSize(100, 100))
            )
        else:
            self.setMinimumSize(100, 100)

    def paintEvent(self, event):
        painter = QtGui.QPainter(self)
        painter.fillRect(
            self.rect(),
            (
                self._checker
                if self.checkerboard
                else QtGui.QBrush(QtGui.QColor(self.app_palette.get("canvas_bg", "#25282C")))
            ),
        )
        pixmap = self.pixmap()
        if pixmap.isNull():
            painter.setPen(QtGui.QColor(self.app_palette.get("text_color", "#BBBBBB")))
            painter.drawText(
                self.rect().adjusted(12, 12, -12, -12),
                Qt.AlignmentFlag.AlignCenter | Qt.TextFlag.TextWordWrap,
                self.text(),
            )
        else:
            size = self.canvas_size if self.canvas_size.isValid() else pixmap.size()
            fit = min(
                max(1, self.width() - 24) / size.width(), max(1, self.height() - 24) / size.height()
            )
            scale = self.zoom or (max(1, int(fit)) if self.pixel_art and fit >= 1 else fit)
            width, height = round(pixmap.width() * scale), round(pixmap.height() * scale)
            target = QtCore.QRect(
                (self.width() - width) // 2, (self.height() - height) // 2, width, height
            )
            painter.setRenderHint(
                QtGui.QPainter.RenderHint.SmoothPixmapTransform, not self.pixel_art
            )
            painter.drawPixmap(target, pixmap)
        painter.end()


def thumbnail(path, palette, pixel_art=True):
    """Make transparency visible in thumbnails, including an explicit missing-file state."""
    image = QtGui.QPixmap(path)
    result = QtGui.QPixmap(80, 64)
    painter = QtGui.QPainter(result)
    painter.fillRect(result.rect(), checker_brush(palette, 5))
    if image.isNull():
        painter.setPen(QtGui.QColor(palette.get("text_color", "#BBBBBB")))
        painter.drawText(result.rect(), Qt.AlignmentFlag.AlignCenter, "Missing")
    else:
        scaled = image.scaled(
            72,
            56,
            Qt.AspectRatioMode.KeepAspectRatio,
            (
                Qt.TransformationMode.FastTransformation
                if pixel_art
                else Qt.TransformationMode.SmoothTransformation
            ),
        )
        painter.drawPixmap((80 - scaled.width()) // 2, (64 - scaled.height()) // 2, scaled)
    painter.end()
    icon = QtGui.QIcon(result)
    # Selection must highlight the card without recoloring the artwork itself.
    for mode in (QtGui.QIcon.Mode.Active, QtGui.QIcon.Mode.Selected):
        icon.addPixmap(result, mode)
    return icon


class TimelineDelegate(QtWidgets.QStyledItemDelegate):
    def initStyleOption(self, option, index):
        super().initStyleOption(option, index)
        # Keep the path in item data and tooltips; visible labels describe sequence order.
        option.text = f"{index.row() + 1:02d}"
        option.decorationPosition = QtWidgets.QStyleOptionViewItem.Position.Top
        option.displayAlignment = Qt.AlignmentFlag.AlignCenter


class FrameTimeline(QtWidgets.QListWidget):
    frames_reordered = QtCore.Signal(int, int)
    drag_started = QtCore.Signal()
    step_requested = QtCore.Signal(int)
    play_requested = QtCore.Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("FrameTimeline")
        self.setAccessibleName("Animation frame timeline")
        self.setItemDelegate(TimelineDelegate(self))
        self.setViewMode(QtWidgets.QListView.ViewMode.IconMode)
        self.setFlow(QtWidgets.QListView.Flow.LeftToRight)
        self.setWrapping(False)
        self.setResizeMode(QtWidgets.QListView.ResizeMode.Adjust)
        self.setMovement(QtWidgets.QListView.Movement.Snap)
        self.setIconSize(QtCore.QSize(80, 64))
        self.setGridSize(QtCore.QSize(96, 94))
        self.setSpacing(4)
        self.setMinimumSize(100, 116)
        self.setHorizontalScrollMode(QtWidgets.QAbstractItemView.ScrollMode.ScrollPerPixel)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setDragDropMode(QtWidgets.QAbstractItemView.DragDropMode.InternalMove)
        self.setDefaultDropAction(Qt.DropAction.MoveAction)
        self.setSelectionMode(QtWidgets.QAbstractItemView.SelectionMode.SingleSelection)
        self.setToolTip("Drag to reorder • Left / Right to step • Space to play or pause")
        self._drop_index = None

    def startDrag(self, supported_actions):
        if self.currentRow() < 0:
            return
        self.drag_started.emit()
        drag = QtGui.QDrag(self)
        drag.setMimeData(self.model().mimeData(self.selectedIndexes()))
        drag.setPixmap(self.currentItem().icon().pixmap(self.iconSize()))
        # We move rows ourselves in dropEvent. Qt's default startDrag can remove
        # the source a second time after a successful custom MoveAction drop.
        try:
            drag.exec(Qt.DropAction.MoveAction)
        finally:
            self._drop_index = None
            self.viewport().update()
            drag.deleteLater()

    def _insertion_index(self, position):
        for row in range(self.count()):
            if position.x() < self.visualItemRect(self.item(row)).center().x():
                return row
        return self.count()

    def dragMoveEvent(self, event):
        if event.source() is not self:
            event.ignore()
            return
        super().dragMoveEvent(event)  # Retain Qt's edge auto-scroll.
        self._drop_index = self._insertion_index(event.position().toPoint())
        event.setDropAction(Qt.DropAction.MoveAction)
        event.accept()
        self.viewport().update()

    def dragLeaveEvent(self, event):
        self._drop_index = None
        super().dragLeaveEvent(event)
        self.viewport().update()

    def dropEvent(self, event):
        if event.source() is not self:
            event.ignore()
            return
        source = self.currentRow()
        insertion = self._insertion_index(event.position().toPoint())
        self.move_frame(source, insertion - (source < insertion))
        self._drop_index = None
        event.setDropAction(Qt.DropAction.MoveAction)
        event.accept()
        self.viewport().update()

    def move_frame(self, source, destination):
        if source == destination or not (
            0 <= source < self.count() and 0 <= destination < self.count()
        ):
            return
        with QtCore.QSignalBlocker(self):
            item = self.takeItem(source)
            self.insertItem(destination, item)
            self.setCurrentItem(item)
        self.scrollToItem(item)
        self.frames_reordered.emit(source, destination)

    def keyPressEvent(self, event):
        if event.modifiers() == Qt.KeyboardModifier.NoModifier:
            if event.key() == Qt.Key.Key_Space:
                self.play_requested.emit()
                event.accept()
                return
            if event.key() in (Qt.Key.Key_Left, Qt.Key.Key_Right):
                self.step_requested.emit(-1 if event.key() == Qt.Key.Key_Left else 1)
                event.accept()
                return
        super().keyPressEvent(event)

    def paintEvent(self, event):
        super().paintEvent(event)
        painter = QtGui.QPainter(self.viewport())
        if not self.count():
            painter.setPen(self.palette().color(QtGui.QPalette.ColorRole.Text))
            painter.drawText(
                self.viewport().rect(),
                Qt.AlignmentFlag.AlignCenter,
                "Add frames to start your animation",
            )
        elif self._drop_index is not None:
            row = min(self._drop_index, self.count() - 1)
            rect = self.visualItemRect(self.item(row))
            x = rect.right() + 2 if self._drop_index == self.count() else rect.left() - 2
            painter.setPen(QtGui.QPen(self.palette().highlight().color(), 3))
            painter.drawLine(x, rect.top(), x, rect.bottom())
        painter.end()
