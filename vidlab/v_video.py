import cv2
from PySide6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QSlider, QLabel, QSizePolicy
from PySide6.QtGui import Qt, QImage, QPixmap
from .c_video import VideoController
from .m_video import VideoModel
from .v_timeline import TimelineWidget
from .v_video_display import VideoDisplay


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
        # ЗАМЕНА: Вместо QLabel используем наш новый дисплей
        self.video_display = VideoDisplay(self.controller)
        self.video_display.setMinimumSize(640, 360)
        self.video_display.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        layout.addWidget(self.video_display)

        # Ряд со слайдером и временем
        slider_layout = QHBoxLayout()

        # Стиль для шрифта: жирный и увеличенный (например, 14px)
        font_style = "font-size: 14px; font-weight: bold; color: #2c3e50;"

        # Индикатор текущего времени/кадра
        self.lbl_time = QLabel("0 (00:00:00.00)")
        self.lbl_time.setStyleSheet(font_style)
        self.lbl_time.setMinimumWidth(120)  # Чтобы слайдер не прыгал при смене цифр

        # Слайдер
        # self.slider = QSlider(Qt.Horizontal)
        # self.slider.setFocusPolicy(Qt.StrongFocus)  # Слайдер может принимать фокус
        self.timeline = TimelineWidget(self.controller)
        self.timeline.setFocusPolicy(Qt.StrongFocus)

        # Правый индикатор (общая длительность)
        self.lbl_total = QLabel("0 (00:00:00.00)")
        self.lbl_total.setStyleSheet(font_style)
        self.lbl_total.setMinimumWidth(120)
        # self.lbl_total.setAlignment(Qt.AlignRight)

        slider_layout.addWidget(self.lbl_time)
        # slider_layout.addWidget(self.slider)
        slider_layout.addWidget(self.timeline)
        slider_layout.addWidget(self.lbl_total)
        layout.addLayout(slider_layout)

        # Кнопки управления
        controls = QHBoxLayout()
        self.btn_start = QPushButton("|<")
        self.btn_start.clicked.connect(self.controller.to_start)

        self.btn_end = QPushButton(">|")
        self.btn_end.clicked.connect(self.controller.to_end)

        # self.btn_go_in = QPushButton("In<")  # К началу области
        # self.btn_go_in.setToolTip("Перейти к началу области (In)")
        # self.btn_go_in.clicked.connect(self.controller.to_in_point)
        #
        # self.btn_go_out = QPushButton(">Out")  # К концу области
        # self.btn_go_out.setToolTip("Перейти к концу области (Out)")
        # self.btn_go_out.clicked.connect(self.controller.to_out_point)

        self.btn_prev = QPushButton("←")
        self.btn_prev.setToolTip("предыдущий маркер")
        self.btn_prev.clicked.connect(self.controller.to_prev_marker)

        self.btn_next = QPushButton("→")
        self.btn_next.setToolTip("следующий маркер")
        self.btn_next.clicked.connect(self.controller.to_next_marker)

        self.btn_back = QPushButton("<")
        self.btn_back.setToolTip("На кадр назад")
        self.btn_back.clicked.connect(self.controller.step_backward)

        self.btn_forward = QPushButton(">")
        self.btn_forward.setToolTip("На кадр вперед")
        self.btn_forward.clicked.connect(self.controller.step_forward)

        self.btn_play = QPushButton("▶ Play")
        self.btn_play.clicked.connect(self.controller.toggle_play)

        for btn in [self.btn_start, #self.btn_go_in,
                    self.btn_prev, self.btn_back,
                    self.btn_play,
                    self.btn_forward, self.btn_next,
                    self.btn_end]: # self.btn_go_out,
            btn.setFocusPolicy(Qt.NoFocus)  # Кнопки больше не крадут фокус у виджета
            btn.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
            controls.addWidget(btn)

        layout.addLayout(controls)

    def _connect_signals(self):
        # От UI к контроллеру

        # Слайдер
        # self.slider.valueChanged.connect(self._on_slider_changed)

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

        # Конвертация BGR -> RGB
        rgb_frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        h, w, ch = rgb_frame.shape
        img = QImage(rgb_frame.data, w, h, ch * w, QImage.Format_RGB888)

        # Просто отдаем пиксмап дисплею
        self.video_display.set_pixmap(QPixmap.fromImage(img))

    def update_slider_range(self):
        if self.controller.cropped_mode:
            in_f = self.controller.get_in_index()
            out_f = self.controller.get_out_index()
        else:
            in_f = self.controller.model.get_min_index()
            out_f = self.controller.model.get_max_index()

        # self.slider.setRange(in_f, out_f)
        self.timeline.update()

        # self.btn_start.setVisible(not self.controller.cropped_mode)
        # self.btn_end.setVisible(not self.controller.cropped_mode)


    def update_slider(self, pos):
        # Блокируем сигналы, чтобы перемещение ползунка программно не вызывало seek в контроллере
        if self.controller.model.frame_count > 0:
            # Обновляем правую метку (длительность)
            self.lbl_total.setText(self.controller.model.get_total_timestamp())

        # Заставляем таймлайн перерисовать Playhead на новой позиции
        self.timeline.update()

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
        modifiers = event.modifiers()
        key = event.key()

        if key == Qt.Key_Space:
            self.controller.toggle_play()
            event.accept()

        elif key == Qt.Key_Right:
            if modifiers & Qt.ControlModifier:
                # Ctrl + Right: к следующему маркеру
                self.controller.to_next_marker()
            else:
                # Просто Right: на один кадр вперед
                self.controller.step_forward()
            event.accept()

        elif key == Qt.Key_Left:
            if modifiers & Qt.ControlModifier:
                # Ctrl + Left: к предыдущему маркеру
                self.controller.to_prev_marker()
            else:
                # Просто Left: на один кадр назад
                self.controller.step_backward()
            event.accept()
        elif key == Qt.Key_Up:
            if modifiers & Qt.ControlModifier:
                # Ctrl + Up: к метке входа (In-point)
                self.controller.to_in_point()
                event.accept()

        elif key == Qt.Key_Down:
            if modifiers & Qt.ControlModifier:
                # Ctrl + Down: к метке выхода (Out-point)
                self.controller.to_out_point()
                event.accept()

        else:
            super().keyPressEvent(event)