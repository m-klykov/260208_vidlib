import json
import os
import cv2
import numpy as np
from .f_asinc_base import FilterAsyncBase

DATA_VERSION = 2  # При изменении логики инкрементируем

class FilterStabilizer(FilterAsyncBase):
    def __init__(self, num, cache_dir, params=None):
        if not params:
            params = {
            }
        super().__init__(num, cache_dir, params)
        self.name = "Stabilizer"

        # Внутреннее состояние
        self._raw_transforms = np.array([])  # Сырые данные из сканера
        self._stab_data = np.array([])  # Сглаженные данные для отрисовки
        self._max_offset = 0
        self._last_smooth_radius = -1  # Радиус, для которого считали последний раз

        self.load_data()

    def get_params_metadata(self):
        return {
            # Порог для смены сцены
            "min_features": {"type": "int", "min": 10, "max": 500, "default": 30},
            "auto_zoom": {"type": "bool", "default": False},
            "sm_radius": {"type": "int", "min": 5, "max": 100, "default": 25},

        }

    def get_npy_filename(self):
        return os.path.join(self.cache_dir, f"{self.get_id()}.npy")

    def save_data(self):
        """Сохраняем всё в один NPY файл"""
        if not self.cache_dir: return
        os.makedirs(self.cache_dir, exist_ok=True)

        payload = {
            "version": DATA_VERSION,
            "ranges": self._analyzed_ranges,
            "marks": self._detected_scenes,
            "raw_transforms": self._raw_transforms,
            "max_offset": self._max_offset
        }
        np.save(self.get_npy_filename(), payload)

    def load_data(self):
        path = self.get_npy_filename()
        if os.path.exists(path):
            try:
                payload = np.load(path, allow_pickle=True).item()
                if payload.get("version") == DATA_VERSION:
                    self._analyzed_ranges = payload.get("ranges", [])
                    self._detected_scenes = payload.get("marks", [])
                    self._raw_transforms = payload.get("raw_transforms", np.array([]))
                    self._max_offset = payload.get("max_offset", 0)
                else:
                    print(f"{self.name}: Old cache version, ignoring.")
            except Exception as e:
                print(f"Error loading cache: {e}")

    def _update_smoothing_if_needed(self, current_idx):
        """
        Ленивый пересчет сглаживания.
        Срабатывает если: изменился радиус или появились новые сырые данные.
        """
        current_radius = self.get_param("sm_radius")
        raw_len = len(self._raw_transforms)

        need_update = (
            current_radius != self._last_smooth_radius or
            ( current_idx >= len(self._stab_data) and
              len(self._stab_data) < raw_len )
        )

        if need_update and raw_len > 0:
            trajectory = np.cumsum(self._raw_transforms, axis=0)
            print(f"расчет сглаживания smlen = {len(self._stab_data)} rawlen = {raw_len}")
            # Передаем маркеры сцен для корректного сброса сглаживания
            smoothed = self._smooth_trajectory_scene_aware(
                trajectory,
                current_radius,
                self._detected_scenes
            )
            self._stab_data = smoothed - trajectory
            self._max_offset = np.max(np.abs(self._stab_data[:, :2])) if len(self._stab_data) > 0 else 0
            self._last_smooth_radius = current_radius

    def _smooth_trajectory_scene_aware(self, trajectory, radius, marks):
        """Векторизованное сглаживание по сегментам"""
        smoothed = np.copy(trajectory)
        num_frames = len(trajectory)
        window_size = 2 * radius + 1

        boundaries = sorted(list(set([0] + marks + [num_frames])))

        for i in range(len(boundaries) - 1):
            start, end = boundaries[i], boundaries[i + 1]
            segment = trajectory[start:end]
            if len(segment) < 2: continue

            # Используем скользящее среднее через свертку (быстрее в разы)
            for col in range(segment.shape[1]):
                # Padding для краев сегмента, чтобы не было черных рывков
                padded = np.pad(segment[:, col], (radius, radius), mode='edge')
                smoothed_col = np.convolve(padded, np.ones(window_size)/window_size, mode='valid')
                smoothed[start:end, col] = smoothed_col[:len(segment)]

        return smoothed

    def process(self, frame, idx):
        self._update_smoothing_if_needed(idx)

        # Если данных нет или индекс вне диапазона
        if len(self._stab_data) == 0 or idx >= len(self._stab_data):
            return frame

        # Считываем корректирующие значения
        dx, dy, da = self._stab_data[idx]
        h, w = frame.shape[:2]

        # 1. Создаем матрицу трансформации
        # ВАЖНО: Мы используем отрицательный угол и инвертированные смещения,
        # если траектория была накоплена 'прямым' методом
        m = cv2.getRotationMatrix2D((w / 2, h / 2), np.degrees(da), 1.0)
        m[0, 2] += dx
        m[1, 2] += dy

        # 2. Авто-зум
        if self.get_param("auto_zoom") and self._max_offset > 0:
            # Коэффициент должен быть достаточным, чтобы закрыть пустоты со всех сторон
            scale = 1.0 + (self._max_offset * 2.5 / min(w, h))
            m_zoom = cv2.getRotationMatrix2D((w / 2, h / 2), 0, scale)
            m = m_zoom @ np.vstack([m, [0, 0, 1]])
            m = m[:2, :]

        # , borderMode=cv2.BORDER_REPLICATE
        return cv2.warpAffine(frame, m, (w, h))

    def run_internal_logic(self, worker):
        cap = cv2.VideoCapture(self.video_path)
        total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))

        raw_transforms = []
        prev_gray = None
        frame_idx = 0
        local_marks = []

        while worker.is_running:
            ret, frame = cap.read()
            if not ret: break

            curr_gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
            if prev_gray is None:
                prev_gray = curr_gray
                raw_transforms.append([0, 0, 0])
                frame_idx += 1
                continue

            p0 = cv2.goodFeaturesToTrack(prev_gray, maxCorners=200, qualityLevel=0.01, minDistance=30)

            # Логика детекции смещения
            current_trans = [0, 0, 0]
            if p0 is not None and len(p0) > 0:
                p1, status, _ = cv2.calcOpticalFlowPyrLK(prev_gray, curr_gray, p0, None)
                if p1 is not None and status is not None:
                    good = np.where(status == 1)[0]
                    if len(good) < self.get_param("min_features"):
                        local_marks.append(frame_idx)  # Смена сцены
                    else:
                        m, _ = cv2.estimateAffinePartial2D(p0[good], p1[good])
                        if m is not None:
                            current_trans = [m[0, 2], m[1, 2], np.arctan2(m[1, 0], m[0, 0])]

            raw_transforms.append(current_trans)

            # Каждые 100 кадров сбрасываем сырые данные в UI поток
            if frame_idx % 100 == 0:
                worker.progress.emit({
                    "progress": int(frame_idx / total_frames * 100),
                    "raw_transforms": list(raw_transforms),
                    "marks": list(local_marks),
                    "ranges": [[0, frame_idx]]
                })

            prev_gray = curr_gray
            frame_idx += 1

        worker.progress.emit({
            "progress": 100,
            "raw_transforms": list(raw_transforms),
            "marks": list(local_marks),
            "ranges": [[0, frame_idx]]
        })
        cap.release()

    def _on_worker_progress(self, data):
        """Прием данных из воркера и сохранение на диск"""
        if "progress" in data: self.progress = data["progress"]
        if "ranges" in data: self._analyzed_ranges = data["ranges"]
        if "marks" in data: self._detected_scenes = data["marks"]
        if "raw_transforms" in data:
            self._raw_transforms = np.array(data["raw_transforms"])

        # Мы не считаем сглаживание здесь!
        # Его посчитает process() при следующем запросе кадра.
        self.save_data()

