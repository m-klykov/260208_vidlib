import json
import os
import cv2
from .f_base import FilterBase
from .f_asinc_base import FilterAsyncBase

class FilterSceneDetector(FilterAsyncBase):
    def __init__(self, num, cache_dir, params=None):
        if not params:
            params = {
                "threshold": 30,
            }
        super().__init__(num, cache_dir, params)
        self.name = "Scene Detector"

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


    def get_params_metadata(self):
        return {
            "threshold": {"type": "int", "min": 1, "max": 100, "default": 30},
            "min_scene_len": {"type": "int", "min": 0, "max": 100, "default": 10}  # Длина в кадрах
        }


    def process(self, frame, idx):
        # Пока просто пропускаем кадр без изменений
        return frame

    def run_internal_logic(self, worker):
        """Реальная работа с OpenCV"""
        cap = cv2.VideoCapture(self.video_path)
        if not cap.isOpened():
            raise Exception("Could not open video file")

        total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        if total_frames < 2:
            worker.is_running =  False

        local_marks = []
        frame_idx = 0
        prev_gray = None  # Инициализируем пустотой

        while worker.is_running:
            ret, curr_frame = cap.read()
            if not ret:
                break

            # 1. Подготовка текущего кадра
            curr_gray = cv2.cvtColor(curr_frame, cv2.COLOR_BGR2GRAY)
            curr_gray = cv2.resize(curr_gray, (256, 144))

            # 2. Если это самый первый кадр — просто сохраняем его и идем дальше
            if prev_gray is None:
                prev_gray = curr_gray
                frame_idx += 1
                continue

            # 3. Считаем разницу (начиная со второго кадра)
            diff = cv2.absdiff(curr_gray, prev_gray)
            score = cv2.mean(diff)[0]

            # 4. Детекция склейки
            thresh = self.get_param("threshold")
            min_len = self.get_param("min_scene_len")

            if score > thresh:
                # ПРОВЕРКА: Прошло ли достаточно кадров с последней метки?
                can_add = True
                if local_marks:
                    last_mark = local_marks[-1]
                    if (frame_idx - last_mark) < min_len:
                        can_add = False

                if can_add:
                    local_marks.append(frame_idx)



            # Каждые 100 кадров шлем отчет в UI
            if frame_idx % 100 == 0:
                worker.progress.emit({
                    "progress": int(frame_idx/(total_frames-1)*100),
                    "ranges": [[0, frame_idx]],
                    "marks": list(local_marks)
                })

            prev_gray = curr_gray
            frame_idx += 1

        # финальное сохранение
        worker.progress.emit({
            "progress": int(frame_idx / (total_frames - 1) * 100),
            "ranges": [[0, frame_idx]],
            "marks": list(local_marks)
        })

        cap.release()


    def _on_worker_progress(self, data):
        """Обновление данных из потока (выполняется в UI-потоке)"""
        # Мы используем наши новые сеттеры/геттеры
        if "progress" in data:
            self.progress = data["progress"]

        if "ranges" in data:
            self._analyzed_ranges = data["ranges"]

        if "marks" in data:
            self._detected_scenes = data["marks"]

        self.save_data()

