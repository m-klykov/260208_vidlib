import cv2

class VideoModel:
    def __init__(self):
        self.cap = None
        self.file_path = None
        self.last_frame = None  # Кэш последнего кадра
        self.current_idx = 0  # Номер текущего кадра
        self.width = 0
        self.height = 0
        self.frame_count = 0
        self.fps = 0
        self.start_frame = 0
        self.end_frame = 0

    def open_video(self, path):
        self.cap = cv2.VideoCapture(path)
        if self.cap.isOpened():
            self.file_path = path
            self.width = int(self.cap.get(cv2.CAP_PROP_FRAME_WIDTH))
            self.height = int(self.cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
            self.frame_count = int(self.cap.get(cv2.CAP_PROP_FRAME_COUNT))
            self.fps = self.cap.get(cv2.CAP_PROP_FPS)
            self.end_frame = self.frame_count - 1
            return True
        return False

    def get_frame(self, frame_no=None):
        if self.cap is None: return None

        if frame_no is not None:
            self.cap.set(cv2.CAP_PROP_POS_FRAMES, frame_no)

        ret, frame = self.cap.read()
        if ret:
            self.last_frame = frame
            self.current_idx = int(self.cap.get(cv2.CAP_PROP_POS_FRAMES)) - 1
            return self.last_frame
        return None

    def get_last_frame(self):
        """Возвращает последний прочитанный кадр без обращения к видеопотоку"""
        return self.last_frame

    def get_current_index(self):
        return self.current_idx