from PySide6.QtCore import Qt
import cv2
import numpy as np
from .f_base import FilterBase


class FilterEllipse(FilterBase):
    def __init__(self, num, cache_dir, params=None):
        if not params:
            params = {
                "x_pos": 0.0,
                "y_pos": 0.0,
                "diameter": 0.2,
                "aspect": 0.0,
                "thickness": 5,
                "opacity": 0.6
            }
        super().__init__(num, cache_dir, params)
        self.name = "Highlight Ellipse"
        self._is_dragging = False

    def get_params_metadata(self):
        return {
            "x_pos": {"type": "float", "min": -1.0, "max": 1.0, "default": 0.0},
            "y_pos": {"type": "float", "min": -1.0, "max": 1.0, "default": 0.0},
            "diameter": {"type": "float", "min": 0.01, "max": 1.0, "default": 0.2},
            "aspect": {"type": "float", "min": -1.0, "max": 1.0, "default": 0.0},
            "thickness": {"type": "int", "min": 1, "max": 50, "default": 5},
            "opacity": {"type": "float", "min": 0.0, "max": 1.0, "default": 0.6}
        }

    # --- Логика перетаскивания ---

    def handle_mouse_press(self, pos, rect):
        """Проверяем, попал ли клик в область видео"""
        if rect.contains(pos):
            self._is_dragging = True

    def handle_mouse_move(self, pos, rect):
        """Обновляем координаты при движении с зажатой кнопкой"""
        if self._is_dragging:
            self._update_pos_from_mouse(pos, rect)
            # Возвращаем курсор захвата и флаг изменения параметров
            return Qt.ClosedHandCursor, True

        # Если просто навели на видео — показываем перекрестие
        if rect.contains(pos):
            return Qt.CrossCursor, False

        return Qt.ArrowCursor, False

    def handle_mouse_release(self):
        self._is_dragging = False

    def _update_pos_from_mouse(self, pos, rect):
        """Математика перевода экранных координат в диапазон [-1, 1]"""
        # 1. Находим относительную позицию в прямоугольнике (0.0 до 1.0)
        rel_x = (pos.x() - rect.left()) / rect.width()
        rel_y = (pos.y() - rect.top()) / rect.height()

        # 2. Переводим в диапазон [-1, 1]
        val_x = clamp(rel_x * 2 - 1, -1.0, 1.0)
        val_y = clamp(rel_y * 2 - 1, -1.0, 1.0)

        self.set_param("x_pos", val_x)
        self.set_param("y_pos", val_y)

    # --- Отрисовка ---

    def process(self, frame, idx):
        h, w = frame.shape[:2]

        cx = int((self.get_param("x_pos") + 1) / 2 * w)
        cy = int((self.get_param("y_pos") + 1) / 2 * h)

        base_r = (self.get_param("diameter") * w) / 2
        asp = self.get_param("aspect")

        ax_x = int(base_r * (1.0 + max(0, asp)))
        ax_y = int(base_r * (1.0 + max(0, -asp)))

        overlay = frame.copy()
        cv2.ellipse(overlay, (cx, cy), (ax_x, ax_y), 0, 0, 360, (0, 0, 255),
                    self.get_param("thickness"), cv2.LINE_AA)

        alpha = self.get_param("opacity")
        cv2.addWeighted(overlay, alpha, frame, 1 - alpha, 0, frame)
        return frame


def clamp(n, minn, maxn):
    return max(min(maxn, n), minn)