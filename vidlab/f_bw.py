import cv2
from .f_base import FilterBase

class FilterBW(FilterBase):
    def __init__(self, num, cache_dir, params=None):
        super().__init__(num, cache_dir, params)
        self.name = "Black and White"

    def get_params_metadata(self):
        # Возвращаем пустой словарь — настроек нет
        return {
            "act_in": {"type": "in_out", "default": -1},  # Наш триггер для UI

        }

    def process(self, frame, idx):
        # Конвертируем в градации серого
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)

        # Чтобы не ломать цепочку (следующий фильтр может ждать 3 канала),
        # конвертируем обратно в BGR, но картинка останется серой
        return cv2.cvtColor(gray, cv2.COLOR_GRAY2BGR)