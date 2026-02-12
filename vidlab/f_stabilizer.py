import json
import os
import cv2
import numpy as np
from .f_asinc_base import FilterAsyncBase

class FilterStabilizer(FilterAsyncBase):
    def __init__(self, num, cache_dir, params=None):
        if not params:
            params = {
            }
        super().__init__(num, cache_dir, params)
        self.name = "Stabilizer"

        self._stab_data = np.array([])
        self._max_offset = 0

        # обязательно, в базовом классе не вызывается
        self.load_data()

    def save_data(self):
        """Сохраняет результаты анализа в файл кеша"""
        if not self.cache_dir:
            print(f"Warning: cache_dir not set for {self.name}")
            return

            # 2. Создаем папку, если её еще не существует
        try:
            os.makedirs(self.cache_dir, exist_ok=True)
        except Exception as e:
            print(f"Error creating cache directory {self.cache_dir}: {e}")
            return

        data = {
            "ranges": self._analyzed_ranges,
            "marks": self._detected_scenes
        }
        try:
            with open(self.get_data_filepath(), 'w') as f:
                json.dump(data, f)
        except Exception as e:
            print(f"Error saving cache for {self.name}: {e}")

        path = self.get_npy_filename()
        # Сохраняем и данные, и мета-информацию (например, max_offset)
        try:
            np.save(path, {"data": self._stab_data, "offset": self._max_offset})
        except Exception as e:
            print(f"Error saving np cache in {path}: {e}")

    def get_npy_filename(self):
        return os.path.join(self.cache_dir, f"{self.get_id()}.npy")

    def load_data(self):
        """Загружает результаты анализа из файла кеша"""
        path = self.get_data_filepath()
        if os.path.exists(path):
            try:
                with open(path, 'r') as f:
                    data = json.load(f)
                    self._analyzed_ranges = data.get("ranges", [])
                    self._detected_scenes = data.get("marks", [])
            except Exception as e:
                print(f"Error loading cache for {self.name}: {e}")

        path = self.get_npy_filename()
        if os.path.exists(path):
            try:
                payload = np.load(path, allow_pickle=True).item()
                self._stab_data = payload["data"]
                self._max_offset = payload["offset"]
            except Exception as e:
                print(f"Error loading np cache from {path}: {e}")


    def get_params_metadata(self):
        return {
            "sm_radius": {"type": "int", "min": 5, "max": 100, "default": 25},
            "auto_zoom": {"type": "bool", "default": False},
            "min_features": {"type": "int", "min": 10, "max": 500, "default": 30}  # Порог для смены сцены
        }

    def process(self, frame, idx):
        if idx >= len(self._stab_data):
            return frame

        dx, dy, da = self._stab_data[idx]
        h, w = frame.shape[:2]

        # 1. Матрица трансформации
        m = cv2.getRotationMatrix2D((w / 2, h / 2), np.degrees(da), 1.0)
        m[0, 2] += dx
        m[1, 2] += dy

        # 2. Если включен авто-зум, увеличиваем масштаб
        if self.get_param("auto_zoom") and self._max_offset > 0:
            # Рассчитываем коэффициент масштабирования исходя из макс. смещения
            scale = 1.0 + (self._max_offset * 2 / min(w, h))
            m_zoom = cv2.getRotationMatrix2D((w / 2, h / 2), 0, scale)
            # Объединяем матрицы (сначала стабилизация, потом зум)
            m = m_zoom @ np.vstack([m, [0, 0, 1]])
            m = m[:2, :]

        return cv2.warpAffine(frame, m, (w, h)) # , borderMode=cv2.BORDER_REPLICATE

    def run_internal_logic(self, worker):
        cap = cv2.VideoCapture(self.video_path)
        total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))

        raw_transforms = [] # [dx, dy, da]
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

            # 1. Поиск точек и оптический поток
            p0 = cv2.goodFeaturesToTrack(prev_gray, maxCorners=200, qualityLevel=0.01, minDistance=30)

            if p0 is None or len(p0) == 0:
                raw_transforms.append([0, 0, 0])
                prev_gray = curr_gray
                frame_idx += 1
                continue

            p1, status, err = cv2.calcOpticalFlowPyrLK(prev_gray, curr_gray, p0, None)

            # 3. Проверка статуса (были ли найдены эти же точки на новом кадре)
            if p1 is None or status is None:
                raw_transforms.append([0, 0, 0])
            else:
                # 2. Проверка на валидность (смена сцены)
                good_indices = np.where(status == 1)[0]
                if len(good_indices) < self.get_param("min_features"):
                    # Смена сцены: не двигаем кадр относительно предыдущего
                    raw_transforms.append([0, 0, 0])
                    local_marks.append(frame_idx)
                else:
                    p0, p1 = p0[good_indices], p1[good_indices]
                    # Вычисляем аффинную трансформацию (Rigid: translation, rotation, scale)
                    m, _ = cv2.estimateAffinePartial2D(p0, p1)
                    if m is not None:
                        dx, dy = m[0, 2], m[1, 2]
                        da = np.arctan2(m[1, 0], m[0, 0])
                        raw_transforms.append([dx, dy, da])
                    else:
                        raw_transforms.append([0, 0, 0])

            if frame_idx % 100 == 0:
                worker.progress.emit({
                    "progress": int(frame_idx/total_frames*100),
                    "ranges": [[0, frame_idx]],
                    "marks": list(local_marks)
                })

            prev_gray = curr_gray
            frame_idx += 1

        # 3. Пост-обработка: Сглаживание траектории
        transforms = np.array(raw_transforms)
        trajectory = np.cumsum(transforms, axis=0)

        smoothed = self._smooth_trajectory(trajectory, self.get_param("sm_radius"))

        # Итоговое смещение, которое нужно применить к каждому кадру
        # Смещение = Сглаженный_путь - Текущий_путь
        final_data = smoothed - trajectory

        # 4. Расчет оптимального зума (чтобы скрыть черные края)
        # Ищем максимальное отклонение по X и Y
        max_offset = np.max(np.abs(final_data[:, :2]))

        # Передаем всё в основной поток
        worker.progress.emit({
            "progress": 100,
            "stab_data": final_data.tolist(),
            "max_offset": float(max_offset)
        })
        cap.release()

    def _smooth_trajectory(self, trajectory, radius):
        """Скользящее среднее для сглаживания пути камеры"""
        smoothed = np.copy(trajectory)
        for i in range(len(trajectory)):
            low = max(0, i - radius)
            high = min(len(trajectory), i + radius)
            smoothed[i] = np.mean(trajectory[low:high], axis=0)
        return smoothed


    def _on_worker_progress(self, data):
        """Обновление данных из потока (выполняется в UI-потоке)"""
        # Мы используем наши новые сеттеры/геттеры
        if "progress" in data:
            self.progress = data["progress"]

        if "ranges" in data:
            self._analyzed_ranges = data["ranges"]

        if "marks" in data:
            self._detected_scenes = data["marks"]
        if "stab_data" in data:
            self._stab_data = np.array(data["stab_data"])

        self._max_offset = data.get("max_offset", 0)

        self.save_data()

