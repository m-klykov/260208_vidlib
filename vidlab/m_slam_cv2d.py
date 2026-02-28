import cv2
import numpy as np
from .m_slam_base import SlamBaseModel


class SlamCv2dModel(SlamBaseModel):
    def _add_system_params(self):
        # Внутренние параметры, не выносимые в UI
        self.min_track_points = 10
        self.optical_flow_params = dict(winSize=(21, 21), maxLevel=3)
        self.speed_damp = 0.95  # Сглаживание скорости

    def get_params_metadata(self) -> dict:
        """Метаданные параметров для UI фильтра"""
        return {
            "roi_left": {"type": "float", "min": 0.0, "max": 0.5, "default": 0.0},
            "roi_right": {"type": "float", "min": 0.5, "max": 1.0, "default": 1.0},
            "roi_top": {"type": "float", "min": 0.0, "max": 0.5, "default": 0.0},
            "roi_bottom": {"type": "float", "min": 0.5, "max": 1.0, "default": 1.0},
            "max_corners": {"type": "int", "min": 50, "max": 1000, "default": 400},
            "min_distance": {"type": "int", "min": 5, "max": 100, "default": 25},
            "fov_h": {"type": "float", "min": 30.0, "max": 160.0, "default": 111.0},
            "smooth_factor": {"type": "float", "min": 0.1, "max": 2.0, "default": 0.8},
            "speed_k": {"type": "float", "min": 0.001, "max": 1.0, "default": 0.05}
        }

    def _process_core(self, frame, idx):
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        h, w = gray.shape
        cx, cy = w // 2, h // 2

        # Расчет границ ROI в пикселях
        x1 = int(w * self.get_param("roi_left", 0.0))
        x2 = int(w * self.get_param("roi_right", 1.0))
        y1 = int(h * self.get_param("roi_top", 0.0))
        y2 = int(h * self.get_param("roi_bottom", 1.0))

        # 1. ТРЕКИНГ
        if self.prev_gray is not None and len(self.pts) > self.min_track_points:
            p0 = np.array([d['pt'] for d in self.pts], dtype=np.float32).reshape(-1, 1, 2)
            p1, status, _ = cv2.calcOpticalFlowPyrLK(self.prev_gray, gray, p0, None, **self.optical_flow_params)

            if p1 is not None:

                p1_flat = p1.reshape(-1, 2)
                # Проверяем статус и попадание в ROI для каждой точки
                in_roi = (p1_flat[:, 0] >= x1) & (p1_flat[:, 0] <= x2) & \
                         (p1_flat[:, 1] >= y1) & (p1_flat[:, 1] <= y2)

                status_bool = status.flatten() == 1

                good = (status.flatten() == 1) & in_roi

                if np.any(good):
                    p0_g, p1_g = p0[good].reshape(-1, 2), p1[good].reshape(-1, 2)
                    deltas = p1_g - p0_g

                    # --- РАСЧЕТ YAW (Балансировка) ---
                    sigma = w / 8
                    dist_x = p0_g[:, 0] - cx
                    weights = np.exp(-(dist_x ** 2) / (2 * sigma ** 2))

                    l_m, r_m = dist_x < 0, dist_x >= 0

                    def get_w_dx(m):
                        return np.sum(deltas[m, 0] * weights[m]) / (np.sum(weights[m]) + 1e-8) if np.any(m) else 0

                    dx = (get_w_dx(l_m) + get_w_dx(r_m)) / 2.0 if (np.any(l_m) and np.any(r_m)) else get_w_dx(
                        l_m or r_m)

                    # --- РАСЧЕТ PITCH / ROLL ---
                    dy = np.sum(deltas[:, 1] * weights) / (np.sum(weights) + 1e-8)

                    M, _ = cv2.estimateAffinePartial2D(p0_g, p1_g)
                    d_roll_deg = 0
                    if M is not None:
                        d_roll_deg = np.degrees(np.arctan2(M[1, 0], M[0, 0]))

                    # Интеграция углов
                    px_per_deg = w / self.get_param("fov_h")
                    sf = self.get_param("smooth_factor")

                    # dx / px_per_deg — это смещение в градусах
                    # Поворот вправо (dx < 0) должен увеличивать yaw
                    self.curr_yaw -= (dx / px_per_deg) * sf
                    # Наклон вниз (dy < 0) должен увеличивать pitch (нос опускается)
                    self.curr_pitch += (dy / px_per_deg) * sf
                    self.curr_roll -= d_roll_deg * sf

                    # Утечка углов к горизонту (стабилизация)
                    self.curr_pitch *= 0.95
                    self.curr_roll *= 0.95

                    # --- РАСЧЕТ СКОРОСТИ (Step Size) ---
                    r0_vecs = p0_g - np.array([cx, cy])
                    corrected_deltas = deltas - np.array([dx, dy])
                    dist_sq = np.sum(r0_vecs ** 2, axis=1)
                    v_mask = dist_sq > 25

                    step_size = 0
                    if np.any(v_mask):
                        rad_deltas = np.sum(corrected_deltas[v_mask] * r0_vecs[v_mask], axis=1) / np.sqrt(
                            dist_sq[v_mask])
                        raw_vel = np.median(rad_deltas)
                        self.curr_velocity = self.speed_damp * self.curr_velocity + (1 - self.speed_damp) * raw_vel
                        step_size = self.curr_velocity * self.get_param("speed_k")

                    # Обновление позиции в пространстве
                    yaw_rad = np.radians(self.curr_yaw)
                    self.curr_x += step_size * np.sin(yaw_rad)
                    self.curr_y += step_size * np.cos(yaw_rad)

                # --- ОБНОВЛЕНИЕ СПИСКА ТОЧЕК (вынесено из if np.any) ---
                new_pts = []
                for i in range(len(self.pts)):
                    # Оставляем точку только если она в ROI и трекается
                    if status_bool[i] and in_roi[i]:
                        new_pts.append({
                            'pt': p1_flat[i],
                            'age': self.pts[i]['age'] + 1
                        })
                self.pts = new_pts

        # 2. ДОСЕВ ТОЧЕК
        self._replenish_features(gray,(x1, y1, x2, y2))

        self.prev_gray = gray.copy()

    def _replenish_features(self, gray, roi_coords=None):

        x1, y1, x2, y2 = roi_coords

        # Создаем черную маску размером с кадр
        mask = np.zeros_like(gray)
        # Рисуем белый прямоугольник там, где МОЖНО искать точки
        mask[y1:y2, x1:x2] = 255

        new_feats = cv2.goodFeaturesToTrack(
            gray,
            maxCorners=self.get_param("max_corners"),
            qualityLevel=0.01,
            minDistance=self.get_param("min_distance"),
            mask=mask  # Передаем маску
        )
        if new_feats is None: return

        new_coords = new_feats.reshape(-1, 2)
        if not self.pts:
            for nc in new_coords:
                self.pts.append({'pt': nc, 'age': 0})
            return

        current_coords = np.array([d['pt'] for d in self.pts])
        for nc in new_coords:
            dists = np.linalg.norm(current_coords - nc, axis=1)
            if np.min(dists) > self.get_param("min_distance"):
                self.pts.append({'pt': nc, 'age': 0})
                # Обновляем массив координат, чтобы новые точки не кучковались
                current_coords = np.vstack([current_coords, nc])

    # Геттеры для фильтра
    def get_points(self):
        return self.pts