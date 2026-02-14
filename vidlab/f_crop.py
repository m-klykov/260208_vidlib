import cv2
import numpy as np
from PySide6.QtGui import QPen, QColor, Qt
from .f_base import FilterBase


class FilterCrop(FilterBase):
    def __init__(self, num, cache_dir, params=None):
        if not params:
            params = {"top": 0, "bottom": 0, "left": 0, "right": 0, "resize": False}
        super().__init__(num, cache_dir, params)
        self.name = "Crop"

        self.active_side = None
        self.is_dragging = False
        self.margin = 10

        # Конфигурация сторон для мыши: [параметр, ось, инверсия]
        self._side_map = {
            'left': {'axis': 'x', 'inv': False},
            'right': {'axis': 'x', 'inv': True},
            'top': {'axis': 'y', 'inv': False},
            'bottom': {'axis': 'y', 'inv': True}
        }

    def get_params_metadata(self):
        meta = {s: {"type": "int", "min": 0, "max": 49, "default": 0} for s in self._side_map}
        meta["resize"] = {"type": "bool", "default": False}
        return meta

    def _get_pixel_offsets(self, w, h):
        """Возвращает отступы в пикселях: (t, b, l, r)"""
        t = int(h * (self.get_param("top") / 100))
        b = int(h * (self.get_param("bottom") / 100))
        l = int(w * (self.get_param("left") / 100))
        r = int(w * (self.get_param("right") / 100))
        return t, b, l, r

    def process(self, frame, idx):
        h_orig, w_orig = frame.shape[:2]
        t, b, l, r = self._get_pixel_offsets(w_orig, h_orig)

        y1, y2 = t, h_orig - b
        x1, x2 = l, w_orig - r

        if y2 <= y1 or x2 <= x1: return frame

        cropped = frame[y1:y2, x1:x2]

        if self.get_param("resize"):
            return cv2.resize(cropped, (w_orig, h_orig), interpolation=cv2.INTER_CUBIC)
        return cropped

    def render_overlay(self, painter, idx, viewport_rect):
        if not self.focused or self.enabled: return

        w, h = viewport_rect.width(), viewport_rect.height()
        sx, sy = viewport_rect.left(), viewport_rect.top()
        t, b, l, r = self._get_pixel_offsets(w, h)

        # 1. Рамка
        painter.setPen(QPen(QColor(255, 0, 0), 2, Qt.DashLine))
        painter.drawRect(sx + l, sy + t, w - l - r, h - t - b)

        # 2. Затемнение (одной пачкой)
        painter.setPen(Qt.NoPen)
        dark = QColor(0, 0, 0, 100)
        painter.fillRect(sx, sy, w, t, dark)  # Top
        painter.fillRect(sx, sy + h - b, w, b, dark)  # Bottom
        painter.fillRect(sx, sy + t, l, h - t - b, dark)  # Left
        painter.fillRect(sx + w - r, sy + t, r, h - t - b, dark)  # Right

    def handle_mouse_move(self, pos, rect):
        if self.enabled: return Qt.ArrowCursor, False

        w, h = rect.width(), rect.height()
        sx, sy = rect.left(), rect.top()
        t, b, l, r = self._get_pixel_offsets(w, h)

        # Координаты линий для проверки
        lines = {
            'left': sx + l, 'right': sx + w - r,
            'top': sy + t, 'bottom': sy + h - b
        }

        if not self.is_dragging:
            self.active_side = None
            for side, coord in lines.items():
                val = pos.x() if self._side_map[side]['axis'] == 'x' else pos.y()
                if abs(val - coord) < self.margin:
                    self.active_side = side
                    break

            if not self.active_side: return Qt.ArrowCursor, False
            curs = Qt.SizeHorCursor if self._side_map[self.active_side]['axis'] == 'x' else Qt.SizeVerCursor
            return curs, False

        else:
            # Математика перетаскивания через side_map
            side_info = self._side_map[self.active_side]
            is_x = side_info['axis'] == 'x'

            # Определяем относительную позицию (0..100)
            if is_x:
                val = (pos.x() - sx) / w * 100
            else:
                val = (pos.y() - sy) / h * 100

            # Если это правая или нижняя сторона, инвертируем значение
            if side_info['inv']: val = 100 - val

            self.set_param(self.active_side, max(0, min(49, val)))
            curs = Qt.SizeHorCursor if is_x else Qt.SizeVerCursor
            return curs, True

    def handle_mouse_press(self, pos, rect):
        if self.active_side: self.is_dragging = True

    def handle_mouse_release(self):
        self.is_dragging = False