from vidlab.f_base import FilterBase
import cv2
import numpy as np
from PySide6.QtGui import QPen, QColor

class FilterMotionDetector(FilterBase):
    def __init__(self, num, cache_dir, params=None):
        default_params = {
            "max_corners": 400,
            "quality_level": 0.01,
            "min_distance": 20,
            "block_size": 3,
            "show_vectors": True,
            "window_size": 5,  # Сравниваем с кадром N - window_size
        }
        super().__init__(num, cache_dir, default_params)
        self.name = "Motion Detector"

        # Память для хранения истории фичей
        self.prev_gray = None
        self.points_history = {}  # frame_idx -> points
        self.last_processed_idx = -1

    def get_params_metadata(self):
        return {
            "max_corners": {"type": "int", "min": 10, "max": 2000, "default": 400},
            "quality_level": {"type": "float", "min": 0.001, "max": 0.1, "default": 0.01},
            "min_distance": {"type": "int", "min": 1, "max": 100, "default": 20},
            "block_size": {"type": "int", "min": 3, "max": 15, "default": 3},
        }

    def process(self, frame, idx):
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)

        # 1. Детектируем точки на текущем кадре
        pts = cv2.goodFeaturesToTrack(
            gray,
            maxCorners=self.get_param("max_corners"),
            qualityLevel=self.get_param("quality_level"),
            minDistance=self.get_param("min_distance"),
            blockSize=self.get_param("block_size")
        )

        if pts is not None:
            # Раскрашиваем точки: чем выше качество точки, тем она "зеленее"
            # (goodFeaturesToTrack не возвращает оценки напрямую, но мы можем их визуализировать)
            for i, p in enumerate(pts):
                x, y = p.ravel()
                # Рисуем кружок
                cv2.circle(frame, (int(x), int(y)), 4, (0, 255, 0), -1)
                # Добавляем индекс точки для отладки
                # cv2.putText(frame, str(i), (int(x), int(y)-5), cv2.FONT_HERSHEY_SIMPLEX, 0.3, (255,255,255))

        # Сохраняем состояние для следующего вызова
        self.prev_gray = gray.copy()
        self.last_processed_idx = idx

        return frame