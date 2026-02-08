from PySide6.QtWidgets import QWidget, QListWidget, QListWidgetItem, QVBoxLayout, QPushButton, QHBoxLayout, \
    QInputDialog, QMessageBox, QSizePolicy, QMenu, QAbstractItemView, QStyledItemDelegate, QLineEdit
from PySide6.QtCore import Qt, Signal
from .c_video import VideoController
from .u_layouts import FlowLayout

ROLE_FRAME_IDX = Qt.ItemDataRole.UserRole
ROLE_CLEAN_TITLE = Qt.ItemDataRole.UserRole + 1
ROLE_TYPE = Qt.ItemDataRole.UserRole + 2

class SceneItemDelegate(QStyledItemDelegate):
    def __init__(self, controller, parent=None):
        super().__init__(parent)
        self.controller = controller

    def createEditor(self, parent, option, index):
        # Проверяем тип метки перед созданием редактора
        mark_type = index.data(ROLE_TYPE)
        if mark_type in ["start", "end"]:
            return None  # Редактор не откроется
        return super().createEditor(parent, option, index)

    def displayText(self, value, locale):
        # value — это то, что лежит в DisplayRole (наше чистое имя)
        # Мы ищем, к какому кадру относится этот элемент через данные айтема
        # Но проще всего: если мы в refresh_list положим в DisplayRole чистое имя,
        # здесь мы его украсим таймкодом.
        return value

        # Чтобы разделить текст при чтении и правке, переопределим создание редактора

    def setEditorData(self, editor, index):
        # Когда открывается поле ввода (QLineEdit), берем данные из EditRole
        text = index.data(ROLE_CLEAN_TITLE)
        print(f"edited text: {text}")
        editor.setText(text)

    def setModelData(self, editor, model, index):
        # Когда пользователь нажал Enter, сохраняем введенное в EditRole
        model.setData(index, editor.text(), ROLE_CLEAN_TITLE)


class SceneListWidget(QWidget):
    def __init__(self, controller):
        super().__init__()
        self.controller : VideoController = controller

        self._init_ui()

        # Подписываемся на обновление данных из контроллера
        self.controller.scenes_updated.connect(self.refresh_list)

        self.controller.cropped_mode_changed.connect(self._on_mode_changed)

    def _init_ui(self):
        layout = QVBoxLayout(self)

        self.list_widget = QListWidget()
        self.delegate = SceneItemDelegate(self.controller, self)
        self.list_widget.setItemDelegate(self.delegate)
        print(f"set delegate")


        layout.addWidget(self.list_widget)

        # или когда элемент выбран и на него нажали еще раз (EditKeyPressed | SelectedClicked)
        self.list_widget.setEditTriggers(
            QAbstractItemView.EditKeyPressed |
            QAbstractItemView.SelectedClicked
        )

        # Подключаем сигнал изменения данных (текста) в списке
        self.list_widget.itemChanged.connect(self._on_item_changed)

        # Разрешаем кастомное контекстное меню для списка
        self.list_widget.setContextMenuPolicy(Qt.CustomContextMenu)
        self.list_widget.customContextMenuRequested.connect(self._show_context_menu)

        btns_container = QWidget()
        btns = FlowLayout(btns_container, margin=0, spacing=5)

        self.btn_add = QPushButton("Add")
        self.btn_add.setToolTip("Добавить метку на текущем кадре")

        self.btn_relocate = QPushButton("Move")  # Новая кнопка
        self.btn_relocate.setToolTip("Переместить выбранную метку на текущий кадр видео")

        self.btn_rename = QPushButton("Rename")
        self.btn_del = QPushButton("Delete")

        # Новые кнопки
        self.btn_set_in = QPushButton("[ Set In")
        self.btn_set_out = QPushButton("Set Out ]")

        # Стилизуем их чуть иначе, чтобы выделить
        self.btn_set_in.setStyleSheet("font-weight: bold; color: #2ecc71;")
        self.btn_set_out.setStyleSheet("font-weight: bold; color: #e74c3c;")

        for b in [self.btn_add, self.btn_relocate, self.btn_rename,
                  self.btn_del, self.btn_set_in, self.btn_set_out]:
            b.setFocusPolicy(Qt.NoFocus)
            b.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)
            btns.addWidget(b)

        layout.addWidget(btns_container)

        # Подсказка для кнопки "Подвинуть"


        self.btn_add.clicked.connect(self.controller.add_current_scene)
        self.btn_relocate.clicked.connect(self._on_relocate)
        self.btn_del.clicked.connect(self._on_delete)
        self.btn_rename.clicked.connect(self._on_rename)
        self.btn_set_in.clicked.connect(lambda: self._add_special("start"))
        self.btn_set_out.clicked.connect(lambda: self._add_special("end"))

        self.list_widget.itemDoubleClicked.connect(self._on_item_double_clicked)

    def refresh_list(self, scenes):
        self.list_widget.blockSignals(True)
        self.list_widget.clear()

        in_f = self.controller.get_in_index()
        out_f = self.controller.get_out_index()

        for s in scenes:
            frame_idx = s['frame']
            m_type = s.get('type', 'scene')

            # В режиме обрезки пропускаем системные метки и всё, что вне диапазона
            if self.controller.cropped_mode:
                if frame_idx <= in_f or frame_idx >= out_f:
                    continue

            # Получаем таймкод через модель видео (через контроллер)
            time_str = self.controller.model.get_time_string(frame_idx)

            # Текст для отображения: "00:00:05 [123] Название"
            prefix = "▶ " if m_type == "start" else "◀ " if m_type == "end" else ""
            display_text = f"{prefix}{time_str} [{frame_idx}] {s['title']}"

            item = QListWidgetItem()

            item.setData(ROLE_FRAME_IDX, frame_idx)

            # КЛЮЧЕВОЙ МОМЕНТ:
            # Для редактирования (EditRole) — ТОЛЬКО название
            # Храним ЧИСТОЕ имя там, где Qt его не достанет автоматикой
            item.setData(ROLE_CLEAN_TITLE, s['title'])
            item.setData(ROLE_TYPE, m_type)

            # Для отображения (DisplayRole) используем полную строку
            item.setData(Qt.ItemDataRole.DisplayRole, display_text)

            flags = Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable
            if m_type == "scene":
                flags |= Qt.ItemFlag.ItemIsEditable

            item.setFlags(flags)

            self.list_widget.addItem(item)

        self.list_widget.blockSignals(False)

    def _on_mode_changed(self, enabled):
        # Скрываем кнопки установки границ в режиме обрезки
        self.btn_set_in.setVisible(not enabled)
        self.btn_set_out.setVisible(not enabled)

    def _on_delete(self):
        item = self.list_widget.currentItem()
        if not item: return

        frame_idx = item.data(ROLE_FRAME_IDX)

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

        old_frame_idx = item.data(ROLE_FRAME_IDX)
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
            if item.data(ROLE_FRAME_IDX) == frame_idx:
                self.list_widget.setCurrentItem(item)
                break

    # def _on_rename(self):
    #     item = self.list_widget.currentItem()
    #     if item:
    #         frame_idx = item.data(Qt.UserRole)
    #         old_title = item.text().split(']', 1)[-1].strip()
    #
    #         new_title, ok = QInputDialog.getText(self, "Переименовать", "Заголовок:", text=old_title)
    #         if ok and new_title:
    #             self.controller.rename_scene(frame_idx, new_title)
    #             self._select_by_frame(frame_idx)

    def _on_rename(self):
        """Теперь вместо диалога просто переводим текущий элемент в режим правки"""
        item = self.list_widget.currentItem()
        if item:
            # Qt автоматически возьмет данные из EditRole
            self.list_widget.editItem(item)

    def _on_item_changed(self, item):
        """Срабатывает, когда пользователь закончил ввод текста в строке"""
        frame_idx = item.data(ROLE_FRAME_IDX)
        new_title = item.data(ROLE_CLEAN_TITLE)

        try:
            # 1. Отправляем новое имя в контроллер (сохраняем в JSON)
            self.controller.rename_scene(frame_idx, new_title)

        except Exception as e:
            self._show_error(f"Ошибка при сохранении имени: {e}")
            # В случае ошибки можно вызвать refresh_list, чтобы откатить текст к старому
            # self.refresh_list(self.controller.project.scenes)

    def _on_item_double_clicked(self, item):
        # По двойному клику просто переходим к кадру
        frame_idx = item.data(ROLE_FRAME_IDX)
        self.controller.seek(frame_idx)

    def _add_special(self, m_type):
        # В контроллер нужно добавить метод add_special_mark
        self.controller.add_special_mark(m_type)

    def _show_error(self, message):
        """Универсальный метод для показа критических ошибок"""
        msg = QMessageBox(self)
        msg.setIcon(QMessageBox.Warning)
        msg.setWindowTitle("Внимание")
        msg.setText(message)
        msg.setStandardButtons(QMessageBox.Ok)
        msg.exec()

    def _show_context_menu(self, position):
        """Создает и показывает меню при правом клике"""
        item = self.list_widget.itemAt(position)
        if not item:
            return

        # Создаем меню
        menu = QMenu(self)

        # Создаем действия (Actions)
        # Мы можем переиспользовать существующие методы логики
        act_jump = menu.addAction("Перейти к кадру")
        menu.addSeparator()
        act_rename = menu.addAction("Переименовать")
        act_relocate = menu.addAction("Подвинуть на текущий кадр")
        menu.addSeparator()
        act_del = menu.addAction("Удалить сцену")

        # Выполняем меню в позиции курсора и получаем выбранное действие
        action = menu.exec(self.list_widget.mapToGlobal(position))

        # Обработка выбора
        if action == act_jump:
            self._on_item_double_clicked(item)
        elif action == act_rename:
            self._on_rename()
        elif action == act_relocate:
            self._on_relocate()
        elif action == act_del:
            self._on_delete()

    def keyPressEvent(self, event):
        if event.key() == Qt.Key_Delete:
            self._on_delete()
        elif event.key() == Qt.Key_F2:
            self._on_rename()
        else:
            super().keyPressEvent(event)