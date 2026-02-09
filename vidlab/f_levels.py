import cv2
import numpy as np
from .f_base import FilterBase


class FilterLevels(FilterBase):
    def __init__(self, num, cache_dir, params=None):
        super().__init__(num, cache_dir, params)
        self.name = "Levels"
        # Дефолтные параметры
        if not self.params:
            self.params = {"black": 0, "white": 255}

    def get_params_metadata(self):
        return {
            "black": {"type": "int", "min": 0, "max": 254, "default": 0},
            "white": {"type": "int", "min": 1, "max": 255, "default": 255}
        }

    def process(self, frame, idx):
        black = self.params.get("black", 0)
        white = self.params.get("white", 255)

        if black == 0 and white == 255:
            return frame

        # Применяем уровни через таблицу поиска (LUT) для скорости
        diff = white - black if white > black else 1
        table = np.array([
            np.clip((i - black) / diff * 255, 0, 255)
            for i in range(256)
        ]).astype("uint8")

        return cv2.LUT(frame, table)