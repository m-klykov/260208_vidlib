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

            # Считаем координаты рамки в пикселях виджета
            t = h * (self.params.get("top", 0) / 100)
            b = h * (self.params.get("bottom", 0) / 100)
            l = w * (self.params.get("left", 0) / 100)
            r = w * (self.params.get("right", 0) / 100)

            # Настройка пера (красный пунктир)
            pen = QPen(QColor(255, 0, 0), 2, Qt.DashLine)
            painter.setPen(pen)

            # Рисуем прямоугольник обрезки
            painter.drawRect(l, t, w - l - r, h - t - b)

            # Затемняем области, которые будут отрезаны
            painter.fillRect(0, 0, w, t, QColor(0, 0, 0, 100))  # Top
            painter.fillRect(0, h - b, w, b, QColor(0, 0, 0, 100))  # Bottom
            painter.fillRect(0, t, l, h - t - b, QColor(0, 0, 0, 100))  # Left
            painter.fillRect(w - r, t, r, h - t - b, QColor(0, 0, 0, 100))  # Right