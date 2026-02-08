from PySide6.QtWidgets import QMainWindow, QDockWidget, QFileDialog
from PySide6.QtCore import Qt
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

        self._create_menu()

    def _create_menu(self):
        menu = self.menuBar()
        file_menu = menu.addMenu("Файл")
        open_act = file_menu.addAction("Открыть")
        open_act.triggered.connect(self._open_file_dialog)

        self.view_menu = menu.addMenu("Вид")

    def _open_file_dialog(self):
        path, _ = QFileDialog.getOpenFileName(self, "Выбор видео")
        if path:
            self.controller.load_video(path)

    # def add_analysis_panel(self):
    #     # Пример динамического добавления панели
    #     dock = QDockWidget("Анализ сцен", self)
    #     dock.setWidget(SceneListWidget())
    #     self.addDockWidget(Qt.RightDockWidgetArea, dock)
    #     self.view_menu.addAction(dock.toggleViewAction())