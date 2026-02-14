import cv2
import numpy as np
from .f_base import FilterBase


class FilterLevels(FilterBase):
    def __init__(self, num, cache_dir, params=None):
        if not params:
           params = {"black": 0, "white": 255}

        super().__init__(num, cache_dir, params)
        self.name = "Levels"
        # Дефолтные параметры


    def get_params_metadata(self):
        return {
            "act_in": {"type": "in_out", "default": -1},  # Наш триггер для UI
            "black": {"type": "int", "min": 0, "max": 254, "default": 0},
            "white": {"type": "int", "min": 1, "max": 255, "default": 255}
        }

    def process(self, frame, idx):
        black = self.get_param("black")
        white = self.get_param("white")

        if black == 0 and white == 255:
            return frame

        # Применяем уровни через таблицу поиска (LUT) для скорости
        diff = white - black if white > black else 1
        table = np.array([
            np.clip((i - black) / diff * 255, 0, 255)
            for i in range(256)
        ]).astype("uint8")

        return cv2.LUT(frame, table)