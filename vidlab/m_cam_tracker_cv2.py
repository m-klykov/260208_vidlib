import os
import cv2
import numpy as np

class CameraTrackerCv2Model:

    def __init__(self, w, h, params):
        self.w = w
        self.h = h
        self.params = params

        # Инструменты
        self.fm = FeatureManager(max_corners=200, min_distance=30)
        self.K = self.build_k(w, h, 6.0)  # FOV factor

        # Состояние (Мир)
        self.prev_gray = None
        self.abs_path = []  # Храним [x, y, yaw] для каждого кадра
        self.marks = []
        self.raw_deltas = []  # Для диагностики, если нужно

        # Глобальные координаты (для внутреннего счета)
        self.current_x = 0.0
        self.current_y = 0.0
        self.current_yaw = 0.0
        self.last_frame_idx = 0


    def process_frame(self, frame, idx):
        """Основной шаг вычислений"""
        curr_gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        delta = [0] * 6  # [dyaw, dpitch, droll, tx, ty, tz]

        if self.prev_gray is not None:
            # 1. Трекинг
            self.fm.replenish_fast(self.prev_gray)
            pts_p, pts_c, status = self.fm.update(self.prev_gray, curr_gray)

            # 2. Геометрия
            if pts_p is not None and len(pts_p) > self.params.get("min_features", 50):
                res, mask, success = self.estimate(pts_p, pts_c)
                if success:
                    delta = res
                    self.fm.pts = pts_c[mask].reshape(-1, 1, 2)
                else:
                    self.marks.append(idx)
                    self.fm.pts = pts_c.reshape(-1, 1, 2)
            else:
                self.marks.append(idx)
                self.fm.pts = None

        # 3. Интегрируем дельту в абсолютный путь (инкапсулируем логику _update_abs_path)
        self._integrate_delta(delta)

        self.raw_deltas.append(delta)
        self.prev_gray = curr_gray
        self.last_frame_idx = idx

        return delta


    def _integrate_delta(self, delta):
        dyaw, _, _, tx, ty, tz = delta

        self.current_yaw += dyaw

        # Твоя логика проекции на 2D карту
        dx = tx * np.cos(self.current_yaw) + tz * np.sin(self.current_yaw)
        dy = -tx * np.sin(self.current_yaw) + tz * np.cos(self.current_yaw)

        self.current_x += dx
        self.current_y += dy

        self.abs_path.append([self.current_x, self.current_y, self.current_yaw])


    def get_results(self):
        """То, что запрашивает фильтр для сохранения/отрисовки"""
        return {
            "abs_path": np.array(self.abs_path, dtype=np.float32),
            "raw_deltas": self.raw_deltas,
            "marks": self.marks,
            "ranges": [[0, self.last_frame_idx]],
        }

    def build_k(self, w, h, fov_factor):
        """fov_factor — это тот самый множитель (w * 7)"""
        f = w * fov_factor
        return np.array([
            [f, 0, w / 2],
            [0, f, h / 2],
            [0, 0, 1]
        ], dtype=np.float32)

    def estimate(self, pts_prev, pts_curr):
        E, mask = cv2.findEssentialMat(pts_curr, pts_prev, self.K, method=cv2.RANSAC, threshold=1.0)
        if E is None or E.shape != (3, 3):
            return None, None, False

        _, R, t, mask_pose = cv2.recoverPose(E, pts_curr, pts_prev, self.K)

        yaw = np.arctan2(R[0, 2], R[2, 2])
        pitch = np.arcsin(-R[1, 2])
        roll = np.arctan2(R[1, 0], R[1, 1])

        combined_mask = (mask.flatten() > 0) & (mask_pose.flatten() > 0)
        return [yaw, pitch, roll, t[0][0], t[1][0], t[2][0]], combined_mask, True

class FeatureManager:
    def __init__(self, max_corners=300, min_distance=30):
        self.max_corners = max_corners
        self.min_distance = min_distance
        self.pts = None

    def update(self, prev_gray, curr_gray):
        """Проводит трекинг существующих точек"""
        if self.pts is None or len(self.pts) == 0:
            return None, None, None

        new_pts, status, _ = cv2.calcOpticalFlowPyrLK(prev_gray, curr_gray, self.pts, None)
        if new_pts is None or status is None:
            return None, None, None

        status = status.flatten() == 1
        return self.pts[status], new_pts[status], status

    def replenish(self, frame_gray):
        """Подсеивает новые точки в пустые зоны кадра"""
        new_feats = cv2.goodFeaturesToTrack(frame_gray, self.max_corners, 0.01, self.min_distance)
        if new_feats is None: return

        if self.pts is None or len(self.pts) == 0:
            self.pts = new_feats
            return

        # Фильтр близости (Bucketing/Distance check)
        existing = self.pts.reshape(-1, 2)
        candidates = new_feats.reshape(-1, 2)

        to_add = []
        for cand in candidates:
            if np.min(np.linalg.norm(existing - cand, axis=1)) > self.min_distance:
                to_add.append(cand)

        if to_add:
            new_stack = np.array(to_add, dtype=np.float32).reshape(-1, 1, 2)
            self.pts = np.vstack([self.pts, new_stack])

    def replenish_fast(self, frame_gray):
        # Создаем маску, где 255 - можно искать, 0 - нельзя
        mask = np.full(frame_gray.shape, 255, dtype=np.uint8)

        if self.pts is not None:
            for pt in self.pts:
                # Рисуем черные круги вокруг существующих точек
                cv2.circle(mask, tuple(pt.ravel().astype(int)), self.min_distance, 0, -1)

        # Ищем новые точки только там, где разрешено маской
        new_feats = cv2.goodFeaturesToTrack(frame_gray, self.max_corners, 0.01, self.min_distance, mask=mask)

        if new_feats is not None:
            if self.pts is None or len(self.pts) == 0:
                self.pts = new_feats
            else:
                self.pts = np.vstack([self.pts, new_feats])

    def filter_by_mask(self, mask):
        """Оставляет только подтвержденные инлайеры"""
        if self.pts is not None and mask is not None:
            self.pts = self.pts[mask.flatten() > 0].reshape(-1, 1, 2)

