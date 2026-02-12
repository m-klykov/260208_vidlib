import cv2
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
            "target_w": {"type": "int", "min": 1, "max": 7680, "default": 1920},
            "target_h": {"type": "int", "min": 1, "max": 4320, "default": 1080},
            "interpolation": {"type": "list", "values": ["Linear", "Cubic", "Nearest"], "default": "Cubic"}
        }

    def process(self, frame, idx):
        h_orig, w_orig = frame.shape[:2]
        tw = self.get_param("target_w")
        th = self.get_param("target_h")

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

        # 3. Вырезаем центральную часть (Center Crop)
        # Находим координаты начала обрезки
        x_start = (nw - tw) // 2
        y_start = (nh - th) // 2

        # Срез массива: [y : y+h, x : x+w]
        cropped = resized[y_start: y_start + th, x_start: x_start + tw]

        return cropped