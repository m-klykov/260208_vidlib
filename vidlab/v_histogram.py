from PySide6.QtWidgets import QWidget
from PySide6.QtGui import QPainter, QColor, QPen
from PySide6.QtCore import Qt


class HistogramWidget(QWidget):
    def __init__(self, controller, parent=None):
        super().__init__(parent)
        self.controller = controller
        self.hist_data = None

        # Минимальный размер, чтобы гистограмма не схлопнулась
        self.setMinimumHeight(100)

        # Подписываемся на обновление кадра
        self.controller.frame_updated.connect(self.update_data)

    def update_data(self):
        # ГЛАВНАЯ ОПТИМИЗАЦИЯ: если виджет скрыт, не тратим ресурсы CPU/GPU
        if not self.isVisible():
            return

        self.hist_data = self.controller.model.get_histogram()
        print('has hist')
        self.update()  # Вызывает paintEvent

    def paintEvent(self, event):
        if self.hist_data is None:
            return

        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)

        painter.fillRect(self.rect(), QColor(30, 30, 30, 200))

        w = self.width()
        h = self.height()
        n = len(self.hist_data)
        bar_w = w / n

        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor(255, 255, 255, 150))

        for i, val in enumerate(self.hist_data):
            # Приводим к int, чтобы PySide не ругался на типы
            x = int(i * bar_w)
            bar_h = int(val * h)
            y = int(h - bar_h)
            width = int(bar_w + 1)

            painter.drawRect(x, y, width, bar_h)