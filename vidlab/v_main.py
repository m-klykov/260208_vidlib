from PySide6.QtGui import QAction
from PySide6.QtWidgets import QMainWindow, QDockWidget, QFileDialog
from PySide6.QtCore import Qt

from .m_settings import SettingsModel
from .v_scene_list import SceneListWidget
from .v_video import VideoWidget
from .c_video import VideoController

WIN_W, WIN_H = 1100, 700 # размер главного окна

class MainView(QMainWindow):
    def __init__(self, controller):
        super().__init__()
        self.controller : VideoController = controller

        self.settings = SettingsModel.get_instance()

        self.setWindowTitle("Video Analyzer MVC")
        self.resize(WIN_W, WIN_H)

        # Главный виджет видео
        self.video_display = VideoWidget(self.controller)
        self.setCentralWidget(self.video_display)

        self.scene_dock = None

        self._create_menu()
        self._load_settings()

    def _create_menu(self):
        menu = self.menuBar()
        file_menu = menu.addMenu("Файл")
        open_act = file_menu.addAction("Открыть")
        open_act.triggered.connect(self._open_file_dialog)

        # Подменю для последних файлов
        self.recent_menu = file_menu.addMenu("Последние файлы")
        self._update_recent_files_menu()

        self.view_menu = menu.addMenu("Вид")
        scenes_act = self.view_menu.addAction("Показать список сцен")
        scenes_act.triggered.connect(self.show_scenes_panel)

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

    def _load_recent(self, path):
        if self.controller.load_video(path):
            self.settings.add_recent_file(path)
            self._update_recent_files_menu()

    def _open_file_dialog(self):
        path, _ = QFileDialog.getOpenFileName(self, "Выбор видео")
        if path:
            if self.controller.load_video(path):
                self.settings.add_recent_file(path)
                self._update_recent_files_menu()

    def show_scenes_panel(self):
        """Создает и показывает панель, если она еще не создана"""
        if self.scene_dock is None:
            # Создаем док-виджет
            self.scene_dock = QDockWidget("Ключевые кадры", self)
            # Разрешаем закрывать, перемещать и делать плавающим
            self.scene_dock.setAllowedAreas(Qt.LeftDockWidgetArea | Qt.RightDockWidgetArea)

            # Инициализируем сам виджет списка
            self.scene_widget = SceneListWidget(self.controller)
            self.scene_dock.setWidget(self.scene_widget)

            # Добавляем в основное окно (справа)
            self.addDockWidget(Qt.RightDockWidgetArea, self.scene_dock)

        # Делаем панель видимой (на случай если ее закрыли крестиком)
        self.scene_dock.show()
        self.scene_dock.raise_()  # Выводим на передний план

    # --- СОХРАНЕНИЕ СОСТОЯНИЯ ---

    def _load_settings(self):
        geo, state = self.settings.load_geometry()
        if geo: self.restoreGeometry(geo)
        if state: self.restoreState(state)

    def closeEvent(self, event):
        # Сохраняем размеры окна, положение Dock-панелей и их видимость
        self.settings.save_geometry(self.saveGeometry(), self.saveState())
        super().closeEvent(event)