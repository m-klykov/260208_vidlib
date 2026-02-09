import json
import os

from .f_base import FilterBase
from .f_bw import FilterBW
from .f_crop import FilterCrop
from .f_levels import FilterLevels
from .m_project import VideoProjectModel


class VideoProjectExtModel(VideoProjectModel):
    def __init__(self):
        super().__init__()
        self.filters = []  # Список активных объектов фильтров

        # Реестр доступных классов фильтров (Имя -> Класс)
        self.filter_registry = {
            "Levels": FilterLevels,
            "Black and White": FilterBW,
            "Crop": FilterCrop,
        }

    def load_project(self, video_path):
        # Загружаем базовые сцены через родителя
        data = super().load_project(video_path)

        # Определяем папку для кеша данных фильтров
        base_dir = os.path.dirname(video_path)
        video_name = os.path.splitext(os.path.basename(video_path))[0]
        self.cache_dir = os.path.join(base_dir, f"{video_name}_fdata")

        # Если в JSON есть ключ 'filters', восстанавливаем объекты
        # Предполагаем, что структура JSON теперь: {"scenes": [], "filters": []}
        if isinstance(data, dict):
            self.scenes = data.get("scenes", [])
            filter_configs = data.get("filters", [])
            self._restore_filters(filter_configs)
        else:
            # Если старый формат (просто список), значит фильтров еще нет
            self.scenes = data
            self.filters = []

        return self.scenes

    def _restore_filters(self, configs):
        self.filters = []
        for cfg in configs:
            f_class = self.filter_registry.get(cfg['name'])
            if f_class:
                f_obj = f_class(cfg['num'], self.cache_dir, cfg['params'])
                f_obj.enabled = cfg.get('enabled', True)
                self.filters.append(f_obj)

    def add_filter(self, filter_name):
        f_class = self.filter_registry.get(filter_name)
        if not f_class: return

        # Считаем номер для нового экземпляра
        existing_nums = [f.num for f in self.filters if f.name == filter_name]
        next_num = max(existing_nums, default=0) + 1

        new_filter = f_class(next_num, self.cache_dir)
        self.filters.append(new_filter)
        self.save_project()

    def save_project(self):
        """Переопределяем сохранение, чтобы включить фильтры"""
        if not self.current_json_path: return

        # Собираем конфигурации фильтров
        filter_configs = []
        for f in self.filters:
            filter_configs.append({
                "name": f.name,
                "num": f.num,
                "enabled": f.enabled,
                "params": f.get_params()
            })

        full_data = {
            "scenes": self.scenes,
            "filters": filter_configs
        }

        try:
            with open(self.current_json_path, 'w', encoding='utf-8') as f:
                json.dump(full_data, f, ensure_ascii=False, indent=4)
        except Exception as e:
            print(f"Ошибка сохранения расширенного проекта: {e}")

    def move_filter(self, index, direction):
        """direction: -1 (вверх), 1 (вниз)"""
        new_idx = index + direction
        if 0 <= new_idx < len(self.filters):
            self.filters[index], self.filters[new_idx] = self.filters[new_idx], self.filters[index]
            self.save_project()
            return True
        return False