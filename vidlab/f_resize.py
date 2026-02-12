import cv2
from PySide6.QtCore import QRectF
from PySide6.QtGui import QPen, QColor, Qt

from .f_base import FilterBase


class FilterResize(FilterBase):
    def __init__(self, num, cache_dir, params=None):
        if not params:
           params = {}

        super().__init__(num, cache_dir, params)
        self.name = "Resize"

    def get_params_metadata(self):
        return {
            "target_w": {"type": "int_spin", "min": 1, "max": 7680, "default": 1920},
            "target_h": {"type": "int_spin", "min": 1, "max": 4320, "default": 1080},
            "offset": {"type": "float", "min": -1.0, "max": 1.0, "default": 0.0},
            "interpolation": {"type": "list", "values": ["Linear", "Cubic", "Nearest"], "default": "Cubic"}
        }

    def process(self, frame, idx):
        h_orig, w_orig = frame.shape[:2]
        tw = self.get_param("target_w")
        th = self.get_param("target_h")
        offset = self.get_param("offset")

        # 1. Вычисляем масштаб для заполнения (Fill)
        # Нам нужно покрыть обе стороны, поэтому берем MAX
        scale = max(tw / w_orig, th / h_orig)

        # Новые размеры после масштабирования (одна сторона будет равна целевой, другая больше)
        nw = int(w_orig * scale)
        nh = int(h_orig * scale)

        # 2. Масштабируем
        interp_map = {
            "Linear": cv2.INTER_LINEAR,
            "Cubic": cv2.INTER_CUBIC,
            "Nearest": cv2.INTER_NEAREST
        }
        interp = interp_map.get(self.get_param("interpolation"), cv2.INTER_LINEAR)

        resized = cv2.resize(frame, (nw, nh), interpolation=interp)

        # 2. Вычисление центра с учетом смещения
        # Доступный запас для сдвига (в пикселях масштабированного кадра)
        dw = nw - tw
        dh = nh - th

        # Базовый центр (0.0 дает точно середину)
        # Формула: (Запас / 2) + (Запас / 2 * коэффициент)
        # Превращается в: Запас / 2 * (1 + offset)
        x_start = int((dw / 2) * (1 + offset))
        y_start = int((dh / 2) * (1 + offset))

        # Ограничиваем, чтобы не выйти за границы массива при расчетах
        x_start = max(0, min(x_start, dw))
        y_start = max(0, min(y_start, dh))

        return resized[y_start: y_start + th, x_start: x_start + tw]

    def render_overlay(self, painter, idx, viewport_rect):
        if self.focused and not self.enabled:
            h_view, w_view = viewport_rect.height(), viewport_rect.width()
            sx, sy = viewport_rect.left(), viewport_rect.top()
            tw, th = self.get_param("target_w"), self.get_param("target_h")
            offset = self.get_param("offset")

            if tw <= 0 or th <= 0: return
            target_aspect = tw / th
            view_aspect = w_view / h_view

            # Определяем размер видимой области на экране
            if view_aspect > target_aspect:
                vis_w, vis_h = h_view * target_aspect, h_view
                # Считаем смещение по горизонтали
                dw = w_view - vis_w
                l = (dw / 2) * (1 + offset)
                t = 0
            else:
                vis_w, vis_h = w_view, w_view / target_aspect
                # Считаем смещение по вертикали
                dh = h_view - vis_h
                l = 0
                t = (dh / 2) * (1 + offset)

            # Рисуем рамку
            pen = QPen(QColor(0, 150, 255), 2, Qt.DashLine)
            painter.setPen(pen)
            rect_to_draw = QRectF(sx + l, sy + t, vis_w, vis_h)
            painter.drawRect(rect_to_draw)

            # Затемнение (теперь динамическое)
            painter.setBrush(QColor(0, 0, 0, 150))
            painter.setPen(Qt.NoPen)

            # Четыре прямоугольника вокруг Safe Area
            painter.drawRect(QRectF(sx, sy, l, h_view))  # Слева
            painter.drawRect(QRectF(sx + l + vis_w, sy, w_view - l - vis_w, h_view))  # Справа
            painter.drawRect(QRectF(sx + l, sy, vis_w, t))  # Сверху
            painter.drawRect(QRectF(sx + l, sy + t + vis_h, vis_w, h_view - t - vis_h))  # Снизу