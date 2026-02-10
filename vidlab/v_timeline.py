import cv2
from PySide6.QtGui import QPainter, QColor, QPen, Qt
from PySide6.QtWidgets import QWidget, QSizePolicy
from PySide6.QtCore import Signal, QPoint

from .c_video import VideoController


class TimelineWidget(QWidget):
    def __init__(self, controller):
        super().__init__()
        self.controller = controller
        self.setMinimumHeight(40)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.setMouseTracking(True)
        self.is_dragging = False

    def _get_active_range(self):
        """Возвращает границы, которые сейчас отображаются на таймлайне"""
        if self.controller.cropped_mode:
            # В режиме обрезки - только рабочий участок
            return self.controller.get_in_index(), self.controller.get_out_index()
        else:
            # В обычном режиме - всё видео целиком
            m = self.controller.model
            return m.get_min_index(), m.get_max_index()

    def _frame_to_x(self, frame):
        start, end = self._get_active_range()
        total = end - start
        if total <= 0: return 0
        # Считаем позицию относительно начала активного участка
        return ((frame - start) / total) * self.width()

    def _x_to_frame(self, x):
        start, end = self._get_active_range()
        total = end - start
        frame = start + (x / self.width()) * total
        return int(max(start, min(end, frame)))

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)

        rect = self.rect()
        mid_y = rect.height() // 2  # Центральная линия

        m = self.controller.model
        if m.get_max_index() <= 0: return
        start_f, end_f = self._get_active_range()

        # 1. Фоновая горизонтальная линия (ось времени)
        painter.setPen(QPen(QColor(80, 80, 80), 1))
        painter.drawLine(0, mid_y, rect.width(), mid_y)

        # 2. ВЫШЕ ЛИНИИ: Данные фильтра
        self._draw_filter_data_top(painter, rect, mid_y, start_f, end_f)

        # 3. НИЖЕ ЛИНИИ: In/Out и пользовательские метки
        if not self.controller.cropped_mode:
            self._draw_navigation_bottom(painter, rect, mid_y, start_f, end_f)
            self._draw_user_marks_bottom(painter, rect, mid_y, start_f, end_f)

        # 4. Плейхед (Треугольник ПОД линией)
        self._draw_playhead_bottom(painter, rect, mid_y, start_f, end_f)

    # --- Подметоды ---

    def _draw_filter_data_top(self, painter, rect, mid_y, start_f, end_f):
        data = self.controller.get_active_filter_timeline_data()
        total_visible = end_f - start_f

        # Рисуем области анализа (Ranges) сверху
        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor(0, 255, 0, 60))
        for s, e in data.get("ranges", []):
            if e < start_f or s > end_f: continue
            x1 = self._frame_to_x(max(s, start_f))
            x2 = self._frame_to_x(min(e, end_f))
            # Рисуем от верха до середины
            painter.drawRect(int(x1), 5, int(x2 - x1), mid_y - 5)

        # Рисуем метки (Marks) сверху - высокие оранжевые линии
        painter.setPen(QPen(QColor("orange"), 2))
        for frame in data.get("marks", []):
            if start_f <= frame <= end_f:
                x = self._frame_to_x(frame)
                painter.drawLine(int(x), 10, int(x), mid_y)

    def _draw_navigation_bottom(self, painter, rect, mid_y, start_f, end_f):
        in_f = self.controller.get_in_index()
        out_f = self.controller.get_out_index()

        x_in = self._frame_to_x(in_f)
        x_out = self._frame_to_x(out_f)

        # Рисуем In/Out как засечки снизу
        painter.setPen(QPen(QColor(255, 200, 0), 2))
        # In [
        painter.drawLine(int(x_in), mid_y, int(x_in), rect.height() - 10)
        painter.drawLine(int(x_in), rect.height() - 10, int(x_in) + 5, rect.height() - 10)
        # Out ]
        painter.drawLine(int(x_out), mid_y, int(x_out), rect.height() - 10)
        painter.drawLine(int(x_out), rect.height() - 10, int(x_out) - 5, rect.height() - 10)

    def _draw_user_marks_bottom(self, painter, rect, mid_y, start_f, end_f):
        # Получаем список меток из модели через контроллер
        marks = self.controller.project.get_user_marks()

        # Настройка пера: бирюзовый цвет, потолще
        painter.setPen(QPen(QColor(0, 170, 170), 2))

        for frame in marks:
            if start_f <= frame <= end_f:
                x = self._frame_to_x(frame)
                # Рисуем метку в нижней части (от оси до низа)
                painter.drawLine(int(x), mid_y, int(x), rect.height() - 5)

                # Маленький ромбик внизу для красоты
                # painter.setBrush(QColor(0, 60, 60))
                # painter.setPen(Qt.NoPen)
                # painter.drawEllipse(int(x) - 3, rect.height() - 8, 6, 6)

    def _draw_playhead_bottom(self, painter, rect, mid_y, start_f, end_f):
        curr_f = self.controller.model.get_current_index()
        if start_f <= curr_f <= end_f:
            x_curr = int(self._frame_to_x(curr_f))

            # Вертикальная игла через весь таймлайн (опционально, можно только снизу)
            painter.setPen(QPen(QColor(255, 0, 0, 100), 1))
            painter.drawLine(x_curr, 5, x_curr, rect.height() - 5)

            # Треугольник под линией
            painter.setBrush(QColor(255, 0, 0))
            painter.setPen(Qt.NoPen)
            points = [
                QPoint(x_curr, mid_y + 2),  # Вершина у линии
                QPoint(x_curr - 7, mid_y + 12),  # Левый угол
                QPoint(x_curr + 7, mid_y + 12)  # Правый угол
            ]
            painter.drawPolygon(points)

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            new_frame = self._x_to_frame(event.pos().x())

            # Если включен cropped_mode, ограничиваем выбор кадра внутри In/Out
            if self.controller.cropped_mode:
                in_f = self.controller.get_in_index()
                out_f = self.controller.get_out_index()
                new_frame = max(in_f, min(out_f, new_frame))

            self.controller.seek(new_frame)
            self.is_dragging = True
            self.update()

    def mouseMoveEvent(self, event):
        if self.is_dragging:
            # Логика та же, что и при клике
            new_frame = self._x_to_frame(event.pos().x())
            if self.controller.cropped_mode:
                in_f = self.controller.get_in_index()
                out_f = self.controller.get_out_index()
                new_frame = max(in_f, min(out_f, new_frame))
            self.controller.seek(new_frame)
            self.update()

    def mouseReleaseEvent(self, event):
        self.is_dragging = False