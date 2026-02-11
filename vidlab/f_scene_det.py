from .f_base import FilterBase


class FilterSceneDetector(FilterBase):
    def __init__(self, num, cache_dir, params=None):
        if not params:
            params = {
                "threshold": 30,
            }
        super().__init__(num, cache_dir, params)
        self.name = "Scene Detector"

        # Реальные поля для данных (будут сериализованы в params)


    def get_params_metadata(self):
        return {
            "threshold": {"type": "int", "min": 1, "max": 100, "default": 30}
        }

    def get_timeline_data(self):
        """Отдаем данные для верхней части таймлайна"""
        # Генерируем фейковые данные для теста, если еще ничего не анализировали
        test_ranges = [[0, 2000], [3000, 4500]]
        test_marks = [150, 600, 1200, 3400, 4100]

        return {
            "ranges": self.params.get("analyzed_ranges", []) or test_ranges,
            "marks": self.params.get("detected_scenes", []) or test_marks
        }

    def process(self, frame, idx):
        # Пока просто пропускаем кадр без изменений
        return frame