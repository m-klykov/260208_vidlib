from vidlab.f_base import FilterBase
import cv2
import numpy as np
from PySide6.QtGui import QPen, QColor

class FilterMotionDetector(FilterBase):
    def __init__(self, num, cache_dir, params=None):

        super().__init__(num, cache_dir, params)
        self.name = "Motion Detector"

        # Память для хранения истории фичей
        self.prev_gray = None
        self.pts_data = []  # Список словарей: {'pt': [x,y], 'age': int}
        self.prev_idx = -1
        self.max_age = 100  # Для нормализации цвета (например, 100 кадров - максимум синевы)

        # Состояние ориентации (накопленное)
        self.abs_yaw = 0.0
        self.abs_pitch = 0.0
        self.abs_roll = 0.0

        # Скорость вперед/назад (сглаженная)
        self.curr_fwd_vel = 0.0

    def get_params_metadata(self):
        return {
            "max_corners": {"type": "int", "min": 10, "max": 2000, "default": 400},
            "quality_level": {"type": "float", "min": 0.001, "max": 0.1, "default": 0.01},
            "min_distance": {"type": "int", "min": 1, "max": 100, "default": 20},
            "block_size": {"type": "int", "min": 3, "max": 15, "default": 3},
            "fov_h": {"type": "float", "min": 30.0, "max": 160.0, "default": 111.0},
            "smooth_factor": {"type": "float", "min": 0.01, "max": 1.0, "default": 0.8},
            "horizon_alpha": {"type": "float", "min": 0.0, "max": 1.0, "default": 0.7},
            "velocity_scale": {"type": "float", "min": 0.1, "max": 10.0, "default": 1.0},

        }

    def analyze_frame(self, frame, idx):
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        h, w = gray.shape
        cx, cy = w // 2, h // 2
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

                idx = np.where(status.flatten() == 1)[0]
                if len(idx) > 10:

                    p0_good = p0[idx].reshape(-1, 2)
                    p1_good = p1[idx].reshape(-1, 2)
                    deltas = p1_good - p0_good

                    # 1. Считаем веса (Гауссиана)
                    sigma = w / 8
                    dist_from_center = p0_good[:, 0] - cx
                    weights = np.exp(-(dist_from_center ** 2) / (2 * sigma ** 2))

                    # 2. Разделяем на левую и правую стороны
                    left_mask = dist_from_center < 0
                    right_mask = dist_from_center >= 0

                    # 3. Взвешенное среднее для каждой стороны
                    def get_weighted_dx(side_mask):
                        if not np.any(side_mask): return 0.0
                        side_weights = weights[side_mask]
                        side_deltas = deltas[side_mask, 0]  # только X
                        return np.sum(side_deltas * side_weights) / (np.sum(side_weights) + 1e-8)

                    dx_left = get_weighted_dx(left_mask)
                    dx_right = get_weighted_dx(right_mask)

                    # Итоговый DX — это среднее между лево и право (балансировка)
                    # Если одна сторона пустая, берем значение другой
                    if not np.any(left_mask):
                        dx = dx_right
                    elif not np.any(right_mask):
                        dx = dx_left
                    else:
                        dx = (dx_left + dx_right) / 2.0

                    # Для DY (Pitch) используем общий взвешенный расчет
                    dy = np.sum(deltas[:, 1] * weights) / (np.sum(weights) + 1e-8)

                    # 4. Roll считаем как раньше через аффинную матрицу
                    d_roll = 0
                    M, _ = cv2.estimateAffinePartial2D(p0[idx], p1[idx])
                    if M is not None:
                        da = np.arctan2(M[1, 0], M[0, 0])
                        d_roll = np.degrees(da)

                    # 5. Интеграция
                    px_per_deg = w / self.get_param("fov_h")
                    sf = self.get_param("smooth_factor")

                    self.abs_yaw -= (dx / px_per_deg) * sf
                    self.abs_pitch += (dy / px_per_deg) * sf
                    self.abs_roll -= d_roll * sf

                    # Демпферы (утечка к центру)
                    self.abs_pitch *= 0.95
                    self.abs_roll *= 0.95

                    # --- РАСЧЕТ ВПЕРЕД/НАЗАД (РАДИАЛЬНОЕ СМЕЩЕНИЕ) ---
                    # 1. Векторы от центра кадра до точек (до движения)
                    r0_vecs = p0_good - np.array([cx, cy])
                    # 2. Проекция дельты движения на радиальный вектор
                    # (скалярное произведение, чтобы понять, "улетает" точка от центра или "сближается")

                    corrected_deltas = deltas - np.array([dx, dy])

                    # Избегаем деления на ноль для центральных точек
                    dist_sq = np.sum(r0_vecs ** 2, axis=1)
                    valid_dist_mask = dist_sq > 25  # игнорируем точки ближе 5px от центра

                    if np.any(valid_dist_mask):
                        # Радиальное смещение (norm_deltas = delta_dot_r / |r|)
                        rad_deltas = np.sum( corrected_deltas * r0_vecs, axis=1)[valid_dist_mask] / np.sqrt(
                            dist_sq[valid_dist_mask])

                        # Поступательная скорость — это среднее радиальное смещение.
                        # Если dx/dy (Yaw/Pitch) мы балансировали, то тут нам нужен средний шум.
                        raw_vel = np.median(rad_deltas)

                        # Сглаживание скорости (Калман-стайл)
                        self.curr_fwd_vel = 0.95 * self.curr_fwd_vel + 0.05 * raw_vel


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
            maxCorners= self.get_param("max_corners"),
            qualityLevel= self.get_param("quality_level"),
            minDistance= self.get_param("min_distance"),
            blockSize= self.get_param("block_size")
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
                    if np.min(dists) < self.get_param("min_distance"):
                        is_far = False

                if is_far:
                    self.pts_data.append({'pt': nc, 'age': 0})
                    result["born_pts"].append(nc)

        self.prev_gray = gray.copy()
        return result

    def process(self, frame, idx):
        # Получаем параметры из UI

        data = self.analyze_frame(frame, idx)

        self._draw_motion(frame, data)

        self._draw_horizon_ui(frame)

        self._draw_velocity_arrow(frame)

        return frame

    def _draw_motion(self, frame, data):

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

    def _draw_horizon_ui(self, frame):

        # print(frame.shape)

        h, w, _ = frame.shape
        cx, cy = w // 2, h // 2

        px_per_deg = w / self.get_param("fov_h")

        # Создаем оверлей для прозрачности
        overlay = frame.copy()

        # Матрица вращения для Roll (крена)
        R = cv2.getRotationMatrix2D((cx, cy), self.abs_roll, 1.0)

        # Смещение горизонта по Pitch
        pitch_offset = int(self.abs_pitch * px_per_deg)

        # Рисуем шкалу каждые 5 градусов
        start_angle = int(self.abs_yaw - 60)
        end_angle = int(self.abs_yaw + 60)

        for ang in range(start_angle, end_angle + 1):
            if ang % 5 == 0:
                # Позиция X относительно центра
                rel_x = int((ang - self.abs_yaw) * px_per_deg)

                # Точка на линии горизонта (до вращения)
                pt_x = cx + rel_x
                pt_y = cy + pitch_offset

                # Применяем вращение (Roll)
                target_x = R[0, 0] * pt_x + R[0, 1] * pt_y + R[0, 2]
                target_y = R[1, 0] * pt_x + R[1, 1] * pt_y + R[1, 2]

                if 0 <= target_x < w and 0 <= target_y < h:
                    is_major = (ang % 15 == 0)
                    color = (255, 255, 255) if is_major else (255, 255, 0)
                    cv2.circle(overlay, (int(target_x), int(target_y)), 5 if is_major else 3, color, -1)

                    if is_major:
                        val = ang % 360
                        cv2.putText(overlay, f"{val}", (int(target_x) - 10, int(target_y) - 10),
                                    cv2.FONT_HERSHEY_SIMPLEX, 1, color, 1)

        # Смешиваем основной кадр с оверлеем
        alpha = self.get_param("horizon_alpha")
        cv2.addWeighted(overlay, alpha, frame, 1 - alpha, 0, frame)


    def _draw_velocity_arrow(self, frame):
        h, w, _ = frame.shape
        cx = w // 2

        velocity = self.curr_fwd_vel

        # Точка крепления стрелки — в нижней части по центру (поверх дороги)
        base_y = int(h * 0.9)
        base_pt = (cx, base_y)

        # Длина стрелки зависит от скорости и scale
        scale = self.get_param("velocity_scale")
        # 1.0 в `velocity` — это примерно 1px радиального смещения в среднем.
        arrow_len = int(velocity * scale * 20.0)

        # Ограничиваем, чтобы не вылетала за кадр
        arrow_len = np.clip(arrow_len, -h // 3, h // 3)

        if abs(arrow_len) > 5:  # Рисуем только при значимом движении
            target_y = base_y - arrow_len  # Стрелка вверх при положительной скорости (fwd)
            target_pt = (cx, target_y)

            # Цвет: Зеленый вперед, Красный назад
            color = (0, 255, 0) if arrow_len > 0 else (0, 0, 255)

            cv2.arrowedLine(frame, base_pt, target_pt, color, 3, tipLength=0.3)

            # Подпись (попугаи скорости)
            cv2.putText(frame, f"Vel: {velocity:.2f}", (cx + 10, base_y - 10),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.6, color, 2)