import os
import cv2
import numpy as np

class CameraTrackerSlamModel:

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

        # --- СИСТЕМА ТОЧЕК ---
        self.next_id = 0
        # active_pts: { id: { 'pt': (x,y), 'start_frame': idx, 'pos_3d': None } }
        self.active_pts = {}
        self.stable_points_3d = []  # Результирующие 3D точки для карты [x, z, age]

        self.last_frame_idx = 0

    def process_frame(self, frame, idx):
        curr_gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        self.last_frame_idx = idx
        rel_pose = np.eye(4, dtype=np.float32)

        if self.prev_gray is not None:
            # 1. Трекинг существующих ID
            tracked_ids, pts_p, pts_c = self._track_with_ids(self.prev_gray, curr_gray)

            # 2. Вычисление позы (как раньше)
            if len(pts_p) > self.params.get("min_features", 50):
                R, t, mask, success = self.estimate_matrix(pts_p, pts_c)
                if success:
                    rel_pose[:3, :3] = R
                    rel_pose[:3, 3] = t.flatten()

                    # Обновляем словарь только инлайерами
                    inlier_ids = [tracked_ids[i] for i in range(len(mask)) if mask[i]]
                    self._update_active_pts(inlier_ids, pts_c[mask.flatten() > 0])
                else:
                    self.active_pts = {}  # Потеря трекинга

            # 3. Подселение новых ID
            self._replenish_with_ids(curr_gray, idx)

            # 4. Попытка триангуляции для "старичков"
            self._triangulate_stable(idx)

        self.current_pose = self.current_pose @ rel_pose
        self.poses.append(self.current_pose.copy())
        self.prev_gray = curr_gray

    def _track_with_ids(self, prev_img, curr_img):
        if not self.active_pts: return [], np.array([]), np.array([])

        ids = list(self.active_pts.keys())
        pts_in = np.array([self.active_pts[i]['pt'] for i in ids], dtype=np.float32).reshape(-1, 1, 2)

        pts_out, status, _ = cv2.calcOpticalFlowPyrLK(prev_img, curr_img, pts_in, None)

        tracked_ids, p_prev, p_curr = [], [], []
        if pts_out is not None:
            status = status.flatten() == 1
            for i, ok in enumerate(status):
                if ok:
                    tracked_ids.append(ids[i])
                    p_prev.append(pts_in[i][0])
                    p_curr.append(pts_out[i][0])

        return tracked_ids, np.array(p_prev), np.array(p_curr)

    def _update_active_pts(self, ids, pts_np):
        # Очищаем словарь от тех, кто не прошел трекинг или RANSAC
        new_active = {}
        for i, pt_id in enumerate(ids):
            if pt_id in self.active_pts:
                data = self.active_pts[pt_id]
                data['pt'] = pts_np[i]
                new_active[pt_id] = data
        self.active_pts = new_active

    def _replenish_with_ids(self, frame_gray, frame_idx):
        mask = np.full(frame_gray.shape, 255, dtype=np.uint8)
        for data in self.active_pts.values():
            cv2.circle(mask, tuple(data['pt'].astype(int)), 30, 0, -1)

        new_feats = cv2.goodFeaturesToTrack(frame_gray, 300 - len(self.active_pts), 0.01, 30, mask=mask)
        if new_feats is not None:
            for f in new_feats:
                self.active_pts[self.next_id] = {
                    'pt': f[0],
                    'start_frame': frame_idx,
                    'pos_3d': None
                }
                self.next_id += 1

    def _triangulate_stable(self, current_frame_idx):
        """Простейшая триангуляция для точек старше 4 кадров"""
        for pt_id, data in self.active_pts.items():
            age = current_frame_idx - data['start_frame']
            if age >= 4 and data['pos_3d'] is None:
                # В идеале тут должна быть честная триангуляция (cv2.triangulatePoints)
                # Для прототипа на "вид сверху" мы можем сэмплировать точку в 3D
                # основываясь на текущей позе и векторе направления.
                # Пока пометим как "стабильную" для визуализации
                pass

    def get_results(self):
        # Извлекаем путь
        path = [[p[0, 3], p[2, 3], np.arctan2(p[0, 2], p[2, 2])] for p in self.poses]

        # Извлекаем стабильные точки для карты
        # [x, z, age]
        stable_points = []
        for pt_id, data in self.active_pts.items():
            age = self.last_frame_idx - data['start_frame']
            if age > 4:
                # Проецируем 2D точку кадра в "типа 3D" для отрисовки на карте
                # В полноценном SLAM тут будут реальные X, Z точки
                # Сейчас для теста используем их относительное положение
                # (Это место мы наполним настоящей триангуляцией в следующем шаге)
                pass

        return {
            "abs_path": np.array(path, dtype=np.float32),
            "marks": self.marks,
            "ranges": [[0, self.last_frame_idx]],
            "active_points_2d": [(d['pt'], self.last_frame_idx - d['start_frame'])
                                 for d in self.active_pts.values()]
        }

    def estimate_matrix(self, pts_prev, pts_curr):
        E, mask = cv2.findEssentialMat(pts_curr, pts_prev, self.K, method=cv2.RANSAC, threshold=0.5)
        if E is None or E.shape != (3, 3): return None, None, None, False
        _, R, t, mask_p = cv2.recoverPose(E, pts_curr, pts_prev, self.K)
        return R, t, (mask.flatten() > 0) & (mask_p.flatten() > 0), True

    def build_k(self, w, h, fov):
        f = w * fov
        return np.array([[f, 0, w / 2], [0, f, h / 2], [0, 0, 1]], dtype=np.float32)
