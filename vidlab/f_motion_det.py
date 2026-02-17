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
        self.pts_data = []  # Список словарей: {'pt': [x,y], 'age': int}
        self.prev_idx = -1
        self.max_age = 100  # Для нормализации цвета (например, 100 кадров - максимум синевы)

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
        h, w = gray.shape
        result = {
            "tracks": [],  # (old_pt, new_pt, age)
            "born_pts": [],  # [x, y]
            "dead_pts": []  # [x, y]
        }

        # 1. ТРЕКИНГ СУЩЕСТВУЮЩИХ (Живые и Умершие)
        if self.prev_gray is not None and len(self.pts_data) > 0:
            prev_h, prev_w = self.prev_gray.shape
            if h != prev_h or w != prev_w:
                self.prev_gray = None
                self.pts_data = []  # Очищаем старые точки, они больше не валидны
                return result


            # Подготавливаем массив точек для OpenCV
            p0 = np.array([d['pt'] for d in self.pts_data], dtype=np.float32).reshape(-1, 1, 2)

            # Ищем, куда они уехали
            p1, status, _ = cv2.calcOpticalFlowPyrLK(
                self.prev_gray, gray, p0, None,
                winSize=(21, 21), maxLevel=3
            )

            new_pts_data = []
            if p1 is not None and status is not None:
                status = status.flatten()
                for i, st in enumerate(status):
                    old_coord = self.pts_data[i]['pt']
                    if st == 1:
                        new_coord = p1[i].ravel()
                        new_age = self.pts_data[i]['age'] + 1
                        new_pts_data.append({'pt': new_coord, 'age': new_age})
                        result["tracks"].append((old_coord, new_coord, new_age))
                    else:
                        # Точка не нашлась на новом кадре - СМЕРТЬ
                        result["dead_pts"].append(old_coord)

            self.pts_data = new_pts_data

        # 2. ДОСЕВ НОВЫХ (Рождение)
        # Используем параметры из твоего UI
        new_features = cv2.goodFeaturesToTrack(
            gray,
            maxCorners=params["max_corners"],
            qualityLevel=params["quality_level"],
            minDistance=params["min_distance"],
            blockSize=params["block_size"]
        )

        if new_features is not None:
            new_coords = new_features.reshape(-1, 2)
            # Берем текущие координаты, чтобы не сеять вплотную к живым
            current_coords = np.array([d['pt'] for d in self.pts_data]) if self.pts_data else np.array([])

            for nc in new_coords:
                is_far = True
                if current_coords.size > 0:
                    # Простая проверка дистанции
                    dists = np.linalg.norm(current_coords - nc, axis=1)
                    if np.min(dists) < params["min_distance"]:
                        is_far = False

                if is_far:
                    self.pts_data.append({'pt': nc, 'age': 0})
                    result["born_pts"].append(nc)

        self.prev_gray = gray.copy()
        return result

    def process(self, frame, idx):
        # Получаем параметры из UI
        params = {
            "max_corners": self.get_param("max_corners"),
            "quality_level": self.get_param("quality_level"),
            "min_distance": self.get_param("min_distance"),
            "block_size": self.get_param("block_size")
        }

        data = self.analyze_frame(frame, idx, params)

        # 1. Рисуем "Трупы" (Красные крестики)
        # Они вспыхнут на один кадр в месте, где точка потерялась
        for p in data["dead_pts"]:
            x, y = int(p[0]), int(p[1])
            cv2.drawMarker(frame, (x, y), (0, 0, 255), cv2.MARKER_TILTED_CROSS, 7, 1)

        # 2. Рисуем "Новорожденных" (Белые пульсирующие точки)
        for p in data["born_pts"]:
            cv2.circle(frame, (int(p[0]), int(p[1])), 5, (255, 255, 255), 1)

        # 3. Рисуем "Живых" (Градиент Желтый -> Синий)
        for p_old, p_new, age in data["tracks"]:
            t = min(age / 50, 1.0)
            color = (int(255 * t), int(255 * (1 - t)), int(255 * (1 - t)))
            cv2.line(frame, (int(p_old[0]), int(p_old[1])), (int(p_new[0]), int(p_new[1])), color, 1)
            cv2.circle(frame, (int(p_new[0]), int(p_new[1])), 2, color, -1)

        return frame