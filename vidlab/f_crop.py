import cv2
from PySide6.QtGui import QPen, QColor, Qt

from .f_base import FilterBase


class FilterCrop(FilterBase):
    def __init__(self, num, cache_dir, params=None):
        super().__init__(num, cache_dir, params)
        self.name = "Crop"
        # Дефолтные значения: 0% отступов со всех сторон
        if not self.params:
            self.params = {"top": 0, "bottom": 0, "left": 0, "right": 0}

        self.active_side = None  # Сторона, на которую навели или которую тянем
        self.is_dragging = False
        self.margin = 10  # Зона чувствительности в пикселях

    def get_params_metadata(self):
        return {
            "top": {"type": "int", "min": 0, "max": 49, "default": 0},
            "bottom": {"type": "int", "min": 0, "max": 49, "default": 0},
            "left": {"type": "int", "min": 0, "max": 49, "default": 0},
            "right": {"type": "int", "min": 0, "max": 49, "default": 0}
        }

    def process(self, frame, idx):
        h, w = frame.shape[:2]

        # Вычисляем пиксели на основе процентов
        t = int(h * (self.params.get("top", 0) / 100))
        b = int(h * (self.params.get("bottom", 0) / 100))
        l = int(w * (self.params.get("left", 0) / 100))
        r = int(w * (self.params.get("right", 0) / 100))

        # Определяем новые границы (минимум 1 пиксель, чтобы не схлопнулось в 0)
        y1, y2 = t, h - b
        x1, x2 = l, w - r

        if y2 <= y1 or x2 <= x1:
            return frame  # Если обрезали всё, возвращаем оригинал

        # Срез массива (crop)
        return frame[y1:y2, x1:x2]

    def render_overlay(self, painter, idx, viewport_rect):
        # Рисуем рамку, только если фильтр в фокусе и НЕ активен (как вы и просили)
        # Если фильтр активен, пользователь и так видит результат обрезки
        if self.focused and not self.enabled:
            h = viewport_rect.height()
            w = viewport_rect.width()
            sx = viewport_rect.left()
            sy = viewport_rect.top()

            # Считаем координаты рамки в пикселях виджета
            t = h * (self.params.get("top", 0) / 100)
            b = h * (self.params.get("bottom", 0) / 100)
            l = w * (self.params.get("left", 0) / 100)
            r = w * (self.params.get("right", 0) / 100)

            # Настройка пера (красный пунктир)
            pen = QPen(QColor(255, 0, 0), 2, Qt.DashLine)
            painter.setPen(pen)

            # Рисуем прямоугольник обрезки
            painter.drawRect(sx + l, #viewport_rect.left +
                             sy + t, # viewport_rect.top +
                             w - l - r, h - t - b)

            # Затемняем области, которые будут отрезаны
            painter.fillRect(sx, sy, w, t, QColor(0, 0, 0, 100))  # Top
            painter.fillRect(sx, sy + h - b, w, b, QColor(0, 0, 0, 100))  # Bottom
            painter.fillRect(sx, sy + t, l, h - t - b, QColor(0, 0, 0, 100))  # Left
            painter.fillRect(sx + w - r, sy + t, r, h - t - b, QColor(0, 0, 0, 100))
            # Right

    def _get_coords(self, rect):
        """Вспомогательный метод для получения координат линий в пикселях"""
        w, h = rect.width(), rect.height()
        x, y = rect.left(), rect.top()
        return {
            'left': x + w * (self.params['left'] / 100),
            'right': x + w - (w * (self.params['right'] / 100)),
            'top': y + h * (self.params['top'] / 100),
            'bottom': y + h - (h * (self.params['bottom'] / 100))
        }

    def handle_mouse_move(self, pos, rect):
        if self.enabled: return Qt.ArrowCursor

        coords = self._get_coords(rect)

        if not self.is_dragging:
            # Проверяем наведение (Hover)
            self.active_side = None
            if abs(pos.x() - coords['left']) < self.margin:
                self.active_side = 'left'
            elif abs(pos.x() - coords['right']) < self.margin:
                self.active_side = 'right'
            elif abs(pos.y() - coords['top']) < self.margin:
                self.active_side = 'top'
            elif abs(pos.y() - coords['bottom']) < self.margin:
                self.active_side = 'bottom'

            # Возвращаем нужный курсор
            if self.active_side in ['left', 'right']: return Qt.SizeHorCursor
            if self.active_side in ['top', 'bottom']: return Qt.SizeVerCursor
            return Qt.ArrowCursor

        else:
            # Логика перетаскивания (Drag)
            w, h = rect.width(), rect.height()
            x, y = rect.left(), rect.top()

            if self.active_side == 'left':
                val = (pos.x() - x) / w * 100
                self.params['left'] = max(0, min(val, 100 - self.params['right'] - 1))
            elif self.active_side == 'right':
                val = (x + w - pos.x()) / w * 100
                self.params['right'] = max(0, min(val, 100 - self.params['left'] - 1))
            elif self.active_side == 'top':
                val = (pos.y() - y) / h * 100
                self.params['top'] = max(0, min(val, 100 - self.params['bottom'] - 1))
            elif self.active_side == 'bottom':
                val = (y + h - pos.y()) / h * 100
                self.params['bottom'] = max(0, min(val, 100 - self.params['top'] - 1))

            return Qt.SizeHorCursor if self.active_side in ['left', 'right'] else Qt.SizeVerCursor

    def handle_mouse_press(self, pos, rect):
        if self.active_side:
            self.is_dragging = True

    def handle_mouse_release(self):
        self.is_dragging = False