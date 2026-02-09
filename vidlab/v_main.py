import os

from PySide6.QtGui import QAction, QShortcut, QKeySequence
from PySide6.QtWidgets import QMainWindow, QDockWidget, QFileDialog, QLabel, QToolBar
from PySide6.QtCore import Qt, QTimer

from .m_config import APP_NAME
from .m_settings import SettingsModel
from .v_filter_man import FilterManagerWidget
from .v_scene_list import SceneListWidget
from .v_video import VideoWidget
from .c_video import VideoController
from .m_config import WIN_W, WIN_H, APP_NAME, APP_VER
from .v_histogram import HistogramWidget  # Импорт внутри, если нужно


class MainView(QMainWindow):
    def __init__(self, controller):
        super().__init__()

        self.resize(WIN_W, WIN_H)

        self.controller : VideoController = controller

        self.settings = SettingsModel.get_instance()

        # Устанавливаем начальный заголовок
        self.update_title()

        self._init_ui()
        self._create_menu()
        self._create_toolbar()

        # Создаем горячую клавишу Ctrl+L
        # self.shortcut_last_file = QShortcut(QKeySequence("Ctrl+L"), self)
        # self.shortcut_last_file.activated.connect(self._load_most_recent_file)

        # Подключаем сигналы контроллера для обновления метаданных
        # Предположим, у контроллера будет сигнал video_loaded
        self.controller.video_loaded.connect(self.on_video_loaded)

        self._load_settings()

    def _init_ui(self):
        # --- Видео виджет ---
        self.video_display = VideoWidget(self.controller)
        self.setCentralWidget(self.video_display)

        # Панель сцен
        self.scene_dock = QDockWidget("Ключевые кадры", self)
        self.scene_dock.setObjectName("SceneListDock")
        self.scene_dock.setAllowedAreas(Qt.LeftDockWidgetArea | Qt.RightDockWidgetArea)
        self.scene_widget = SceneListWidget(self.controller)
        self.scene_dock.setWidget(self.scene_widget)
        self.addDockWidget(Qt.RightDockWidgetArea, self.scene_dock)
        self.scene_dock.hide()

        # В _init_ui основного окна:
        self.filter_dock = QDockWidget("✨ Фильтры и Эффекты", self)
        self.filter_dock.setObjectName("FilterDock")
        self.filter_manager_widget = FilterManagerWidget(self.controller)
        self.filter_dock.setWidget(self.filter_manager_widget)
        self.addDockWidget(Qt.LeftDockWidgetArea, self.filter_dock)  # Слева, например
        self.filter_dock.hide()

        # --- НОВОЕ: Док с гистограммой ---
        self.hist_dock = QDockWidget("📊 Гистограмма", self)
        self.hist_dock.setObjectName("HistogramDock")
        self.hist_dock.setAllowedAreas(Qt.AllDockWidgetAreas)

        # Создаем наш виджет гистограммы

        self.hist_widget = HistogramWidget(self.controller)
        self.hist_dock.setWidget(self.hist_widget)

        # Размещаем её справа. Если scene_dock тоже виден, они поделят место
        self.addDockWidget(Qt.RightDockWidgetArea, self.hist_dock)
        self.hist_dock.hide()

        # --- СТРОКА СОСТОЯНИЯ ---
        self.status_bar = self.statusBar()

        self.info_label = QLabel(" Видео не загружено")
        self.status_bar.addWidget(self.info_label)

        # spacer = QLabel("  |  ")
        # self.status_bar.addWidget(spacer)

        self.msg_label = QLabel("")

        # '1' заставляет этот лейбл растягиваться
        self.status_bar.addWidget(self.msg_label, 1)

    def update_title(self, file_path=None):
        """Обновляет заголовок окна"""
        if file_path:
            file_name = os.path.basename(file_path)
            self.setWindowTitle(f"{file_name} — {APP_NAME} v{APP_VER}")
        else:
            self.setWindowTitle(f"{APP_NAME} v{APP_VER}")

    def _create_menu(self):
        menu = self.menuBar()
        file_menu = menu.addMenu("Файл")
        open_act = file_menu.addAction("📂 Открыть")
        open_act.setShortcut("Ctrl+O")
        open_act.triggered.connect(self._open_file_dialog)

        last_act = file_menu.addAction("🕒 Открыть последний")
        last_act.setShortcut("Ctrl+L")
        last_act.triggered.connect(self._load_most_recent_file)

        # Подменю для последних файлов
        self.recent_menu = file_menu.addMenu("Последние файлы")
        self._update_recent_files_menu()

        self.view_menu = menu.addMenu("Вид")

        crop_act = self.view_menu.addAction("✂️ Режим обрезки (In/Out)")
        crop_act.setCheckable(True)
        crop_act.setShortcut("Ctrl+Shift+C")
        crop_act.triggered.connect(self.controller.set_cropped_mode)

        toggle_scenes_act = self.scene_dock.toggleViewAction()
        toggle_scenes_act.setText("Список сцен")
        self.view_menu.addAction(toggle_scenes_act)

        toggle_filter_man = self.filter_dock.toggleViewAction()
        toggle_filter_man.setText("✨ Фильтры")
        self.view_menu.addAction(toggle_filter_man)

    def _update_recent_files_menu(self):
        self.recent_menu.clear()
        files = self.settings.get_recent_files()

        if not files:
            self.recent_menu.addAction("Список пуст").setEnabled(False)

        for f_path in files:
            action = QAction(f_path, self)
            # Используем лямбду для передачи пути в контроллер
            action.triggered.connect(lambda chk=False, p=f_path: self._load_recent(p))
            self.recent_menu.addAction(action)

    def _create_toolbar(self):
        self.toolbar = QToolBar("Main Toolbar")
        self.toolbar.setMovable(False)  # Чтобы случайно не оторвали
        self.addToolBar(self.toolbar)

        # 1. Кнопка "Открыть последний проект"
        self.act_load_last = QAction("🕒 Last Video", self)
        self.act_load_last.setToolTip("Загрузить последний открытый файл (Ctrl+L)")
        self.act_load_last.triggered.connect(self._load_most_recent_file)
        self.toolbar.addAction(self.act_load_last)

        self.toolbar.addSeparator()

        # Кнопка Скриншота
        # Если есть иконка: QIcon("path/to/icon.png")
        self.act_screenshot = QAction("📸 Screenshot", self)
        self.act_screenshot.setShortcut("Ctrl+S")
        # self.act_screenshot.setStatusTip("Сохранить текущий кадр в папку с видео")
        self.act_screenshot.triggered.connect(self._make_screenshot)
        self.toolbar.addAction(self.act_screenshot)
        self.toolbar.addSeparator()

        # 3. Кнопка "Открыть папку"
        self.act_open_folder = QAction("📂 Open Folder", self)
        self.act_open_folder.setToolTip("Открыть папку с видео и скриншотами")
        self.act_open_folder.triggered.connect(self.controller.open_video_folder)
        self.toolbar.addAction(self.act_open_folder)

        self.toolbar.addSeparator()

        self.act_hist = QAction("📊 Hist", self)
        self.act_hist.setCheckable(True)
        self.act_hist.triggered.connect(self._toggle_histogram)
        self.toolbar.addAction(self.act_hist)

    def _make_screenshot(self):
        res = self.controller.make_screenshot()
        # print("Скриншот")
        if res:
            self.show_status_msg(f'Screenshot in "{res}"')
            print(f'Screenshot in "{res}"')


    def on_video_loaded(self):
        """Вызывается, когда контроллер успешно загрузил видео"""
        model = self.controller.model
        path = model.file_path

        # 1. Обновляем заголовок
        self.update_title(path)

        # обновляем меню
        self.settings.add_recent_file(path)
        self._update_recent_files_menu()

        # 2. Обновляем строку состояния
        info = f"Разрешение: {model.width}x{model.height} | FPS: {model.fps:.2f}"
        self.info_label.setText(info)

        self.show_status_msg("Видео успешно загружено")

    def show_status_msg(self, text, timeout=3000):
        """Выводит временное сообщение в строку состояния"""
        self.msg_label.setText("| "+text)
        # Очищаем через N миллисекунд
        if timeout > 0:
            QTimer.singleShot(timeout, lambda: self.msg_label.setText(""))

    def _load_recent(self, path):
        self.controller.load_video(path)

    def _load_most_recent_file(self):
        """Загружает самый первый файл из списка последних"""
        recent_files = self.settings.get_recent_files()

        if recent_files and len(recent_files) > 0:
            last_path = recent_files[0]
            # Вызываем метод загрузки (контроллер сам уведомит всех через сигнал)
            self._load_recent(last_path)
            self.show_status_msg(f"Загружен последний файл: {os.path.basename(last_path)}")
        else:
            self.show_status_msg("Список последних файлов пуст")
            self._show_error("Нет недавно открытых файлов для быстрой загрузки.")

    def _open_file_dialog(self):
        path, _ = QFileDialog.getOpenFileName(self, "Выбор видео")
        if path:
            self.controller.load_video(path)

    # --- СОХРАНЕНИЕ СОСТОЯНИЯ ---

    def _load_settings(self):
        geo, state = self.settings.load_geometry()
        if geo: self.restoreGeometry(geo)
        if state: self.restoreState(state)

    def closeEvent(self, event):
        # Сохраняем размеры окна, положение Dock-панелей и их видимость
        self.settings.save_geometry(self.saveGeometry(), self.saveState())
        super().closeEvent(event)

    def _toggle_histogram(self, checked):
        if checked:
            self.hist_dock.show()
            # Сразу обновляем данные из self.last_frame
            self.hist_widget.update_data()
        else:
            self.hist_dock.hide()