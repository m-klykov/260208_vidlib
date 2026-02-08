from PySide6.QtCore import QObject, QTimer, Signal
from .m_video import VideoModel

class VideoController(QObject):
    video_loaded = Signal()  # Сигнал без параметров, так как View сама возьмет данные из модели
    frame_updated = Signal(object) # Передает кадр для отрисовки
    position_changed = Signal(int) # Передает текущий индекс кадра
    playing_changed = Signal(bool)  # True если играет, False если пауза

    def __init__(self):
        super().__init__()
        self.model = VideoModel()
        self.timer = QTimer()
        self.timer.timeout.connect(self._play_step)
        self._is_playing = False

    @property
    def is_playing(self):
        return self._is_playing

    def load_video(self, path):
        print(f"c: open {path}")

        if self.model.open_video(path):
            self.stop()  # Сброс состояния
            self.seek(0)
            self.video_loaded.emit()  # Уведомляем всех подписанных

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
        self.seek(0)

    def to_end(self):
        self.seek(self.model.frame_count - 1)