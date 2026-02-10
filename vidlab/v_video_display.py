from PySide6.QtWidgets import QWidget
from PySide6.QtGui import QPainter, QPixmap
from PySide6.QtCore import Qt, QRect


class VideoDisplay(QWidget):
    def __init__(self, controller, parent=None):
        super().__init__(parent)
        self.controller = controller
        self.pixmap = None
        self.setMouseTracking(True)  # Важно для изменения курсора без нажатия
        # Черный фон по умолчанию
        self.setAttribute(Qt.WA_OpaquePaintEvent)

    def set_pixmap(self, pixmap):
        self.pixmap = pixmap
        self.update()  # Вызывает paintEvent

    def _get_target_rect(self):
        w_size = self.size()
        if self.pixmap is None:
            return QRect(0, 0, w_size.width(), w_size.height())
        pix_size = self.pixmap.size()
        scaled_size = pix_size.scaled(w_size, Qt.KeepAspectRatio)

        # Центрируем картинку
        x = (w_size.width() - scaled_size.width()) // 2
        y = (w_size.height() - scaled_size.height()) // 2
        return QRect(x, y, scaled_size.width(), scaled_size.height())

    def paintEvent(self, event):
        painter = QPainter(self)
        # Рисуем черный фон
        painter.fillRect(self.rect(), Qt.black)

        if not self.pixmap:
            painter.setPen(Qt.white)
            painter.drawText(self.rect(), Qt.AlignCenter, "Загрузите видео")
            return

        # 1. Вычисляем размеры для сохранения пропорций (Aspect Ratio)
        target_rect = self._get_target_rect()

        # 2. Рисуем само видео
        painter.drawPixmap(target_rect, self.pixmap)

        # 3. Рисуем оверлеи фильтров (передаем painter и область видео)
        self.controller.draw_filters_overlay(painter, target_rect)

    def mouseMoveEvent(self, event):
        target_rect = self._get_target_rect()
        # Контроллер спросит фильтр, какой курсор поставить
        cursor = self.controller.handle_mouse_move(event.pos(), target_rect)
        self.setCursor(cursor)
        self.update()

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            target_rect = self._get_target_rect()
            self.controller.handle_mouse_press(event.pos(), target_rect)

    def mouseReleaseEvent(self, event):
        self.controller.handle_mouse_release()