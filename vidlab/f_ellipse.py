import cv2
import numpy as np
from .f_base import FilterBase


class FilterEllipse(FilterBase):
    def __init__(self, num, cache_dir, params=None):
        if not params:
            params = {
                "x_pos": 0.0,  # -1 (лево) до 1 (право)
                "y_pos": 0.0,  # -1 (верх) до 1 (низ)
                "diameter": 0.2,  # Относительно ширины кадра
                "aspect": 0.0,  # -1 (вертикальный) до 1 (горизонтальный)
                "thickness": 5,  # Толщина линии в пикселях
                "opacity": 0.6  # Прозрачность 0.0 - 1.0
            }
        super().__init__(num, cache_dir, params)
        self.name = "Ellipse"

    def get_params_metadata(self):
        return {
            "x_pos": {"type": "float", "min": -1.0, "max": 1.0, "default": 0.0},
            "y_pos": {"type": "float", "min": -1.0, "max": 1.0, "default": 0.0},
            "diameter": {"type": "float", "min": 0.01, "max": 1.0, "default": 0.2},
            "aspect": {"type": "float", "min": -1.0, "max": 1.0, "default": 0.0},
            "thickness": {"type": "int", "min": 1, "max": 50, "default": 5},
            "opacity": {"type": "float", "min": 0.0, "max": 1.0, "default": 0.6}
        }

    def process(self, frame, idx):
        h, w = frame.shape[:2]

        # 1. Вычисляем центр в пикселях
        # Перевод из [-1, 1] в [0, w] или [0, h]
        center_x = int((self.get_param("x_pos") + 1) / 2 * w)
        center_y = int((self.get_param("y_pos") + 1) / 2 * h)

        # 2. Вычисляем радиусы эллипса
        base_radius = (self.get_param("diameter") * w) / 2
        aspect = self.get_param("aspect")

        # Если aspect > 0, растягиваем по X, если < 0 - по Y
        axes_x = int(base_radius * (1.0 + max(0, aspect)))
        axes_y = int(base_radius * (1.0 + max(0, -aspect)))

        # 3. Рисуем на отдельном слое для прозрачности
        overlay = frame.copy()
        color = (0, 0, 255)  # BGR - Чистый красный
        thickness = self.get_param("thickness")

        cv2.ellipse(
            overlay,
            (center_x, center_y),
            (axes_x, axes_y),
            0, 0, 360,
            color,
            thickness,
            cv2.LINE_AA
        )

        # 4. Смешиваем оригинал и слой с эллипсом
        alpha = self.get_param("opacity")
        cv2.addWeighted(overlay, alpha, frame, 1 - alpha, 0, frame)

        return frame