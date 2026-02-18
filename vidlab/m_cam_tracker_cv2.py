import os
import cv2
import numpy as np

class CameraTrackerCv2Model:

    def __init__(self, w, h, params):
        self.w = w
        self.h = h
        self.params = params

        # Инструменты
        self.K = self.build_k(w, h, 6.0)  # FOV factor

        # Состояние (Мир)
        self.prev_gray = None
        # Список всех матриц 4x4 для каждого кадра
        self.poses = []
        # Текущая абсолютная позиция (Мировая матрица)
        self.current_pose = np.eye(4, dtype=np.float32)
        self.marks = []

        self.max_corners = 300
        self.min_distance = 30
        self.pts = None

        self.last_frame_idx = 0

    def process_frame(self, frame, idx):
        curr_gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)

        # Матрица относительного движения (по умолчанию - стоим)
        rel_pose = np.eye(4, dtype=np.float32)

        if self.prev_gray is not None:
            self.pts_replenish(self.prev_gray)
            pts_p, pts_c, status = self.pts_update(self.prev_gray, curr_gray)

            if pts_p is not None and len(pts_p) > self.params.get("min_features", 50):
                # Теперь estimate возвращает готовую матрицу 4x4
                R, t, mask, success = self.estimate_matrix(pts_p, pts_c)
                if success:
                    rel_pose[:3, :3] = R
                    rel_pose[:3, 3] = t.flatten()
                    self.pts = pts_c[mask].reshape(-1, 1, 2)
                else:
                    self.marks.append(idx)
                    self.fm.pts = pts_c.reshape(-1, 1, 2)
            else:
                self.marks.append(idx)
                self.pts = None

        # Интегрируем: умножаем текущую позу на относительное движение
        # Важно: умножаем справа (Local-to-Global)
        self.current_pose = self.current_pose @ rel_pose

        # Сохраняем копию текущей матрицы в историю
        self.poses.append(self.current_pose.copy())

        self.prev_gray = curr_gray
        self.last_frame_idx = idx


    def estimate_matrix(self, pts_prev, pts_curr):
        """Возвращает R и t напрямую"""
        E, mask = cv2.findEssentialMat(pts_curr, pts_prev, self.K, method=cv2.RANSAC, threshold=1.0)
        if E is None or E.shape != (3, 3):
            return None, None, None, False

        _, R, t, mask_pose = cv2.recoverPose(E, pts_curr, pts_prev, self.K)
        combined_mask = (mask.flatten() > 0) & (mask_pose.flatten() > 0)
        return R, t, combined_mask, True

    def get_results(self):
        """Генерирует abs_path и дельты из сохраненных матриц"""
        abs_path = []
        raw_deltas = []

        for i in range(len(self.poses)):
            T = self.poses[i]

            # 1. Извлекаем координаты X, Z (для вида сверху)
            # В SLAM по умолчанию: Z - вперед, X - право, Y - низ.
            tx = T[0, 3]
            tz = T[2, 3]

            # 2. Извлекаем Yaw (угол поворота вокруг оси Y)
            # Из матрицы вращения R:
            yaw = np.arctan2(T[0, 2], T[2, 2])

            abs_path.append([tx, tz, yaw])

            # 3. Для диагностики (дельты между кадрами)
            if i > 0:
                # Находим относительную матрицу между i и i-1
                rel = np.linalg.inv(self.poses[i - 1]) @ self.poses[i]
                r_yaw = np.arctan2(rel[0, 2], rel[2, 2])
                raw_deltas.append([r_yaw, 0, 0, rel[0, 3], rel[1, 3], rel[2, 3]])
            else:
                raw_deltas.append([0] * 6)

        return {
            "abs_path": np.array(abs_path, dtype=np.float32),
            "raw_deltas": raw_deltas,
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

    def pts_update(self, prev_gray, curr_gray):
        """Проводит трекинг существующих точек"""
        if self.pts is None or len(self.pts) == 0:
            return None, None, None

        new_pts, status, _ = cv2.calcOpticalFlowPyrLK(prev_gray, curr_gray, self.pts, None)
        if new_pts is None or status is None:
            return None, None, None

        status = status.flatten() == 1
        return self.pts[status], new_pts[status], status

    def pts_replenish(self, frame_gray):
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

