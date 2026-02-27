import numpy as np


class SlamBaseModel:
    def __init__(self, is_batch_mode=False):
        self.is_batch_mode = is_batch_mode

        # 1. Загружаем метаданные (описание параметров)
        self.metadata = self.get_params_metadata()

        # 2. Инициализируем конфиг дефолтными значениями из метаданных
        self.config = {
            name: info.get("default")
            for name, info in self.metadata.items()
        }

        # 3. Добавляем неконфигурируемые системные параметры
        self._add_system_params()

        # 4. Сбрасываем состояние
        self.reset()

    def _add_system_params(self):
        """Параметры, которые не выносятся в UI фильтра"""
        self.internal_seed = 42

    def get_params_metadata(self) -> dict:
        """
        Тестовые параметры для отладки фильтра.
        """
        return {
            "test_points_count": {"type": "int", "min": 0, "max": 1000, "default": 100},
            "test_speed": {"type": "float", "min": 0.0, "max": 5.0, "default": 1.0}
        }

    def set_params(self, all_params: dict):
        """Забирает только те параметры, которые описаны в метаданных модели"""
        for name in self.metadata:
            if name in all_params:
                self.config[name] = all_params[name]

    def get_param(self, name, default=None):
        """Безопасное получение параметра из конфига"""
        return self.config.get(name, default)

    def reset(self):
        """Базовая очистка состояния"""
        self.prev_gray = None
        self.last_idx = -1

        # Очистка навигации
        self.curr_x, self.curr_y, self.curr_yaw = 0.0, 0.0, 0.0
        self.curr_pitch, self.curr_roll = 0.0, 0.0
        self.curr_velocity = 0.0

        # Точки (для теста)
        self.pts = []

        # Путь (только в пакетном режиме)
        self.abs_path = [] if self.is_batch_mode else None

    def update(self, frame, idx):
        """
        Оркестрация обновления.
        Логика сброса и накопления пути здесь, математика — в _process_core.
        """
        if idx == self.last_idx: return

        if idx != self.last_idx + 1:
            self.reset()

        # Вызываем реализацию конкретного алгоритма
        self._process_core(frame, idx)

        # Если нужно копить путь (пакетный режим)
        if self.is_batch_mode:
            self.abs_path.append([self.curr_x, self.curr_y, self.curr_yaw])

        self.last_idx = idx

    def _process_core(self, frame, idx):
        """
        Имитация работы SLAM для тестирования фильтра.
        """
        h, w = frame.shape[:2]

        # 1. Имитируем крен (Roll) по синусоиде
        self.curr_roll = np.sin(idx * 0.1) * 10.0  # +/- 10 градусов
        self.curr_pitch = np.cos(idx * 0.05) * 5.0

        # 2. Имитируем движение вперед по кругу
        speed = self.get_param("test_speed")
        self.curr_velocity = speed
        self.curr_yaw += 0.02 * speed  # Поворачиваем

        self.curr_x += np.sin(self.curr_yaw) * speed
        self.curr_y += np.cos(self.curr_yaw) * speed

        # 3. Имитируем точки («звездное небо», зависящее от параметра)
        num_pts = self.get_param("test_points_count")
        # Генерируем точки только если их количество изменилось или их нет
        if len(self.pts) != num_pts:
            np.random.seed(self.internal_seed)
            self.pts = []
            for _ in range(num_pts):
                self.pts.append({
                    'pt': [np.random.randint(0, w), np.random.randint(0, h)],
                    'age': np.random.randint(0, 50)
                })

    # --- Геттеры для фильтра (вызываются по требованию) ---

    def get_horizon_angles(self):
        """Возвращает (pitch, roll, yaw_abs)"""
        return self.curr_pitch, self.curr_roll, self.curr_yaw

    def get_points(self):
        """Текущий список [{'pt': [x,y], 'age': int}]"""
        return self.pts

    def get_fwd_velocity(self):
        return self.curr_velocity

    def get_full_path(self):
        """Возвращает накопленный путь как numpy массив"""
        if self.abs_path is not None and len(self.abs_path) > 0:
            return np.array(self.abs_path, dtype=np.float32)
        return np.array([], dtype=np.float32)