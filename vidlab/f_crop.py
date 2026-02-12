import cv2
from PySide6.QtGui import QPen, QColor, Qt

from .f_base import FilterBase


class FilterCrop(FilterBase):
    def __init__(self, num, cache_dir, params=None):
        if not params:
           params = {"top": 0, "bottom": 0, "left": 0, "right": 0}

        super().__init__(num, cache_dir, params)
        self.name = "Crop"
        # Дефолтные значения: 0% отступов со всех сторон

        self.active_side = None  # Сторона, на которую навели или которую тянем
        self.is_dragging = False
        self.margin = 10  # Зона чувствительности в пикселях

    def get_params_metadata(self):
        return {
            "top": {"type": "int", "min": 0, "max": 49, "default": 0},
            "bottom": {"type": "int", "min": 0, "max": 49, "default": 0},
            "left": {"type": "int", "min": 0, "max": 49, "default": 0},
            "right": {"type": "int", "min": 0, "max": 49, "default": 0},
            "resize": {"type": "bool", "default": False},
        }

    def process(self, frame, idx):
        h_orig, w_orig = frame.shape[:2]

        # 1. Вычисляем пиксели на основе процентов
        t = int(h_orig * (self.get_param("top") / 100))
        b = int(h_orig * (self.get_param("bottom") / 100))
        l = int(w_orig * (self.get_param("left") / 100))
        r = int(w_orig * (self.get_param("right") / 100))

        # 2. Определяем границы кропа
        y1, y2 = t, h_orig - b
        x1, x2 = l, w_orig - r

        # Защита от некорректных значений
        if y2 <= y1 or x2 <= x1:
            return frame

        # 3. Делаем кроп
        cropped = frame[y1:y2, x1:x2]

        # 4. Если включен параметр zoom — растягиваем до исходного размера
        if self.get_param("resize"):
            # Используем cv2.resize для восстановления исходных размеров
            # INTER_CUBIC дает хороший баланс между четкостью и скоростью
            return cv2.resize(cropped, (w_orig, h_orig), interpolation=cv2.INTER_CUBIC)

        return cropped

    def render_overlay(self, painter, idx, viewport_rect):
        # Рисуем рамку, только если фильтр в фокусе и НЕ активен (как вы и просили)
        # Если фильтр активен, пользователь и так видит результат обрезки
        if self.focused and not self.enabled:
            h = viewport_rect.height()
            w = viewport_rect.width()
            sx = viewport_rect.left()
            sy = viewport_rect.top()

            # Считаем координаты рамки в пикселях виджета
            t = h * (self.get_param("top") / 100)
            b = h * (self.get_param("bottom") / 100)
            l = w * (self.get_param("left") / 100)
            r = w * (self.get_param("right") / 100)

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
            'left': x + w * (self.get_param('left') / 100),
            'right': x + w - (w * (self.get_param('right') / 100)),
            'top': y + h * (self.get_param('top') / 100),
            'bottom': y + h - (h * (self.get_param('bottom') / 100))
        }

    def handle_mouse_move(self, pos, rect):
        if self.enabled: return Qt.ArrowCursor, False

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
            if self.active_side in ['left', 'right']: return Qt.SizeHorCursor, False
            if self.active_side in ['top', 'bottom']: return Qt.SizeVerCursor, False
            return Qt.ArrowCursor, False

        else:
            # Логика перетаскивания (Drag)
            w, h = rect.width(), rect.height()
            x, y = rect.left(), rect.top()

            params_changed = False

            if self.active_side == 'left':
                val = (pos.x() - x) / w * 100
                self.set_param('left', val)
                params_changed = True

            elif self.active_side == 'right':
                val = (x + w - pos.x()) / w * 100
                self.set_param('right', val)
                params_changed = True

            elif self.active_side == 'top':
                val = (pos.y() - y) / h * 100
                self.set_param('top', val)
                params_changed = True

            elif self.active_side == 'bottom':
                val = (y + h - pos.y()) / h * 100
                self.set_param('bottom',val)
                params_changed = True

            curs = Qt.SizeHorCursor if self.active_side in ['left', 'right'] else Qt.SizeVerCursor
            return curs, params_changed

    def handle_mouse_press(self, pos, rect):
        if self.active_side:
            self.is_dragging = True

    def handle_mouse_release(self):
        self.is_dragging = False