import os
import cv2
import numpy as np

class CameraTrackerSlamModel:

    def __init__(self, w, h, params):
        self.w = w
        self.h = h
        self.params = params

        # Инструменты
        self.K = self.build_k(w, h, 111)  # FOV factor

        # Состояние (Мир)
        self.prev_gray = None
        # Список всех матриц 4x4 для каждого кадра
        self.poses = []
        # Текущая абсолютная позиция (Мировая матрица)
        self.current_pose = np.eye(4, dtype=np.float32)
        self.marks = []

        self.max_corners = 300
        self.min_distance = 20

        self.slam_config = {
            "min_triangulation_age": 5,  # Минимальный возраст для попытки
            "min_parallax_dist": 0.05,  # Минимальный "базис" (смещение камеры)
            "z_min": 1.0,  # Ближняя отсечка (чтобы не липло к носу)
            "z_max": 80.0,  # Дальняя отсечка (шумные точки в бесконечности)
            "max_active_pts": 400  # Целевое количество точек в трекинге
        }

        # Расширяем конфиг для управления
        self.slam_config.update({
            "quality_level": 0.01,  # Ручка 1
            "parallax_ratio_target": 0.05,  # Ручка 2 (целевое качество триангуляции)
            "success_rate_history": []
        })

        # --- СИСТЕМА ТОЧЕК ---
        self.next_id = 0
        # active_pts: { id: { 'pt': (x,y), 'start_frame': idx, 'pos_3d': None } }
        self.active_pts = {}
        self.map_points_3d = []  # Результирующие 3D точки для карты [x, z, age]

        self.voxel_size = 1  # Размер кубика (5 см)
        self.voxel_map = {}  # {(vx, vz): index_in_map_points_3d}

        self.last_frame_idx = 0

        self.stats_total_lost_points = 0

    def process_frame(self, frame, idx):
        curr_gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        self.last_frame_idx = idx
        rel_pose = np.eye(4, dtype=np.float32)

        if self.prev_gray is not None:
            tracked_ids, pts_p, pts_c = self._track_with_ids(self.prev_gray, curr_gray)

            if len(pts_p) > self.params.get("min_features", 50):
                R, t, mask, success = self.estimate_matrix(pts_p, pts_c)
                if success:
                    rel_pose[:3, :3] = R
                    rel_pose[:3, 3] = t.flatten()

                    # Фильтруем активные точки
                    self._update_active_pts([tracked_ids[i] for i in range(len(mask)) if mask[i]],
                                            pts_c[mask.flatten() > 0])
                else:
                    self.active_pts = {}

            self._replenish_with_ids(curr_gray, idx)
            # --- СНАЧАЛА ОБНОВЛЯЕМ ПОЗУ ---
            self.current_pose = self.current_pose @ rel_pose
            self.poses.append(self.current_pose.copy())

            # --- ТЕПЕРЬ ТРИАНГУЛИРУЕМ ---
            # self._refine_3d_points(idx)
        else:
            # Для самого первого кадра тоже нужна поза в списке
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

    def _update_active_pts(self, inlier_ids, pts_np):
        """
        Теперь мы не просто выбрасываем точки, а проверяем их перед удалением.
        """
        next_active = {}
        # Те, кто выжил в текущем кадре
        inlier_set = set(inlier_ids)

        # Перебираем все точки, что были активны до этого кадра
        for i, (pt_id, data) in enumerate(self.active_pts.items()):
            if pt_id in inlier_set:
                # Точка жива: обновляем координаты и оставляем в строю
                idx_in_np = inlier_ids.index(pt_id)
                data['pt'] = pts_np[idx_in_np]
                next_active[pt_id] = data
            else:
                # ТОЧКА ПОТЕРЯНА (вышла из кадра или шум)
                # Перед окончательным удалением пробуем её триангулировать!
                self.stats_total_lost_points += 1
                self._triangulate_single_point(data)

        self.active_pts = next_active

    def _triangulate_single_point(self, data):
        # 1. Возраст (базовый фильтр)
        age = self.last_frame_idx - data['first_pose_idx']
        if age < self.slam_config["min_triangulation_age"]:
            return

        # 2. Базис (смещение камеры)
        start_pose = self.poses[data['first_pose_idx']]
        curr_pose = self.current_pose
        dist = np.linalg.norm(curr_pose[:3, 3] - start_pose[:3, 3])

        # Динамический порог базиса: если точка живет долго, мы можем простить малый дист
        # но совсем без движения (dist ~ 0) триангуляция математически невозможна
        if dist < self.slam_config["min_parallax_dist"]:
            return

        # 3. Математика триангуляции
        T1_inv = np.linalg.inv(start_pose)
        T2_inv = np.linalg.inv(curr_pose)
        P1 = self.K @ T1_inv[:3, :]
        P2 = self.K @ T2_inv[:3, :]

        pts4d = cv2.triangulatePoints(P1, P2,
                                      data['first_pt'].reshape(2, 1).astype(np.float32),
                                      data['pt'].reshape(2, 1).astype(np.float32))
        pts3d = pts4d[:3] / (pts4d[3] + 1e-8)

        # 4. Проверка валидности (находится ли точка перед камерой)
        p_hom = np.ones(4)
        p_hom[:3] = pts3d.flatten()
        pt_loc = T2_inv @ p_hom

        depth = pt_loc[2]

        # Адаптивная проверка: ошибка триангуляции пропорциональна квадрату глубины.
        # Поэтому для далеких точек нам нужен ОГРОМНЫЙ базис.
        # Если dist / depth слишком мал (< 0.01), точка будет нестабильной.
        parallax_ratio = dist / (depth + 1e-5)

        is_valid = (self.slam_config["z_min"] < depth < self.slam_config["z_max"]) and \
                   (parallax_ratio > 0.02)

        # Пишем в историю для адаптации
        self.slam_config["success_rate_history"].append(1 if is_valid else 0)
        # Ограничиваем историю
        if len(self.slam_config["success_rate_history"]) > 500:
            self.slam_config["success_rate_history"].pop(0)

        if is_valid:
            pos = pts3d.flatten()

            # 1. Считаем индекс вокселя (в 2D для карты достаточно X и Z)
            vx = int(pos[0] / self.voxel_size)
            vz = int(pos[2] / self.voxel_size)
            v_idx = (vx, vz)

            if v_idx in self.voxel_map:
                # 2. Если воксель занят, обновляем существующую точку
                idx_in_list = self.voxel_map[v_idx]
                old_point = self.map_points_3d[idx_in_list]

                # Стратегия: если новая точка имеет лучший параллакс (ratio),
                # значит она точнее — обновляем её.
                if parallax_ratio > old_point.get('ratio', 0):
                    self.map_points_3d[idx_in_list] = {
                        'pos': pos,
                        'age': age,
                        'ratio': parallax_ratio
                    }
            else:
                # 3. Если воксель пустой, добавляем новую точку
                new_idx = len(self.map_points_3d)
                self.map_points_3d.append({
                    'pos': pos,
                    'age': age,
                    'ratio': parallax_ratio
                })
                self.voxel_map[v_idx] = new_idx

            # Для статистики адаптации
            self.slam_config["success_rate_history"].append(1)
        else:
            self.slam_config["success_rate_history"].append(0)

    def _replenish_with_ids(self, frame_gray, frame_idx):
        mask = np.full(frame_gray.shape, 255, dtype=np.uint8)
        for d in self.active_pts.values():
            cv2.circle(mask, tuple(d['pt'].astype(int)), self.min_distance, 0, -1)

        cnt = max(1,self.max_corners - len(self.active_pts))
        new_feats = cv2.goodFeaturesToTrack(
            frame_gray,
            cnt,
            self.slam_config["quality_level"], # <--- Динамика
            self.min_distance,
            mask=mask)
        if new_feats is not None:
            for f in new_feats:
                self.active_pts[self.next_id] = {
                    'pt': f[0],
                    'first_pt': f[0],
                    'first_pose_idx': frame_idx,
                    'pos_3d': None
                }
                self.next_id += 1

    def _triangulate_points(self, current_idx):
        if len(self.poses) < 5: return

        # Матрица текущей камеры P2 = K @ [R|t] (инверсия текущей позы)
        T_curr_inv = np.linalg.inv(self.current_pose)
        P2 = self.K @ T_curr_inv[:3, :]

        for pt_id, data in self.active_pts.items():
            if data['pos_3d'] is not None: continue

            # Возраст точки
            age = current_idx - data['first_pose_idx']

            # Нам нужно значимое смещение.
            # Если мы еще не накопили Scale, будем ориентироваться на возраст и "базис"
            start_pose = self.poses[data['first_pose_idx']]
            rel_t = self.current_pose[:3, 3] - start_pose[:3, 3]
            dist = np.linalg.norm(rel_t)

            # Условие: либо мы прошли расстояние, либо прошло много кадров (напр. 15)
            if  age > 10: # dist > 3 or
                T_start_inv = np.linalg.inv(start_pose)
                P1 = self.K @ T_start_inv[:3, :]

                # Точки должны быть float32
                pts1 = data['first_pt'].reshape(2, 1).astype(np.float32)
                pts2 = data['pt'].reshape(2, 1).astype(np.float32)

                pts4d = cv2.triangulatePoints(P1, P2, pts1, pts2)
                pts3d = pts4d[:3] / (pts4d[3] + 1e-8)  # Избегаем деления на 0

                # Проверяем положение точки относительно ПЕРВОЙ камеры (локально)
                # Переводим точку из мира в локальную систему первой камеры
                p_hom = np.ones(4)
                p_hom[:3] = pts3d.flatten()
                pt_local = T_start_inv @ p_hom

                # Точка должна быть перед камерой (z > 0)
                # и не слишком близко/далеко
                if 0.1 < pt_local[2] < 100:
                    data['pos_3d'] = pts3d.flatten()  # Это уже мировые координаты
                    self.map_points_3d.append({
                        'pos': data['pos_3d'],
                        'age': age
                    })

    def _refine_3d_points(self, idx):
        T_curr_inv = np.linalg.inv(self.current_pose)
        P2 = self.K @ T_curr_inv[:3, :]

        for pt_id, data in self.active_pts.items():
            age = idx - data['first_pose_idx']
            if age < 5: continue  # Ждем минимальный параллакс

            # Триангулируем текущее положение относительно старта
            start_pose = self.poses[data['first_pose_idx']]
            P1 = self.K @ np.linalg.inv(start_pose)[:3, :]

            pts4d = cv2.triangulatePoints(P1, P2,
                                          data['first_pt'].reshape(2, 1).astype(np.float32),
                                          data['pt'].reshape(2, 1).astype(np.float32))
            new_pos_3d = (pts4d[:3] / (pts4d[3] + 1e-8)).flatten()

            if data['pos_3d'] is None:
                data['pos_3d'] = new_pos_3d
                data['history_3d'] = [new_pos_3d]
            else:
                # Считаем "дрейф" — насколько точка сместилась в МИРЕ с прошлого кадра
                drift = np.linalg.norm(new_pos_3d - data['pos_3d'])

                # Если дрейф слишком большой — это либо машина, либо ошибка трекера
                if drift > 0.5:  # Порог (нужно настраивать)
                    data['is_dynamic'] = True

                    # Обновляем позицию (можно через среднее или фильтр Калмана)
                data['pos_3d'] = 0.8 * data['pos_3d'] + 0.2 * new_pos_3d

    def get_results(self):
        # Траектория камеры
        path = [[p[0, 3], p[2, 3], np.arctan2(p[0, 2], p[2, 2])] for p in self.poses]



        # Облако точек
        cloud = []
        for p in self.map_points_3d:
            cloud.append([p['pos'][0], p['pos'][2], p['age']])


        # --- СТАТИСТИКА ---

        self._adapt_logic() # крутим ручки

        # Статистика
        active_count = len(self.active_pts)
        triangulated_count = len(self.map_points_3d)

        # Считаем возраст самой старой активной точки
        all_ages = [self.last_frame_idx - d['first_pose_idx'] for d in self.active_pts.values()]
        max_age = max(all_ages) if all_ages else 0

        # Считаем эффективность (Success Rate)
        total_lost = self.stats_total_lost_points
        success_rate = (triangulated_count / total_lost * 100) if total_lost > 0 else 0

        return {
            "abs_path": np.array(path, dtype=np.float32),
            "map_cloud": np.array(cloud, dtype=np.float32),
            "marks": self.marks,
            "ranges": [[0, self.last_frame_idx]],
            "stats": {
                "active": active_count,
                "in_map": triangulated_count,
                "max_age_pending": max_age,
                "success_rate_pct": round(success_rate, 1),
                "last_ratio": float(round(self.map_points_3d[-1]['ratio'], 2)) if self.map_points_3d else 0,
                # --- ТЕКУЩИЕ ЗНАЧЕНИЯ "РУЧЕК" ---
                "cfg_quality": round(self.slam_config.get("quality_level", 0), 4),
                "cfg_min_dist": round(self.slam_config.get("min_parallax_dist", 0), 3)
            }
        }

    def estimate_matrix(self, pts_prev, pts_curr):
        E, mask = cv2.findEssentialMat(pts_curr, pts_prev, self.K, method=cv2.RANSAC, threshold=0.5)
        if E is None or E.shape != (3, 3): return None, None, None, False
        _, R, t, mask_p = cv2.recoverPose(E, pts_curr, pts_prev, self.K)
        return R, t, (mask.flatten() > 0) & (mask_p.flatten() > 0), True

    def build_k(self, w, h, fov_deg):
        # 1. Переводим градусы в радианы
        fov_rad = np.deg2rad(fov_deg)

        # 2. Рассчитываем фокусное расстояние в пикселях
        # Формула: f = (w/2) / tan(fov_rad / 2)
        f = (w / 2.0) / np.tan(fov_rad / 2.0)

        # Центр изображения (Principal Point)
        cx = w / 2.0
        cy = h / 2.0

        return np.array([
            [f, 0, cx],
            [0, f, cy],
            [0, 0, 1]
        ], dtype=np.float32)

    def _adapt_logic(self):
        # --- КОНТУР 1: Детектор (Количество активных точек) ---
        # Метрика: Насколько мы заполнены точками?
        fill_rate = len(self.active_pts) / self.max_corners
        if fill_rate < 0.7:  # Если точек мало, снижаем планку качества
            self.slam_config["quality_level"] *= 0.95
        elif fill_rate > 0.9:  # Если забито под завязку, выбираем только лучшие
            self.slam_config["quality_level"] *= 1.05
        # Ограничители
        self.slam_config["quality_level"] = np.clip(self.slam_config["quality_level"], 0.001, 0.05)

        # --- КОНТУР 2: Триангулятор (Эффективность / Success Rate) ---
        # Метрика: Какой процент потерянных точек стал 3D?
        # Если success_rate низкий, значит либо dist слишком большой, либо Z кривой.
        # Но мы будем крутить только min_parallax_dist (базис).

        # Считаем успех за последние 100 попыток
        recent_stats = self.slam_config["success_rate_history"][-100:]
        if len(recent_stats) > 50:
            current_sr = sum(recent_stats) / len(recent_stats)
            if current_sr < 0.05:  # Менее 5% успеха — снижаем требования к смещению
                self.slam_config["min_parallax_dist"] *= 0.9
            elif current_sr > 0.20:  # Слишком много точек (шум) — требуем большего смещения
                self.slam_config["min_parallax_dist"] *= 1.1

            self.slam_config["min_parallax_dist"] = np.clip(self.slam_config["min_parallax_dist"], 0.01, 0.5)

