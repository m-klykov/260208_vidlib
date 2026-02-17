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
        self.prev_pts = None
        self.prev_idx = -1

    def get_params_metadata(self):
        return {
            "max_corners": {"type": "int", "min": 10, "max": 2000, "default": 400},
            "quality_level": {"type": "float", "min": 0.001, "max": 0.1, "default": 0.01},
            "min_distance": {"type": "int", "min": 1, "max": 100, "default": 20},
            "block_size": {"type": "int", "min": 3, "max": 15, "default": 3},
            "show_nums": {"type": "bool", "default": False},
        }

    def analyze_frame(self, frame, idx, params):
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        result = {
            "matched_pts": [],
            "new_pts": [],
            "lost_pts": []
        }

        # --- ШАГ 1: ТРЕКИНГ СУЩЕСТВУЮЩИХ ТОЧЕК ---
        active_pts_after_flow = []
        if self.prev_gray is not None and self.prev_pts is not None:
            curr_pts, status, _ = cv2.calcOpticalFlowPyrLK(
                self.prev_gray, gray, self.prev_pts, None,
                winSize=(21, 21), maxLevel=3
            )

            for i, st in enumerate(status):
                p_old = self.prev_pts[i].ravel()
                if st == 1:
                    p_new = curr_pts[i].ravel()
                    result["matched_pts"].append((p_old, p_new))
                    active_pts_after_flow.append(p_new)
                else:
                    result["lost_pts"].append(p_old)

        # --- ШАГ 2: ПОИСК КАНДИДАТОВ В НОВЫЕ ТОЧКИ ---
        raw_new_features = cv2.goodFeaturesToTrack(
            gray,
            maxCorners=params["max_corners"],
            qualityLevel=params["quality_level"],
            minDistance=params["min_distance"],
            blockSize=params["block_size"]
        )

        # --- ШАГ 3: ФИЛЬТРАЦИЯ И ПОПОЛНЕНИЕ ---
        # Мы добавляем новые точки только там, где "пусто"
        final_next_pts = [p for p in active_pts_after_flow]

        if raw_new_features is not None:
            for feat in raw_new_features:
                new_p = feat.ravel()

                # Проверяем, нет ли уже живой точки рядом с этим кандидатом
                is_too_close = False
                if len(final_next_pts) > 0:
                    # Считаем расстояния до всех существующих точек
                    dists = np.linalg.norm(np.array(final_next_pts) - new_p, axis=1)
                    if np.min(dists) < params["min_distance"]:
                        is_too_close = True

                if not is_too_close:
                    final_next_pts.append(new_p)
                    result["new_pts"].append(new_p)

        # --- ШАГ 4: ОБНОВЛЕНИЕ ПАМЯТИ ---
        self.prev_gray = gray.copy()
        if len(final_next_pts) > 0:
            self.prev_pts = np.array(final_next_pts, dtype=np.float32).reshape(-1, 1, 2)
        else:
            self.prev_pts = None

        self.prev_idx = idx
        return result

    def process(self, frame, idx):
        # Получаем параметры из UI
        params = {
            "max_corners": self.get_param("max_corners"),
            "quality_level": self.get_param("quality_level"),
            "min_distance": self.get_param("min_distance"),
            "block_size": self.get_param("block_size")
        }

        # Вызываем наш анализатор (экземпляр MotionAnalyzer должен быть в self)
        data = self.analyze_frame(frame, idx, params)

        # ОТРИСОВКА

        # 1. Рисуем векторы движения (желтые линии)
        for p_old, p_new in data["matched_pts"]:
            p1 = (int(p_old[0]), int(p_old[1]))
            p2 = (int(p_new[0]), int(p_new[1]))
            cv2.line(frame, p1, p2, (0, 255, 255), 1, cv2.LINE_AA)
            cv2.circle(frame, p2, 2, (0, 255, 255), -1)

        # 2. Рисуем потерянные точки (красные)
        for p in data["lost_pts"]:
            cv2.circle(frame, (int(p[0]), int(p[1])), 3, (0, 0, 255), 1)

        # 3. Рисуем новые найденные точки (зеленые)
        for p in data["new_pts"]:
            cv2.circle(frame, (int(p[0]), int(p[1])), 2, (0, 255, 0), -1)

        return frame