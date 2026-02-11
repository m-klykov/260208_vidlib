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

        # Реальные поля для данных (будут сериализованы в params)
        test_ranges = [[0, 2000], [3000, 4500]]
        test_marks = [150, 600, 1200, 3400, 4100]

        self.set_param("analyzed_ranges", test_ranges)
        self.set_param("detected_scenes", test_marks)


    def get_params_metadata(self):
        return {
            "threshold": {"type": "int", "min": 1, "max": 100, "default": 30}
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
        if total_frames==0:
            worker.is_running =  False

        local_marks = []
        frame_idx = 0

        while worker.is_running:
            ret, frame = cap.read()
            if not ret:
                break

            # --- Тут будет магия OpenCV ---
            # Читаем параметры через безопасный геттер
            thresh = self.get_param("threshold")

            # Фейковая логика для теста:
            if frame_idx % 500 == 0 and frame_idx > 0:
                local_marks.append(frame_idx)

            # Каждые 100 кадров шлем отчет в UI
            if frame_idx % 100 == 0:
                worker.progress.emit({
                    "progress": int(frame_idx/total_frames*100),
                    "ranges": [[0, frame_idx]],
                    "marks": list(local_marks)
                })

            frame_idx += 1

        cap.release()