import os
import cv2
import numpy as np

class CameraTrackerCv2Model:

    def __init__(self, w, h, params):
        self.w = w
        self.h = h
        # Конфигурация из параметров
        self.fov_w =  111.0
        self.max_corners = 400
        self.min_distance = 25
        self.smooth_factor = 0.8
        self.speed_k = 0.05  # Добавил коэффициент скорости, если его не было

        # Состояние навигации
        self.curr_x = 0.0
        self.curr_y = 0.0
        self.curr_yaw = 0.0  # В радианах

        self.abs_path = [[0.0, 0.0, 0.0 ]]  # [x, y, yaw]

        self.prev_gray = None
        self.pts = []  # {'pt': [x,y]}
        self.last_frame_idx = 0

    def process_frame(self, frame, idx):
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        h, w = gray.shape
        cx, cy = w // 2, h // 2
        px_per_deg = w / self.fov_w

        if self.prev_gray is not None and len(self.pts) > 10:
            # Здесь d['pt'] теперь всегда будет работать
            p0 = np.array([d['pt'] for d in self.pts], dtype=np.float32).reshape(-1, 1, 2)
            p1, status, _ = cv2.calcOpticalFlowPyrLK(self.prev_gray, gray, p0, None)

            if p1 is not None:
                good = status.flatten() == 1
                p0_g, p1_g = p0[good].reshape(-1, 2), p1[good].reshape(-1, 2)
                deltas = p1_g - p0_g

                # 1. Расчет Yaw
                sigma = w / 8
                dist_x = p0_g[:, 0] - cx
                weights = np.exp(-(dist_x ** 2) / (2 * sigma ** 2))
                l_m, r_m = dist_x < 0, dist_x >= 0

                def get_w_dx(m):
                    return np.sum(deltas[m, 0] * weights[m]) / (np.sum(weights[m]) + 1e-8) if np.any(m) else 0

                dx = (get_w_dx(l_m) + get_w_dx(r_m)) / 2.0 if (np.any(l_m) and np.any(r_m)) else get_w_dx(l_m or r_m)

                d_yaw = -(dx / px_per_deg) * (np.pi / 180.0) * self.smooth_factor
                self.curr_yaw += d_yaw

                # 2. Скорость (Зум)
                dy = np.sum(deltas[:, 1] * weights) / (np.sum(weights) + 1e-8)
                corrected_deltas = deltas - np.array([dx, dy])
                r0_vecs = p0_g - np.array([cx, cy])
                dist_sq = np.sum(r0_vecs ** 2, axis=1)
                v_mask = dist_sq > 25

                step_size = 0
                if np.any(v_mask):
                    rad_deltas = np.sum(corrected_deltas[v_mask] * r0_vecs[v_mask], axis=1) / np.sqrt(dist_sq[v_mask])
                    step_size = np.median(rad_deltas) * self.speed_k

                # 3. Перемещение
                self.curr_x += step_size * np.sin(self.curr_yaw)
                self.curr_y += step_size * np.cos(self.curr_yaw)

                # Обновляем точки
                new_pts_data = []
                # Проходим по всем исходным точкам и их статусам одновременно
                for old_pt_dict, is_ok, new_coord in zip(self.pts, status.flatten(), p1.reshape(-1, 2)):
                    if is_ok:
                        new_pts_data.append({
                            'pt': new_coord,
                            'age': old_pt_dict['age'] + 1
                        })
                self.pts = new_pts_data

        self.abs_path.append([self.curr_x, self.curr_y, self.curr_yaw])
        self.pts_replenish(gray)
        self.prev_gray = gray.copy()
        self.last_frame_idx = idx

    def pts_replenish(self, gray):
        new_feats = cv2.goodFeaturesToTrack(gray, self.max_corners, 0.01, self.min_distance)
        if new_feats is None: return

        # Если точек нет, инициализируем список правильно
        if not self.pts:
            for f in new_feats:
                self.pts.append({'pt': f[0], 'age': 0})
            return

        new_coords = new_feats.reshape(-1, 2)
        current_coords = np.array([d['pt'] for d in self.pts])

        for nc in new_coords:
            # Проверка дистанции до существующих
            dists = np.linalg.norm(current_coords - nc, axis=1)
            if np.min(dists) > self.min_distance:
                self.pts.append({'pt': nc, 'age': 0})


    def get_results(self):

        return {
            "abs_path": np.array(self.abs_path, dtype=np.float32),
            # "marks": self.marks,
            "ranges": [[0, self.last_frame_idx]],
        }




