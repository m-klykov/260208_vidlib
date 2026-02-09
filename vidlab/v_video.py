import cv2
from PySide6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QSlider, QLabel, QSizePolicy
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
        # Важно: разрешаем лейблу сжиматься и растягиваться во все стороны
        self.video_label.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)

        layout.addWidget(self.video_label)

        # Ряд со слайдером и временем
        slider_layout = QHBoxLayout()

        # Стиль для шрифта: жирный и увеличенный (например, 14px)
        font_style = "font-size: 14px; font-weight: bold; color: #2c3e50;"

        # Индикатор текущего времени/кадра
        self.lbl_time = QLabel("0 (00:00:00.00)")
        self.lbl_time.setStyleSheet(font_style)
        self.lbl_time.setMinimumWidth(120)  # Чтобы слайдер не прыгал при смене цифр

        # Слайдер
        self.slider = QSlider(Qt.Horizontal)
        self.slider.setFocusPolicy(Qt.StrongFocus)  # Слайдер может принимать фокус

        # Правый индикатор (общая длительность)
        self.lbl_total = QLabel("0 (00:00:00.00)")
        self.lbl_total.setStyleSheet(font_style)
        self.lbl_total.setMinimumWidth(120)
        # self.lbl_total.setAlignment(Qt.AlignRight)

        slider_layout.addWidget(self.lbl_time)
        slider_layout.addWidget(self.slider)
        slider_layout.addWidget(self.lbl_total)
        layout.addLayout(slider_layout)

        # Кнопки управления
        controls = QHBoxLayout()
        self.btn_start = QPushButton("|<")
        self.btn_go_in = QPushButton("In<")  # К началу области
        self.btn_go_in.setToolTip("Перейти к началу области (In)")
        self.btn_back = QPushButton("<")
        self.btn_play = QPushButton("▶ Play")
        self.btn_forward = QPushButton(">")
        self.btn_go_out = QPushButton(">Out")  # К концу области
        self.btn_go_out.setToolTip("Перейти к концу области (Out)")
        self.btn_end = QPushButton(">|")

        self.btn_go_in.setToolTip("Перейти к началу области (In)")
        self.btn_go_out.setToolTip("Перейти к концу области (Out)")

        for btn in [self.btn_start, self.btn_go_in, self.btn_back,
                    self.btn_play,
                    self.btn_forward, self.btn_go_out, self.btn_end]:
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
        self.btn_go_in.clicked.connect(self.controller.to_in_point)
        self.btn_go_out.clicked.connect(self.controller.to_out_point)

        # Слайдер
        self.slider.valueChanged.connect(self._on_slider_changed)

        # От контроллера к UI
        self.controller.frame_updated.connect(self.render_frame)
        self.controller.position_changed.connect(self.update_slider)
        self.controller.playing_changed.connect(self.update_play_button)
        self.controller.cropped_mode_changed.connect(self.update_slider_range)

    def resizeEvent(self, event):
        """Срабатывает автоматически при изменении размера окна"""
        super().resizeEvent(event)
        # Если видео загружено и есть последний кадр — перерисовываем его
        last_frame = self.controller.model.get_last_frame()
        if last_frame is not None:
            self.render_frame(last_frame)

    def render_frame(self, frame):
        if frame is None: return

        # Конвертация OpenCV (BGR) -> RGB
        rgb_frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        h, w, ch = rgb_frame.shape
        bytes_per_line = ch * w

        img = QImage(rgb_frame.data, w, h, bytes_per_line, QImage.Format_RGB888)

        # Масштабирование под ТЕКУЩИЙ размер video_label
        # Используем Qt.KeepAspectRatio для сохранения пропорций
        pixmap = QPixmap.fromImage(img)
        scaled_pixmap = pixmap.scaled(
            self.video_label.size(),
            Qt.KeepAspectRatio,
            Qt.SmoothTransformation
        )

        self.video_label.setPixmap(scaled_pixmap)

    def update_slider_range(self):
        if self.controller.cropped_mode:
            in_f = self.controller.get_in_index()
            out_f = self.controller.get_out_index()
        else:
            in_f = self.controller.model.get_min_index()
            out_f = self.controller.model.get_max_index()

        self.slider.setRange(in_f, out_f)

        self.btn_start.setVisible(not self.controller.cropped_mode)
        self.btn_end.setVisible(not self.controller.cropped_mode)


    def update_slider(self, pos):
        # Блокируем сигналы, чтобы перемещение ползунка программно не вызывало seek в контроллере
        self.slider.blockSignals(True)
        if self.controller.model.frame_count > 0:
            self.update_slider_range()
            # Обновляем правую метку (длительность)
            self.lbl_total.setText(self.controller.model.get_total_timestamp())
        self.slider.setValue(pos)
        self.slider.blockSignals(False)

        # Обновляем текстовый индикатор
        timestamp = self.controller.model.get_full_timestamp(pos)
        self.lbl_time.setText(timestamp)

    def update_play_button(self, is_playing):
        self.btn_play.setText("⏸ Pause" if is_playing else "▶ Play")

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