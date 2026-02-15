import struct
import os
import numpy as np
from collections import OrderedDict


class TrackerStorage:
    # Константы формата
    FILE_SIG = b'TRK!'  # Сигнатура в начале файла
    FOOTER_SIG = b'RGST'  # Сигнатура таблицы диапазонов (Range Table)
    HEADER_SIZE = 8  # 4 байта Sig + 4 байта MaxFrame
    FRAME_SIZE = 8  # 2 x float32 (x, y)

    def __init__(self, file_path, max_cache_blocks=10, block_size=1000):
        self.file_path = file_path
        self.max_frame = 0
        self.tracked_ranges = []

        # Настройки кэша
        self.block_size = block_size
        self.max_cache_blocks = max_cache_blocks
        self.cache = OrderedDict()

        # Инициализация
        if os.path.exists(self.file_path):
            self._load_metadata()

    def _load_metadata(self):
        """Читает заголовок и таблицу диапазонов из хвоста."""
        file_size = os.path.getsize(self.file_path)
        print(f"track file size :{file_size}")
        if file_size < self.HEADER_SIZE:
            print(f"track file too small size")
            return

        with open(self.file_path, 'rb') as f:
            # 1. Заголовок
            sig, self.max_frame = struct.unpack('<4sI', f.read(self.HEADER_SIZE))
            print(f"track file open")
            if sig != self.FILE_SIG:
                print(f"track file bad sig")
                return

            # 2. Ищем хвост. Таблица лежит СРАЗУ после данных (HEADER + max_frame * 8)
            footer_pos = self.HEADER_SIZE + self.max_frame * self.FRAME_SIZE
            if file_size < footer_pos + 8:  # Минимум Sig + Len
                print(f"track file bad fot pos {footer_pos}")
                return

            f.seek(footer_pos)
            footer_sig, table_count = struct.unpack('<4sI', f.read(8))

            if footer_sig == self.FOOTER_SIG:
                # Читаем таблицу: table_count пар по 4+4 байта
                ranges_bytes = f.read(table_count * 8)
                if len(ranges_bytes) == table_count * 8:
                    self.tracked_ranges = list(struct.iter_unpack('<II', ranges_bytes))
            else:
                print(f"track file bad foot sig")

        print(f"track file fr count :{self.max_frame}. blocks: {len(self.tracked_ranges)}")

    def get_delta(self, frame_idx):
        """Публичный метод получения смещения для кадра."""
        if frame_idx >= self.max_frame:
            return 0.0, 0.0

        # Проверка по карте диапазонов (быстро)
        # in_range = False
        # for start, end in self.tracked_ranges:
        #     if start <= frame_idx < end:
        #         in_range = True
        #         break
        #
        # if not in_range:
        #     return 0.0, 0.0

        # Кэшированное чтение
        block_idx = frame_idx // self.block_size
        if block_idx not in self.cache:
            self._load_block_to_cache(block_idx)

        self.cache.move_to_end(block_idx)
        local_idx = frame_idx % self.block_size
        return self.cache[block_idx][local_idx]

    def _load_block_to_cache(self, block_idx):
        """Подгружает блок кадров с диска в память."""
        if len(self.cache) >= self.max_cache_blocks:
            self.cache.popitem(last=False)

        block_data = np.zeros((self.block_size, 2), dtype=np.float32)
        start_f = block_idx * self.block_size
        file_offset = self.HEADER_SIZE + start_f * self.FRAME_SIZE

        if os.path.exists(self.file_path):
            f_size = os.path.getsize(self.file_path)
            if file_offset < f_size:
                with open(self.file_path, 'rb') as f:
                    f.seek(file_offset)
                    # Читаем либо целый блок, либо до начала хвоста
                    bytes_to_read = min(self.block_size * self.FRAME_SIZE,
                                        (self.max_frame * self.FRAME_SIZE) - (start_f * self.FRAME_SIZE))
                    if bytes_to_read > 0:
                        raw = f.read(bytes_to_read)
                        loaded = np.frombuffer(raw, dtype=np.float32).reshape(-1, 2)
                        block_data[:len(loaded)] = loaded

        self.cache[block_idx] = block_data

    def write_block(self, start_frame, data):
        """Записывает блок дельт и переписывает хвост."""
        num_frames = len(data)
        end_frame = start_frame + num_frames

        # 1. Обновляем метаданные
        self.max_frame = max(self.max_frame, end_frame)
        self._update_tracked_ranges(start_frame, end_frame)

        # 2. Запись
        # Режим 'a+b' не подходит для seek(0), 'r+b' капризен.
        # Если файла нет, создаем его через 'wb', если есть — 'r+b'
        if not os.path.exists(self.file_path):
            with open(self.file_path, 'wb') as f:
                f.write(struct.pack('<4sI', self.FILE_SIG, self.max_frame))

        with open(self.file_path, 'r+b') as f:
            # Заголовок
            f.seek(0)
            f.write(struct.pack('<4sI', self.FILE_SIG, self.max_frame))

            # Данные (с заполнением пустот нулями)
            target_pos = self.HEADER_SIZE + start_frame * self.FRAME_SIZE
            f_size = os.path.getsize(self.file_path)
            if target_pos > f_size:
                f.seek(f_size)
                f.write(b'\x00' * (target_pos - f_size))

            f.seek(target_pos)
            f.write(data.astype(np.float32).tobytes())

            # Хвост: Сигнатура + Кол-во + Пары (start, end)
            f.seek(self.HEADER_SIZE + self.max_frame * self.FRAME_SIZE)
            f.write(struct.pack('<4sI', self.FOOTER_SIG, len(self.tracked_ranges)))
            for r_start, r_end in self.tracked_ranges:
                f.write(struct.pack('<II', r_start, r_end))

            # Обрезаем лишнее, если старый хвост был длиннее
            f.truncate()
            f.flush()  # Принудительно сбрасываем на диск

        # Сброс кэша для актуализации данных
        self.cache.clear()

    def _update_tracked_ranges(self, start, end):
        """Добавление интервала с мержем."""
        self.tracked_ranges.append((start, end))
        self.tracked_ranges.sort()

        if not self.tracked_ranges:
            return

        merged = []
        curr_s, curr_e = self.tracked_ranges[0]
        for next_s, next_e in self.tracked_ranges[1:]:
            if next_s <= curr_e:
                curr_e = max(curr_e, next_e)
            else:
                merged.append((curr_s, curr_e))
                curr_s, curr_e = next_s, next_e
        merged.append((curr_s, curr_e))
        self.tracked_ranges = merged

    def get_ranges(self):
        """Для отрисовки таймлайна."""
        return self.tracked_ranges

    def clear_all(self):
        """Полное удаление данных трекинга с диска и из памяти."""
        # 1. Очищаем кэш в оперативной памяти
        self.cache.clear()

        # 2. Сбрасываем метаданные
        self.max_frame = 0
        self.tracked_ranges = []

        # 3. Удаляем файл физически
        if os.path.exists(self.file_path):
            try:
                os.remove(self.file_path)
            except Exception as e:
                print(f"Error deleting tracking file: {e}")
                # Если файл занят, можно попробовать хотя бы обнулить его
                with open(self.file_path, 'wb') as f:
                    f.truncate(0)