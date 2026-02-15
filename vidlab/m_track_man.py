import numpy as np
import cv2


class TrackerManager:
    def __init__(self, storage, set_keyframe_callback):
        """
        :param storage: Экземпляр TrackerStorage для работы с диском
        :param set_keyframe_callback: Функция фильтра для установки ручного ключа
                                     типа callback(frame_idx, x, y)
        """
        self.storage = storage
        self.set_keyframe_cb = set_keyframe_callback

        self._cv_tracker = None
        self._is_active = False

        # Данные текущего активного сеанса
        self.temp_buffer = []  # Список сырых координат [(x, y), ...]
        self.start_frame = None  # Кадр начала текущего куска
        self.initial_manual_pos = None  # Позиция ручного ключа в начале сегмента

        # Список будущих ручных ключей для отслеживания "встречи"
        self.future_keys = []  # [(frame, x, y), ...]

    def is_active(self):
        return self._is_active

    def init_tracker(self, frame, frame_idx, roi, current_pos, future_keys):
        """
        Инициализация нового сеанса трекинга.
        :param roi: (x, y, w, h) в пикселях для OpenCV
        :param current_pos: (x, y) в формате [-1, 1] текущее положение
        :param future_keys: список всех ручных ключей после текущего кадра
        """
        success = False
        try:
            self._cv_tracker = cv2.TrackerCSRT_create()
            self._cv_tracker.init(frame, roi)
            success = True
        except Exception as e:
            print(f"Tracker init failed: {e}")

        if success:
            self._is_active = True
            self.start_frame = frame_idx
            self.temp_buffer = [current_pos]
            self.initial_manual_pos = current_pos
            self.future_keys = sorted(future_keys, key=lambda x: x[0])
            return True
        return False

    def update(self, frame, frame_idx):
        if not self._is_active:
            return False

        success, box = self._cv_tracker.update(frame)

        if success:
            h, w = frame.shape[:2]
            # Центр бокса в [-1, 1]
            nx = ((box[0] + box[2] / 2) / w) * 2 - 1
            ny = ((box[1] + box[3] / 2) / h) * 2 - 1
            raw_pos = (nx, ny)

            self.temp_buffer.append(raw_pos)

            # Проверяем: не достигли ли мы следующего ручного ключа?
            if self.future_keys and frame_idx >= self.future_keys[0][0]:
                target_key = self.future_keys.pop(0)
                # Запекаем пройденный участок до этого ключа
                self._bake_and_commit(target_key[0], target_key[1], target_key[2])

                # Переинициализируем точку отсчета для следующего сегмента
                self.start_frame = target_key[0]
                self.temp_buffer = [(target_key[1], target_key[2])]
                self.initial_manual_pos = (target_key[1], target_key[2])

            return True
        else:
            self.stop_and_save(frame_idx - 1)
            return False

    def stop_and_save(self, last_valid_frame):
        """Остановка трекера пользователем или при потере цели."""
        if not self._is_active:
            return

        if len(self.temp_buffer) > 1:
            # Создаем ручной ключ в точке остановки (вызываем фильтр)
            final_raw_pos = self.temp_buffer[-1]
            self.set_keyframe_cb(last_valid_frame, final_raw_pos[0], final_raw_pos[1])

            # Запекаем участок
            self._bake_and_commit(last_valid_frame, final_raw_pos[0], final_raw_pos[1])

        self._is_active = False
        self._cv_tracker = None
        self.temp_buffer = []

    def cancel_tracking(self):
        """
        Прерывает текущую сессию трекинга без сохранения данных.
        Используется при ошибках или отмене действия пользователем.
        """
        self._is_active = False
        self._cv_tracker = None
        self.temp_buffer = []
        self.start_frame = None
        self.initial_manual_pos = None
        self.future_keys = []

    def clear_all_data(self):
        """
        Полностью удаляет данные с диска и сбрасывает состояние менеджера.
        """
        self.cancel_tracking()
        self.storage.clear_all()

    def _bake_and_commit(self, end_frame, end_manual_x, end_manual_y):
        if len(self.temp_buffer) < 2:
            return

        # 1. Подготовка данных
        actual_len = end_frame - self.start_frame + 1
        # raw_data - это абсолютные координаты трекера на экране
        raw_data = np.array(self.temp_buffer[:actual_len])

        # 2. Строим "идеальную" линию между ручными ключами (Manual Path)
        m_start = np.array(self.initial_manual_pos)
        m_end = np.array([end_manual_x, end_manual_y])

        t_steps = np.linspace(0, 1, len(raw_data))
        # Точки на прямой между ключами для каждого кадра
        manual_path = m_start + np.outer(t_steps, (m_end - m_start))

        # 3. Вычисляем "сырое" отклонение трекера от этой линии
        # В начальной точке это будет 0 (так как raw_data[0] == m_start)
        # В конечной точке это будет величина дрейфа (drift)
        raw_deltas = raw_data - manual_path

        # 4. Линейная компенсация этого дрейфа
        # Берем отклонение в последнем кадре
        final_drift = raw_deltas[-1]
        # Распределяем его от 0 до final_drift
        drift_correction = np.outer(t_steps, final_drift)

        # 5. Итоговая дельта для записи
        # Теперь:
        # В начале: raw_deltas[0] (это 0) - 0 = 0
        # В конце: raw_deltas[-1] (это final_drift) - final_drift = 0
        baked_deltas = raw_deltas - drift_correction

        # Пишем на диск
        self.storage.write_block(self.start_frame, baked_deltas)

    def get_offset_for_frame(self, frame_idx, current_manual_pos):
        """
        :param current_manual_pos: (x, y) текущая точка на линии между ключами
        """
        if self._is_active and frame_idx >= self.start_frame:
            buf_idx = frame_idx - self.start_frame
            if buf_idx < len(self.temp_buffer):
                # Где сейчас трекер (абсолютные координаты)
                raw_x, raw_y = self.temp_buffer[buf_idx]

                # Где сейчас ручная линия (интерполированный "план")
                curr_m_x, curr_m_y = current_manual_pos

                # Дельта — это просто отклонение трекера от линии в текущий момент
                return (raw_x - curr_m_x,
                        raw_y - curr_m_y)

        # Если не трекаем — берем запеченное из файла
        return self.storage.get_delta(frame_idx)

    def rebake_segment(self, start_frame, end_frame, start_manual_pos, end_manual_pos):
        """
        Пересчитывает дельты на участке так, чтобы они соответствовали новой линии между ключами.
        Гарантирует, что в start_frame и end_frame дельта останется (или станет) 0.
        """
        num_frames = end_frame - start_frame + 1
        if num_frames < 2: return

        # 1. Достаем всё, что было в файле на этом участке
        old_deltas = []
        for f in range(start_frame, end_frame + 1):
            old_deltas.append(self.storage.get_delta(f))
        old_deltas = np.array(old_deltas)

        # 2. Нам нужно убрать дрейф в начале и в конце.
        # В начале (t=0) дрейф = old_deltas[0]
        # В конце (t=1) дрейф = old_deltas[-1]
        t_steps = np.linspace(0, 1, num_frames)

        # Линейная интерполяция дрейфа, который нужно вычесть
        # d_start * (1-t) + d_end * t
        drift_correction = np.outer(1 - t_steps, old_deltas[0]) + np.outer(t_steps, old_deltas[-1])

        # 3. Новые дельты = старые дельты - коррекция дрейфа
        new_deltas = old_deltas - drift_correction

        # 4. Пишем обратно
        self.storage.write_block(start_frame, new_deltas)