from PySide6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QListWidget,
                               QListWidgetItem, QPushButton, QMenu, QCheckBox, QLabel, QScrollArea, QMessageBox,
                               QProgressBar)
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

        if info['type'] == 'int':
            from PySide6.QtWidgets import QSlider
            slider = QSlider(Qt.Horizontal)
            slider.setRange(info['min'], info['max'])
            slider.setValue(filter_obj.get_param(key, info['default']))

            value_label = QLabel(str(slider.value()))

            # Сохраняем ссылку на слайдер и лейбл
            self.param_widgets[key] = (slider, value_label)

            slider.valueChanged.connect(lambda v, k=key: self._on_ui_param_changed(v, k))
            hbox.addWidget(slider)
            hbox.addWidget(value_label)

        self.params_layout.addLayout(hbox)

    def _on_ui_param_changed(self, value, key):
        """Когда пользователь крутит ползунок"""
        if self._current_filter_obj:
            self._current_filter_obj.set_param(key, value)
            # real_value =  self._current_filter_obj.get_param(key)
            # Обновляем текст рядом с ползунком
            if key in self.param_widgets:
                slider, label = self.param_widgets[key]
                label.setText(str(value))

            self.project.save_project()
            self.controller.refresh_current_frame()

    def _update_ui_from_params(self):
        """Когда параметры изменились в фильтре (от мышки)"""
        if not self._current_filter_obj: return

        # Блокируем сигналы слайдеров, чтобы не было зацикливания
        # (UI -> Filter -> UI)
        for key, (slider, label) in self.param_widgets.items():
            new_val = int(self._current_filter_obj.get_param(key))
            slider.blockSignals(True)
            slider.setValue(new_val)
            label.setText(str(new_val))
            slider.blockSignals(False)

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