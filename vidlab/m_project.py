import json
import os


class VideoProjectModel:
    def __init__(self):
        self.current_json_path = None
        self.scenes = []  # Список словарей: [{"frame": 100, "title": "Вход героя"}, ...]

    def load_project(self, video_path):
        """Определяет путь к JSON и загружает данные"""
        base_path = os.path.splitext(video_path)[0]
        self.current_json_path = base_path + ".json"

        if os.path.exists(self.current_json_path):
            try:
                with open(self.current_json_path, 'r', encoding='utf-8') as f:
                    self.scenes = json.load(f)
            except Exception as e:
                print(f"Ошибка загрузки JSON: {e}")
                self.scenes = []
        else:
            self.scenes = []
        return self.scenes

    def save_project(self):
        """Сохраняет текущий список сцен в файл"""
        if self.current_json_path:
            try:
                with open(self.current_json_path, 'w', encoding='utf-8') as f:
                    json.dump(self.scenes, f, ensure_ascii=False, indent=4)
            except Exception as e:
                print(f"Ошибка сохранения JSON: {e}")

    def add_scene(self, frame_idx, title="Новая сцена"):
        # Проверяем, нет ли уже сцены на этом кадре
        if not any(s['frame'] == frame_idx for s in self.scenes):
            self.scenes.append({"frame": frame_idx, "title": title})
            self.scenes.sort(key=lambda x: x['frame'])  # Сортируем по времени
            self.save_project()

    def remove_scene(self, frame_idx):
        self.scenes = [s for s in self.scenes if s['frame'] != frame_idx]
        self.save_project()

    def update_scene_title(self, frame_idx, new_title):
        for s in self.scenes:
            if s['frame'] == frame_idx:
                s['title'] = new_title
                break
        self.save_project()

    def update_scene_frame(self, old_frame_idx, new_frame_idx):
        if any(s['frame'] == new_frame_idx for s in self.scenes):
            raise ValueError(f"Кадр {new_frame_idx} ужн занят")

        for s in self.scenes:
            if s['frame'] == old_frame_idx:
                s['frame'] = new_frame_idx
                self.scenes.sort(key=lambda x: x['frame'])
                self.save_project()
                return True
        return False