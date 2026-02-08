from PySide6.QtWidgets import QMainWindow, QDockWidget, QFileDialog
from PySide6.QtCore import Qt

from .v_scene_list import SceneListWidget
from .v_video import VideoWidget
from .c_video import VideoController

WIN_W, WIN_H = 1100, 700 # размер главного окна

class MainView(QMainWindow):
    def __init__(self, controller):
        super().__init__()
        self.controller : VideoController = controller
        self.setWindowTitle("Video Analyzer MVC")
        self.resize(WIN_W, WIN_H)

        # Главный виджет видео
        self.video_display = VideoWidget(self.controller)
        self.setCentralWidget(self.video_display)

        self.scene_dock = None

        self._create_menu()

    def _create_menu(self):
        menu = self.menuBar()
        file_menu = menu.addMenu("Файл")
        open_act = file_menu.addAction("Открыть")
        open_act.triggered.connect(self._open_file_dialog)

        self.view_menu = menu.addMenu("Вид")
        scenes_act = self.view_menu.addAction("Показать список сцен")
        scenes_act.triggered.connect(self.show_scenes_panel)

    def _open_file_dialog(self):
        path, _ = QFileDialog.getOpenFileName(self, "Выбор видео")
        if path:
            self.controller.load_video(path)

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