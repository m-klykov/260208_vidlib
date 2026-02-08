from PySide6.QtWidgets import QWidget, QListWidget, QListWidgetItem, QVBoxLayout, QPushButton, QHBoxLayout, \
    QInputDialog, QMessageBox, QSizePolicy
from PySide6.QtCore import Qt, Signal
from .c_video import VideoController
from .u_layouts import FlowLayout


class SceneListWidget(QWidget):
    def __init__(self, controller):
        super().__init__()
        self.controller : VideoController = controller

        self._init_ui()

        # Подписываемся на обновление данных из контроллера
        self.controller.scenes_updated.connect(self.refresh_list)

    def _init_ui(self):
        layout = QVBoxLayout(self)

        self.list_widget = QListWidget()
        layout.addWidget(self.list_widget)

        btns_container = QWidget()
        btns = FlowLayout(btns_container, margin=0, spacing=5)

        self.btn_add = QPushButton("Add")
        self.btn_add.setToolTip("Добавить метку на текущем кадре")

        self.btn_relocate = QPushButton("Move")  # Новая кнопка
        self.btn_relocate.setToolTip("Переместить выбранную метку на текущий кадр видео")

        self.btn_rename = QPushButton("Rename")
        self.btn_del = QPushButton("Delete")

        for b in [self.btn_add, self.btn_relocate, self.btn_rename, self.btn_del]:
            b.setFocusPolicy(Qt.NoFocus)
            b.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)
            btns.addWidget(b)

        layout.addWidget(btns_container)

        # Подсказка для кнопки "Подвинуть"


        self.btn_add.clicked.connect(self.controller.add_current_scene)
        self.btn_relocate.clicked.connect(self._on_relocate)
        self.btn_del.clicked.connect(self._on_delete)
        self.btn_rename.clicked.connect(self._on_rename)
        self.list_widget.itemDoubleClicked.connect(self._on_item_double_clicked)

    def refresh_list(self, scenes):
        self.list_widget.clear()
        for s in scenes:
            item = QListWidgetItem(f"[{s['frame']}] {s['title']}")
            item.setData(Qt.UserRole, s['frame'])
            self.list_widget.addItem(item)

    def _on_delete(self):
        item = self.list_widget.currentItem()
        if not item: return

        frame_idx = item.data(Qt.UserRole)

        # Переспрашиваем пользователя
        msg = QMessageBox()
        msg.setIcon(QMessageBox.Question)
        msg.setText(f"Удалить выбранную сцену?")
        msg.setInformativeText(f"Кадр: {frame_idx}\nЭто действие нельзя будет отменить.")
        msg.setWindowTitle("Подтверждение удаления")
        msg.setStandardButtons(QMessageBox.Yes | QMessageBox.No)
        msg.setDefaultButton(QMessageBox.No)

        if msg.exec() == QMessageBox.Yes:
            self.controller.delete_scene(frame_idx)

    def _on_relocate(self):
        item = self.list_widget.currentItem()
        if not item:
            return

        old_frame_idx = item.data(Qt.UserRole)
        new_frame_idx = self.controller.model.current_idx

        if old_frame_idx == new_frame_idx:
            return

        # Можно добавить легкое подтверждение или просто выполнить
        try:
            if self.controller.relocate_scene(old_frame_idx):
                # После перемещения выбираем обновленный элемент в списке
                self._select_by_frame(new_frame_idx)
        except ValueError as ve:
            self._show_error(str(ve))

    def _select_by_frame(self, frame_idx):
        """Вспомогательный метод для выделения нужной строки в списке"""
        for i in range(self.list_widget.count()):
            item = self.list_widget.item(i)
            if item.data(Qt.UserRole) == frame_idx:
                self.list_widget.setCurrentItem(item)
                break

    def _on_rename(self):
        item = self.list_widget.currentItem()
        if item:
            frame_idx = item.data(Qt.UserRole)
            old_title = item.text().split(']', 1)[-1].strip()

            new_title, ok = QInputDialog.getText(self, "Переименовать", "Заголовок:", text=old_title)
            if ok and new_title:
                self.controller.rename_scene(frame_idx, new_title)

    def _on_item_double_clicked(self, item):
        # По двойному клику просто переходим к кадру
        frame_idx = item.data(Qt.UserRole)
        self.controller.seek(frame_idx)

    def _show_error(self, message):
        """Универсальный метод для показа критических ошибок"""
        msg = QMessageBox(self)
        msg.setIcon(QMessageBox.Warning)
        msg.setWindowTitle("Внимание")
        msg.setText(message)
        msg.setStandardButtons(QMessageBox.Ok)
        msg.exec()