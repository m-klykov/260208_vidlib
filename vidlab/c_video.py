from PySide6.QtCore import QObject, QTimer, Signal

from .m_project import VideoProjectModel
from .m_video import VideoModel

class VideoController(QObject):
    video_loaded = Signal()  # Сигнал без параметров, так как View сама возьмет данные из модели
    scenes_updated = Signal(list) # сигнал для обновления виджета сцен
    frame_updated = Signal(object) # Передает кадр для отрисовки
    position_changed = Signal(int) # Передает текущий индекс кадра
    playing_changed = Signal(bool)  # True если играет, False если пауза
    cropped_mode_changed = Signal(bool)  # Сигнал для обновления UI

    def __init__(self):
        super().__init__()
        self.model = VideoModel()
        self.project = VideoProjectModel()  # Модель для JSON

        self.timer = QTimer()
        self.timer.timeout.connect(self._play_step)
        self._is_playing = False
        self.cropped_mode = False

    @property
    def is_playing(self):
        return self._is_playing

    def set_cropped_mode(self, enabled):
        if self.cropped_mode == enabled: return

        self.cropped_mode = enabled

        # Если включили режим, а мы вне диапазона — прыгаем в начало
        if enabled:
            in_f = self.get_in_index()
            out_f = self.get_out_index()

            if self.model.current_idx < in_f or self.model.current_idx > out_f:
                self.seek(in_f)

        self.cropped_mode_changed.emit(enabled)
        # Обновляем список и слайдер
        self.scenes_updated.emit(self.project.scenes)

    def load_video(self, path):
        print(f"c: open {path}")

        if self.model.open_video(path):
            self.stop()  # Сброс состояния
            self.seek(self.model.get_min_index())
            self.video_loaded.emit()  # Уведомляем всех подписанных

            # Загружаем сцены из JSON при открытии видео
            scenes = self.project.load_project(path)
            self.scenes_updated.emit(scenes)  # Сообщаем View, что сцены загружены

            return True
        return False

    def toggle_play(self):
        if self._is_playing:
            self.stop()
        else:
            if self.model.cap:
                self._is_playing = True
                self.timer.start(int(1000 / self.model.fps))
                self.playing_changed.emit(True)

    def stop(self):
        self._is_playing = False
        self.timer.stop()
        self.playing_changed.emit(False)

    def _play_step(self):
        frame = self.model.get_frame()
        if frame is not None:
            self.frame_updated.emit(frame)
            self.position_changed.emit(self.model.get_current_index())
        else:
            self.stop()

    def seek(self, position):
        self.stop() # Останавливаем при перемотке

        if self.cropped_mode:
            in_f = self.get_in_index()
            out_f = self.get_out_index()
            position = max(in_f, min(position, out_f))

        frame = self.model.get_frame(position)
        if frame is not None:
            self.frame_updated.emit(frame)
            self.position_changed.emit(position)

    def step_forward(self):
        self.stop()
        curr = self.model.get_current_index()
        self.seek(curr + 1)

    def step_backward(self):
        self.stop()
        curr = self.model.get_current_index()
        self.seek(max(0, curr - 2)) # -2 т.к. после чтения индекс уже смещен вперед

    def to_start(self):
        self.seek(self.model.get_min_index())

    def to_end(self):
        self.seek(self.model.get_max_index())

    def get_in_index(self):
        return self.project.get_in_frame(self.model.get_min_index())

    def get_out_index(self):
        return self.project.get_out_frame(self.model.get_max_index())


    def to_in_point(self):
        self.seek(self.get_in_index())

    def to_out_point(self):
        self.seek(self.get_out_index())

    def add_current_scene(self):
        idx = self.model.current_idx
        self.project.add_scene(idx)
        self.scenes_updated.emit(self.project.scenes)

    def delete_scene(self, frame_idx):
        self.project.remove_scene(frame_idx)
        self.scenes_updated.emit(self.project.scenes)

    def rename_scene(self, frame_idx, full_text):
        # Извлекаем текст после последней закрывающей скобки
        # Строка: "00:00:01 [100] Моя сцена" -> "Моя сцена"
        if "]" in full_text:
            new_title = full_text.split("]")[-1].strip()
        else:
            new_title = full_text.strip()

        self.project.update_scene_title(frame_idx, new_title)
        self.scenes_updated.emit(self.project.scenes)

    def relocate_scene(self, old_frame_idx):
        new_idx = self.model.current_idx

        if self.project.update_scene_frame(old_frame_idx, new_idx):
            self.scenes_updated.emit(self.project.scenes)
            return True

        return False

    def add_special_mark(self, m_type):
        idx = self.model.current_idx
        # Модель сама разберется с удалением дубликатов типа
        self.project.add_special_mark(idx, m_type)
        self.scenes_updated.emit(self.project.scenes)

