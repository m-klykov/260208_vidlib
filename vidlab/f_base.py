import os
import json

from PySide6.QtCore import QObject, Signal, QMutex, QMutexLocker
from PySide6.QtGui import Qt


class FilterBase(QObject):

    params_changed = Signal()  # Сигнал для UI (ползунки, таймлайн)

    def __init__(self, num, cache_dir, params=None):
        self.name = "Base Filter"  # Переопределяется в потомках
        self.num = num
        self.cache_dir = cache_dir  # Путь к папке вида video_fdata/
        self._params = params or {}
        self.enabled = True
        self.focused = False
        self._lock = QMutex()

        # Временные списки для работы в памяти (не сериализуются автоматически)
        self._analyzed_ranges = []
        self._detected_scenes = []

    def get_id(self):
        # Превращает "Scene Detector" в "scene_detector_1"
        clean_name = self.name.lower().replace(" ", "_")
        return f"{clean_name}_{self.num}"

    def get_params(self):
        """Возвращает текущие значения параметров для сохранения в основной JSON"""
        with QMutexLocker(self._lock):
            return dict(self._params)

    def get_param(self, key, default=None):
        """
        Безопасное чтение:
        1. Из словаря параметров
        2. Из метаданных (default значение)
        3. Из аргумента default
        """
        with QMutexLocker(self._lock):
            # 1. Если параметр уже задан (есть в словаре)
            if key in self._params:
                return self._params[key]

        # 2. Если в словаре нет, ищем в метаданных (вне лока, т.к. метаданные статичны)
        metadata = self.get_params_metadata()
        if key in metadata and 'default' in metadata[key]:
            return metadata[key]['default']

        # 3. Крайний случай
        return default

    def set_param(self, key, value):
        """Безопасная запись с проверкой границ и уведомлением"""
        metadata = self.get_params_metadata()

        # 1. Валидация по метаданным
        if key in metadata:
            meta = metadata[key]
            try:
                if meta['type'] == 'int':
                    value = int(max(meta['min'], min(meta['max'], value)))
                elif meta['type'] == 'float':
                    value = max(meta['min'], min(meta['max'], float(value)))
            except (ValueError, TypeError):
                return  # Некорректный тип, игнорируем

        # 2. Запись под замком
        with QMutexLocker(self._lock):
            if self._params.get(key) == value:
                return  # Ничего не изменилось
            self._params[key] = value

        # 3. Уведомление системы
        # self.params_changed.emit()

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
        """Переопределяем, чтобы отдавать данные не из params, а из внутренних списков"""
        return {
            "ranges": self._analyzed_ranges,
            "marks": self._detected_scenes
        }

    def handle_mouse_move(self, pos, rect):
        """возвращает курсор и надо ли обновить значение параметров фильтра"""
        return Qt.ArrowCursor, False

    def handle_mouse_press(self, pos, rect):
        pass

    def handle_mouse_release(self):
        pass