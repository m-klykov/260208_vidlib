import os
import json

from PySide6.QtCore import QObject, Signal
from PySide6.QtGui import Qt


class FilterBase(QObject):

    def __init__(self, num, cache_dir, params=None):
        self.name = "Base Filter"  # Переопределяется в потомках
        self.num = num
        self.cache_dir = cache_dir  # Путь к папке вида video_fdata/
        self.params = params or {}
        self.enabled = True
        self.focused = False

    def get_id(self):
        # Превращает "Scene Detector" в "scene_detector_1"
        clean_name = self.name.lower().replace(" ", "_")
        return f"{clean_name}_{self.num}"

    def get_params(self):
        """Возвращает текущие значения параметров для сохранения в основной JSON"""
        return self.params

    def get_params_metadata(self):
        """
        Возвращает описание параметров для построения UI.
        Пример: {"threshold": {"type": "float", "min": 0, "max": 100, "default": 30}}
        """
        return {}

    def get_data_path(self):
        """Возвращает путь к личному файлу данных фильтра в папке кеша"""
        return os.path.join(self.cache_dir, f"{self.get_id()}.json")

    # --- Методы-заглушки для переопределения ---

    def process(self, frame, idx):
        """Статическая обработка кадра"""
        return frame

    def render_overlay(self, painter, idx, viewport_rect):
        """Рисование поверх видео"""
        pass

    def get_timeline_data(self):
        """Данные для отрисовки на таймлайне (диапазоны, метки)"""
        return {"ranges": [], "marks": []}

    def handle_mouse_move(self, pos, rect):
        """возвращает курсор и надо ли обновить значение параметров фильтра"""
        return Qt.ArrowCursor, False

    def handle_mouse_press(self, pos, rect):
        pass

    def handle_mouse_release(self):
        pass