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

        self.current_frame_idx = 0  # Устанавливается контроллером перед процессом

        # Временные списки для работы в памяти (не сериализуются автоматически)
        self._analyzed_ranges = []
        self._detected_scenes = []

    def get_id(self):
        # Превращает "Scene Detector" в "scene_detector_1"
        clean_name = self.name.lower().replace(" ", "_")
        return f"{clean_name}_{self.num}"

    def set_current_frame(self, idx):
        """устанавливается из контроллера"""
        self.current_frame_idx = idx

    def get_params(self):
        """Возвращает текущие значения параметров для сохранения в основной JSON"""
        with QMutexLocker(self._lock):
            return dict(self._params)

    def is_animated(self, key):
        """Проверяет, хранится ли параметр как структура ключевых кадров"""
        with QMutexLocker(self._lock):
            val = self._params.get(key)
            return isinstance(val, dict) and val.get("is_animated") is True

    def can_be_animated(self, key):
        """Проверяет метаданные: разрешена ли анимация для этого типа"""
        metadata = self.get_params_metadata()
        if key not in metadata: return False

        p_type = metadata[key].get('type')
        # Разрешаем анимацию для чисел
        return p_type in ['float']

    def set_animation(self, key, is_set):
        """Включает/выключает режим анимации для параметра"""
        if not self.can_be_animated(key): return
        if self.is_animated(key) == is_set: return

        current_val = self.get_param(key)  # Получаем текущее (возможно интерполированное) значение

        if not is_set:
            # Выключаем: превращаем в обычное число (значение из текущего кадра)
            with QMutexLocker(self._lock):
                self._params[key] = current_val
        else:
            # Включаем: создаем структуру с первым ключом на текущем кадре
            with QMutexLocker(self._lock):
                self._params[key] = {
                    "is_animated": True,
                    "keys": {str(self.current_frame_idx): current_val}
                }

    def get_param(self, key, default=None):
        with QMutexLocker(self._lock):
            if key in self._params:
                val = self._params[key]
                # Если параметр анимирован — интерполируем
                if isinstance(val, dict) and val.get("is_animated"):
                    return self._interpolate(val["keys"], self.current_frame_idx)
                return val

        # 2. Метаданные (вне лока)
        metadata = self.get_params_metadata()
        if key in metadata and 'default' in metadata[key]:
            return metadata[key]['default']
        return default

    def set_param(self, key, value):
        metadata = self.get_params_metadata()
        if key not in metadata:
            with QMutexLocker(self._lock):
                self._params[key] = value
            return

        # 1. Валидация границ (общая для статики и ключей)
        meta = metadata[key]
        try:
            if meta['type'] == 'int':
                value = int(max(meta['min'], min(meta['max'], value)))
            elif meta['type'] == 'float':
                value = max(meta['min'], min(meta['max'], float(value)))
        except:
            return

        # 2. Запись

        if self.is_animated(key):
            with QMutexLocker(self._lock):
                # Записываем ключ для текущего кадра
                # Используем строки для ключей словаря (для совместимости с JSON)
                self._params[key]["keys"][str(self.current_frame_idx)] = value
        else:
            # Обычная статичная запись
            if self._params.get(key) == value: return
            with QMutexLocker(self._lock):
                self._params[key] = value

    def _interpolate(self, keys_dict, current_frame):
        if not keys_dict: return 0

        # Сортируем кадры-ключи
        frames = sorted([int(f) for f in keys_dict.keys()])

        # Крайние точки
        if current_frame <= frames[0]: return keys_dict[str(frames[0])]
        if current_frame >= frames[-1]: return keys_dict[str(frames[-1])]

        # Линейная интерполяция между соседями
        for i in range(len(frames) - 1):
            f1, f2 = frames[i], frames[i + 1]
            if f1 <= current_frame <= f2:
                v1 = keys_dict[str(f1)]
                v2 = keys_dict[str(f2)]
                t = (current_frame - f1) / (f2 - f1)
                return v1 + (v2 - v1) * t
        return 0

    def is_active_at(self, idx):
        # Если параметров нет — фильтр работает везде
        in_p = self.get_param("act_in", -1)
        out_p = self.get_param("act_out", -1)

        if in_p == -1:
            return True

        return in_p <= idx < out_p

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
            "marks": self._detected_scenes,
            "act_in": self.get_param("act_in",-1),
            "act_out": self.get_param("act_out",-1),
        }

    def handle_mouse_move(self, pos, rect):
        """возвращает курсор и надо ли обновить значение параметров фильтра"""
        return Qt.ArrowCursor, False

    def handle_mouse_press(self, pos, rect):
        pass

    def handle_mouse_release(self):
        pass