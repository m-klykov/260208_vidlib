import cv2
import os


class VideoExport:
    def __init__(self, output_path, fps, size):
        self.output_path = output_path
        self.fps = fps
        self.size = size  # (width, height)
        self.writer = None
        self._is_cancelled = False

        # Кодек H.264 (AVC).
        # На Windows/Linux через FFmpeg бэкенд обычно используется 'avc1' или 'X264'
        self.fourcc = cv2.VideoWriter_fourcc(*'mp4v')

    def _init_writer(self):
        if self.writer is None:
            os.makedirs(os.path.dirname(self.output_path), exist_ok=True)

            # Мы явно указываем бэкенд API_FFMPEG, чтобы OpenCV
            # использовал библиотеки ffmpeg для кодирования в H.264
            self.writer = cv2.VideoWriter(
                self.output_path,
                cv2.CAP_FFMPEG,  # Используем бэкенд FFMPEG
                self.fourcc,
                self.fps,
                self.size,
                True  # isColor
            )



    def write_frame(self, frame):
        if self._is_cancelled:
            return
        self._init_writer()

        # Защита: VideoWriter ожидает точный размер, указанный при инициализации
        if (frame.shape[1], frame.shape[0]) != self.size:
            frame = cv2.resize(frame, self.size)

        self.writer.write(frame)

    def finish(self):
        if self.writer:
            self.writer.release()
            self.writer = None
        print(f"Экспорт успешно завершен: {self.output_path}")

    def cancel(self):
        self._is_cancelled = True
        if self.writer:
            self.writer.release()
            self.writer = None

        if os.path.exists(self.output_path):
            try:
                os.remove(self.output_path)
                print(f"Экспорт отменен, файл удален.")
            except Exception as e:
                print(f"Не удалось удалить файл: {e}")