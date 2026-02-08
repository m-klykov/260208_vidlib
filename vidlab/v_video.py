import cv2
from PySide6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QSlider, QLabel
from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QImage, QPixmap
from .c_video import VideoController
from .m_video import VideoModel

class VideoWidget(QWidget):
    def __init__(self, controller):
        super().__init__()
        self.controller : VideoController = controller

        # Разрешаем виджету принимать фокус клавиатуры
        self.setFocusPolicy(Qt.StrongFocus)

        self._init_ui()
        self._connect_signals()

    def _init_ui(self):
        layout = QVBoxLayout(self)

        # Экран
        self.video_label = QLabel("Загрузите видео")
        self.video_label.setAlignment(Qt.AlignCenter)
        self.video_label.setStyleSheet("background-color: black;")
        self.video_label.setMinimumSize(640, 360)
        layout.addWidget(self.video_label)

        # Слайдер
        self.slider = QSlider(Qt.Horizontal)
        self.slider.setFocusPolicy(Qt.StrongFocus)  # Слайдер может принимать фокус

        layout.addWidget(self.slider)

        # Кнопки управления
        controls = QHBoxLayout()
        self.btn_start = QPushButton("|<")
        self.btn_back = QPushButton("<")
        self.btn_play = QPushButton("Play")
        self.btn_forward = QPushButton(">")
        self.btn_end = QPushButton(">|")

        for btn in [self.btn_start, self.btn_back, self.btn_play, self.btn_forward, self.btn_end]:
            btn.setFocusPolicy(Qt.NoFocus)  # Кнопки больше не крадут фокус у виджета
            controls.addWidget(btn)

        layout.addLayout(controls)

    def _connect_signals(self):
        # От UI к контроллеру
        self.btn_play.clicked.connect(self.controller.toggle_play)
        self.btn_start.clicked.connect(self.controller.to_start)
        self.btn_end.clicked.connect(self.controller.to_end)
        self.btn_forward.clicked.connect(self.controller.step_forward)
        self.btn_back.clicked.connect(self.controller.step_backward)

        # Слайдер
        self.slider.valueChanged.connect(self._on_slider_changed)

        # От контроллера к UI
        self.controller.frame_updated.connect(self.render_frame)
        self.controller.position_changed.connect(self.update_slider)
        self.controller.playing_changed.connect(self.update_play_button)

    def render_frame(self, frame):
        if frame is None: return

        # Конвертация OpenCV -> PySide
        frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        h, w, ch = frame.shape
        img = QImage(frame.data, w, h, ch * w, QImage.Format_RGB888)

        pix = QPixmap.fromImage(img)
        # Масштабируем кадр под размер лейбла с сохранением пропорций
        self.video_label.setPixmap(pix.scaled(self.video_label.size(), Qt.KeepAspectRatio, Qt.SmoothTransformation))

    def update_slider(self, pos):
        # Блокируем сигналы, чтобы перемещение ползунка программно не вызывало seek в контроллере
        self.slider.blockSignals(True)
        if self.controller.model.frame_count > 0:
            self.slider.setMaximum(self.controller.model.frame_count - 1)
        self.slider.setValue(pos)
        self.slider.blockSignals(False)

    def update_play_button(self, is_playing):
        self.btn_play.setText("Pause" if is_playing else "Play")

    def _on_slider_changed(self, value):
        # Вызываем seek только если изменение пришло от пользователя (мышка/клавиатура)
        # а не от таймера воспроизведения (сигнал blockSignals в update_slider это учтет)
        if not self.slider.signalsBlocked():
            self.controller.seek(value)

    # Обработка клавиатуры
    def keyPressEvent(self, event):
        if event.key() == Qt.Key_Space:
            self.controller.toggle_play()
            event.accept()

        elif event.key() == Qt.Key_Right:
            self.controller.step_forward()
            event.accept()

        elif event.key() == Qt.Key_Left:
            self.controller.step_backward()
            event.accept()

        else:
            super().keyPressEvent(event)