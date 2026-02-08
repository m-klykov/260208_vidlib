from PySide6.QtWidgets import QWidget, QListWidget, QListWidgetItem, QVBoxLayout, QPushButton
from PySide6.QtCore import Qt, Signal
from .c_video import VideoController

class SceneListWidget(QWidget):
    def __init__(self, controller):
        super().__init__()
        self.controller : VideoController = controller
        layout = QVBoxLayout(self)

        self.list_widget = QListWidget()
        layout.addWidget(self.list_widget)

        self.btn_add = QPushButton("Добавить текущий кадр")
        self.btn_add.setFocusPolicy(Qt.NoFocus)
        layout.addWidget(self.btn_add)

        # Клик по элементу списка — переход к кадру
        self.list_widget.itemDoubleClicked.connect(self._jump_to_scene)
        self.btn_add.clicked.connect(self._add_scene)

    def _add_scene(self):
        idx = self.controller.model.get_current_index()
        info = self.controller.model.get_full_timestamp()
        item = QListWidgetItem(f"{info}")
        item.setData(Qt.UserRole, idx)  # Сохраняем номер кадра внутри элемента
        self.list_widget.addItem(item)

    def _jump_to_scene(self, item):
        frame_idx = item.data(Qt.UserRole)
        self.controller.seek(frame_idx)