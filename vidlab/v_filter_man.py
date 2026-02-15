from PySide6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QListWidget,
                               QListWidgetItem, QPushButton, QMenu, QCheckBox, QLabel, QScrollArea, QMessageBox,
                               QProgressBar, QSlider, QComboBox, QSpinBox)
from PySide6.QtCore import Qt, Signal, QTimer

from vidlab.c_video import VideoController
from vidlab.f_asinc_base import FilterAsyncBase


class FilterManagerWidget(QWidget):
    def __init__(self, controller):
        super().__init__()
        self.controller : VideoController= controller
        self.project = controller.project
        self._init_ui()

        self.param_widgets = {}  # Словарь для хранения ссылок { "param_name": widget }
        self._current_filter_obj = None

        self.controller.scenes_updated.connect(self.refresh_list)
        self.controller.filter_params_changed.connect(self._update_ui_from_params)
        self.controller.detection_failed.connect(self._on_detection_failed)
        # self.refresh_list()

    def _init_ui(self):
        layout = QVBoxLayout(self)

        # --- Список фильтров ---
        self.list_widget = QListWidget()
        self.list_widget.currentRowChanged.connect(self._on_filter_selected)
        self.list_widget.itemChanged.connect(self._on_item_changed)
        layout.addWidget(QLabel("Стек фильтров:"))
        layout.addWidget(self.list_widget)

        # --- Кнопки управления списком ---
        btn_layout = QHBoxLayout()
        self.btn_add = QPushButton("➕Add")
        self.btn_del = QPushButton("🗑Del")
        self.btn_up = QPushButton("↑Up")
        self.btn_down = QPushButton("↓Down")

        for b in [self.btn_add, self.btn_del, self.btn_up, self.btn_down]:
            btn_layout.addWidget(b)
        layout.addLayout(btn_layout)

        # --- Панель параметров ---
        layout.addWidget(QLabel("Параметры:"))
        self.params_scroll = QScrollArea()
        self.params_scroll.setWidgetResizable(True)
        self.params_container = QWidget()
        self.params_layout = QVBoxLayout(self.params_container)
        self.params_layout.setAlignment(Qt.AlignTop)
        self.params_scroll.setWidget(self.params_container)
        layout.addWidget(self.params_scroll)

        # Кнопка анализа (создаем заранее, будем скрывать/показывать)
        self.btn_analyze = QPushButton("Analyze Video")
        self.btn_analyze.clicked.connect(self.on_analyze_clicked)
        self.btn_analyze.setVisible(False)
        layout.addWidget(self.btn_analyze)

        self.progress_bar = QProgressBar()
        self.progress_bar.setVisible(False)
        layout.addWidget(self.progress_bar)

        # Таймер для обновления состояния кнопок и прогресс-бара
        self.update_timer = QTimer()
        self.update_timer.timeout.connect(self.sync_ui_state)
        self.update_timer.start(200)  # 5 раз в секунду достаточно

        # Подключение действий
        self.btn_add.clicked.connect(self._show_add_menu)
        self.btn_del.clicked.connect(self._delete_filter)
        self.btn_up.clicked.connect(lambda: self._move_filter(-1))
        self.btn_down.clicked.connect(lambda: self._move_filter(1))

    def refresh_list(self):
        """Синхронизирует UI со списком фильтров в проекте"""
        self._on_filter_selected(-1)
        self.list_widget.clear()
        for f in self.project.filters:
            item = QListWidgetItem(f.get_id())
            # Добавляем чекбокс прямо в элемент списка (или можно кастомный виджет)
            item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
            item.setCheckState(Qt.Checked if f.enabled else Qt.Unchecked)
            self.list_widget.addItem(item)

        self.controller.refresh_current_frame()  # Обновить превью

    def _on_filter_selected(self, index):

        # 1. Отключаем старые сигналы, если были
        # if self._current_filter_obj is not None:
        #     try:
        #         self._current_filter_obj.params_changed.disconnect(self._update_ui_from_params)
        #     except:
        #         pass

        # Очищаем старую панель
        # Очищаем старую панель максимально безопасно
        while self.params_layout.count():
            item = self.params_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()  # Правильный способ удаления виджета в Qt
            elif item.layout() is not None:
                # Если это вложенный лайаут (как наш hbox с ползунком), чистим и его
                self._clear_sub_layout(item.layout())

        self.param_widgets = {}

        if index < 0 or index >= len(self.project.filters):
            self._current_filter_obj = None
            return

        selected_filter = self.project.filters[index]
        self._current_filter_obj = selected_filter

        # 2. Подписываемся на изменения из фильтра (от мышки)
        # selected_filter.params_changed.connect(self._update_ui_from_params)
        if selected_filter.can_tracking():
            hbox = QHBoxLayout()

            self.btn_track = QPushButton("🎯 Start Auto-Track")
            self.btn_track.setCheckable(True)
            self.btn_track.clicked.connect(self._on_track_clicked)
            hbox.addWidget(self.btn_track)

            self.btn_track_reset = QPushButton("Clear data")
            self.btn_track_reset.setFixedWidth(100)
            self.btn_track_reset.clicked.connect(self._on_track_reset_clicked)
            hbox.addWidget(self.btn_track_reset)

            self.params_layout.addLayout(hbox)

        # Устанавливаем фокус (для Overlay в будущем)
        for f in self.project.filters: f.focused = False
        selected_filter.focused = True

        # Строим UI на основе метаданных
        metadata = selected_filter.get_params_metadata()
        for key, info in metadata.items():
            self._add_param_control(selected_filter, key, info)

        # Показываем кнопку только если фильтр — асинхронный
        is_async = isinstance(selected_filter, FilterAsyncBase)
        self.btn_analyze.setVisible(is_async)
        self.progress_bar.setVisible(is_async)
        self.sync_ui_state()

        self.controller.refresh_current_frame()  # Обновить превью

    def sync_ui_state(self):
        """Вызывается по таймеру для обновления текста кнопки и прогресса"""
        if (not self._current_filter_obj
        or not isinstance(self._current_filter_obj, FilterAsyncBase)):
            return

        f = self._current_filter_obj
        if f.is_analyzing:
            self.btn_analyze.setText("Stop Analysis")
            self.btn_analyze.setStyleSheet("background-color: #ffaaaa;")  # Подсветим красным
            self.progress_bar.setVisible(True)
            self.progress_bar.setValue(f.progress)

        else:
            self.btn_analyze.setText("Start Analysis")
            self.btn_analyze.setStyleSheet("")
            self.progress_bar.setVisible(f.progress > 0 and f.progress < 100)
            self.progress_bar.setValue(f.progress)

        self.controller.refresh_current_frame()

    def on_analyze_clicked(self):
        if (not self._current_filter_obj
                or not isinstance(self._current_filter_obj, FilterAsyncBase)):
            return

        f = self._current_filter_obj

        if f.is_analyzing:
            f.stop_analysis()
        else:
            # Перед запуском прокидываем путь к видео из модели
            f.video_path = self.controller.model.file_path
            f.start_analysis()

    def _on_track_clicked(self, checked):
        if checked:
            # Пытаемся запустить через контроллер
            success = self.controller.start_track_focused()
            if not success:
                self.btn_track.setChecked(False)
                return
            self.btn_track.setText("🛑 Stop Tracking")
            self.btn_track.setStyleSheet("background-color: #ffaaaa;")
        else:
            # Останавливаем
            self._current_filter_obj.stop_tracker()
            self.controller.stop()  # Предположим, вы назвали его так
            self.btn_track.setText("🎯 Start Auto-Track")
            self.btn_track.setStyleSheet("")
            self.controller.project.save_project()

        self.controller.refresh_current_frame()

    def _on_track_reset_clicked(self):
        if not self._current_filter_obj:
            return

        confirmed = self._ask_confirm(
            "Удаление данных трекинга",
            "Вы уверены, что хотите удалить все данные трекиннга?"
        )

        if not confirmed: return

        self._current_filter_obj.reset_tracking()
        self.btn_track.setChecked(False)
        self.controller.refresh_current_frame()

    def _on_detection_failed(self):
        self.btn_track.setChecked(False)


    def _clear_sub_layout(self, layout):
        """Рекурсивно очищает вложенные лайауты"""
        while layout.count():
            item = layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()
            elif item.layout() is not None:
                self._clear_sub_layout(item.layout())

    def _add_param_control(self, filter_obj, key, info):
        hbox = QHBoxLayout()
        hbox.addWidget(QLabel(f"{key}:"))

        p_type = info.get('type')
        current_val = filter_obj.get_param(key, info.get('default'))

        # Создаем запись в словаре виджетов
        self.param_widgets[key] = {'type': p_type}

        if p_type == 'int':
            slider = QSlider(Qt.Horizontal)
            slider.setRange(info['min'], info['max'])
            slider.setValue(int(current_val))
            label = QLabel(str(slider.value()))

            slider.valueChanged.connect(lambda v, k=key: self._on_ui_param_changed(v, k))
            hbox.addWidget(slider)
            hbox.addWidget(label)

            self.param_widgets[key].update({'widget': slider, 'label': label})

        elif p_type == 'float':
            slider = QSlider(Qt.Horizontal)
            slider.setRange(int(info['min'] * 100), int(info['max'] * 100))
            slider.setValue(int(current_val * 100))
            label = QLabel(f"{current_val:.2f}")

            slider.valueChanged.connect(lambda v, k=key: self._on_ui_param_changed(v / 100.0, k))
            hbox.addWidget(slider)
            hbox.addWidget(label)

            self.param_widgets[key].update({'widget': slider, 'label': label})

            # ДОБАВЛЯЕМ КНОПКУ АНИМАЦИИ
            if filter_obj.can_be_animated(key):
                # Кнопка-ромбик
                btn_anim = QPushButton("◆")  # Можно использовать иконку или символ
                btn_anim.setCheckable(True)
                btn_anim.setFixedSize(24, 24)

                # Устанавливаем текущее состояние
                is_anim = filter_obj.is_animated(key)
                btn_anim.setChecked(is_anim)
                self._style_anim_button(btn_anim, is_anim)

                # Обработка нажатия
                btn_anim.toggled.connect(lambda checked, k=key: self._on_toggle_animation(k, checked))

                hbox.addWidget(btn_anim)
                self.param_widgets[key].update({'anim_btn': btn_anim})

        elif p_type == 'bool':
            checkbox = QCheckBox()
            checkbox.setChecked(bool(current_val))
            checkbox.toggled.connect(lambda v, k=key: self._on_ui_param_changed(v, k))
            hbox.addWidget(checkbox)

            self.param_widgets[key].update({'widget': checkbox, 'label': None})

        elif p_type == 'int_spin':
            spin = QSpinBox()
            spin.setRange(info.get('min', 0), info.get('max', 10000))
            spin.setValue(int(current_val))
            # Убираем кнопки-стрелочки, если нужно компактнее: spin.setButtonSymbols(QAbstractSpinBox.NoButtons)

            spin.valueChanged.connect(lambda v, k=key: self._on_ui_param_changed(v, k))
            hbox.addWidget(spin)

            self.param_widgets[key].update({'widget': spin, 'label': None})

        elif p_type == 'list':
            combo = QComboBox()
            items = info.get('values', [])
            combo.addItems([str(i) for i in items])

            # Устанавливаем текущее значение
            idx = combo.findText(str(current_val))
            if idx >= 0:
                combo.setCurrentIndex(idx)

            combo.currentTextChanged.connect(lambda v, k=key: self._on_ui_param_changed(v, k))
            hbox.addWidget(combo)

            self.param_widgets[key].update({'widget': combo, 'label': None})

        elif p_type == 'in_out':
            # Создаем кнопки управления диапазоном
            btn_in = QPushButton("[ In")
            btn_in.clicked.connect(self._on_mark_in_pressed)

            btn_out = QPushButton("Out ]")
            btn_out.clicked.connect(self._on_mark_out_pressed)

            btn_clear = QPushButton("Reset")
            btn_clear.clicked.connect(self._on_clear_pressed)

            # Стилизуем кнопки для компактности
            for btn in [btn_in, btn_out, btn_clear]:
                btn.setFixedWidth(60)
                hbox.addWidget(btn)

            # Лейбл, который будет обновляться методом _update_in_out_label
            label = QLabel("---")
            label.setStyleSheet("font-weight: bold; color: #2ecc71; margin-left: 8px;")

            # Подключаем сигналы к твоим методам

            hbox.addWidget(label)
            hbox.addStretch()

            # Регистрируем виджеты
            self.param_widgets[key].update({
                'widget': btn_in,
                'label': label
            })

            # Сразу инициализируем текст лейбла текущими значениями
            self._update_in_out_label()

        self.params_layout.addLayout(hbox)

    def _on_ui_param_changed(self, value, key):
        if not self._current_filter_obj: return

        self._current_filter_obj.set_param(key, value)
        data = self.param_widgets.get(key)

        if data and data['label']:
            if data['type'] == 'float':
                data['label'].setText(f"{value:.2f}")
            else:
                data['label'].setText(str(value))

        self.project.save_project()
        self.controller.refresh_current_frame()

    def _update_ui_from_params(self):
        if not self._current_filter_obj: return

        for key, data in self.param_widgets.items():
            widget = data['widget']
            label = data['label']
            p_type = data['type']
            val = self._current_filter_obj.get_param(key)

            widget.blockSignals(True)

            if p_type == 'int':
                widget.setValue(int(val))
                if label: label.setText(str(int(val)))

            elif p_type == 'float':
                widget.setValue(int(val * 100))
                if label: label.setText(f"{val:.2f}")

            elif p_type == 'bool':
                widget.setChecked(bool(val))

            elif p_type == 'int_spin':
                widget.setValue(int(val))

            elif p_type == 'list':
                idx = widget.findText(str(val))
                if idx >= 0:
                    widget.setCurrentIndex(idx)

            widget.blockSignals(False)

    def _on_mark_in_pressed(self):
        if not self._current_filter_obj: return
        filter = self._current_filter_obj

        curr = self.controller.model.current_idx
        old_out = filter.get_param("act_out",-1)

        filter.set_param("act_in", curr)
        # Если диапазон не был задан (-1), ставим конец в конец видео
        if old_out <= curr:
            filter.set_param("act_out", self.controller.model.get_max_index())

        self._update_in_out_label()  # Обновит текст типа "120 - 500"
        self.project.save_project()
        self.controller.refresh_current_frame()

    def _on_mark_out_pressed(self):
        if not self._current_filter_obj: return
        filter = self._current_filter_obj
        curr = self.controller.model.current_idx
        old_in = filter.get_param("act_in",-1)

        filter.set_param("act_out", curr)
        # Если начало не было задано, ставим его в 0 (или начало видео)
        if old_in < 0 or old_in >= curr:
            filter.set_param("act_in", 0)

        self._update_in_out_label()  # Обновит текст типа "120 - 500"
        self.project.save_project()
        self.controller.refresh_current_frame()

    def _on_clear_pressed(self):
        if not self._current_filter_obj: return
        filter = self._current_filter_obj

        filter.set_param("act_in", -1)
        filter.set_param("act_out", -1)
        self._update_in_out_label()  # Обновит текст типа "120 - 500"
        self.project.save_project()
        self.controller.refresh_current_frame()

    def _update_in_out_label(self):
        if not self._current_filter_obj: return
        filter = self._current_filter_obj

        data = self.param_widgets.get("act_in")

        if data and data['label']:
            act_in = filter.get_param("act_in", -1)
            act_out = filter.get_param("act_out", -1)
            if act_in >= 0:
                data['label'].setText(f"{act_in}-{act_out}")
            else:
                data['label'].setText("---")

    def _style_anim_button(self, btn, is_active):
        """Подсветка кнопки: синяя, если анимировано"""
        if is_active:
            btn.setStyleSheet("background-color: #3498db; color: white; border-radius: 3px; font-weight: bold;")
        else:
            btn.setStyleSheet("background-color: #ecf0f1; color: #7f8c8d; border-radius: 3px;")

    def _on_toggle_animation(self, key, is_set):
        if not self._current_filter_obj:
            return

            # Если пользователь хочет выключить анимацию — спрашиваем
        if not is_set:
            confirmed = self._ask_confirm(
                "Удаление анимации",
                f"Вы уверены, что хотите удалить все ключевые кадры для '{key}'?\n"
                "Параметр станет статичным."
            )
            if not confirmed:
                # Возвращаем кнопку в активное состояние, если нажали "No"
                btn = self.param_widgets[key].get('anim_btn')
                if btn:
                    btn.blockSignals(True)
                    btn.setChecked(True)
                    btn.blockSignals(False)
                return

            # Вызываем метод в фильтре
        self._current_filter_obj.set_animation(key, is_set)

        # Обновляем стиль кнопки
        if key in self.param_widgets:
            btn = self.param_widgets[key].get('anim_btn')
            if btn:
                self._style_anim_button(btn, is_set)

        self.project.save_project()
        self.controller.refresh_current_frame()


    def _show_add_menu(self):
        menu = QMenu(self)
        # Получаем названия всех доступных типов фильтров из регистра модели
        available_filters = self.project.filter_registry.keys()

        for name in available_filters:
            action = menu.addAction(name)
            # Передаем имя фильтра в метод добавления
            action.triggered.connect(lambda chk=False, n=name: self._add_filter_to_project(n))

        # Показываем меню под кнопкой "+"
        menu.exec(self.btn_add.mapToGlobal(self.btn_add.rect().bottomLeft()))

    def _add_filter_to_project(self, filter_name):
        self.project.add_filter(filter_name)
        self.refresh_list()
        # Выделяем последний добавленный
        self.list_widget.setCurrentRow(len(self.project.filters) - 1)

    def _delete_filter(self):
        row = self.list_widget.currentRow()
        if row < 0:
            return

        filter_obj = self.project.filters[row]
        filter_id = filter_obj.get_id()

        # Создаем диалог подтверждения
        msg_box = QMessageBox(self)
        msg_box.setIcon(QMessageBox.Question)
        msg_box.setWindowTitle("Подтверждение удаления")
        msg_box.setText(f"Вы уверены, что хотите удалить фильтр '{filter_id}'?")
        msg_box.setInformativeText("Все настройки этого фильтра будут потеряны.")

        # Добавляем стандартные кнопки на русском (или системные)
        btn_yes = msg_box.addButton("Удалить", QMessageBox.AcceptRole)
        btn_no = msg_box.addButton("Отмена", QMessageBox.RejectRole)

        msg_box.setDefaultButton(btn_no)
        msg_box.exec()

        # Проверяем, на какую кнопку нажал пользователь
        if msg_box.clickedButton() == btn_yes:
            # Удаляем из списка в модели
            self.project.filters.pop(row)
            self.project.save_project()

            self.refresh_list()

            # Очищаем панель параметров, так как фильтра больше нет
            self._on_filter_selected(-1)

            # Обновляем кадр
            # self.controller.refresh_current_frame()


    def _move_filter(self, direction):
        """direction: -1 (вверх), 1 (вниз)"""
        row = self.list_widget.currentRow()
        if row < 0:
            return

        # Просим модель поменять элементы местами
        if self.project.move_filter(row, direction):
            # Обновляем UI
            self.refresh_list()
            # Возвращаем выделение на новый индекс
            new_row = row + direction
            self.list_widget.setCurrentRow(new_row)
            # Перерисовываем видео (порядок фильтров изменился!)
            self.controller.refresh_current_frame()

    def _on_item_changed(self, item):
        index = self.list_widget.row(item)
        if index >= 0 and index < len(self.project.filters):
            is_checked = item.checkState() == Qt.Checked
            filter_obj = self.project.filters[index]

            # Если состояние реально изменилось
            if filter_obj.enabled != is_checked:
                filter_obj.enabled = is_checked
                self.project.save_project()
                self.controller.refresh_current_frame()

    def _ask_confirm(self, title, text):
        """Универсальное окно подтверждения"""
        msg = QMessageBox(self)
        msg.setIcon(QMessageBox.Question)
        msg.setWindowTitle(title)
        msg.setText(text)
        msg.setStandardButtons(QMessageBox.Yes | QMessageBox.No)
        msg.setDefaultButton(QMessageBox.No)  # Чтобы случайно не нажать Enter

        return msg.exec() == QMessageBox.Yes