from PySide6.QtCore import Qt, QPoint
import cv2
import numpy as np
from PySide6.QtGui import QPen, QColor

from .f_base import FilterBase


class FilterEllipse(FilterBase):
    def __init__(self, num, cache_dir, params=None):
        if not params:
            params = {
                "x_pos": 0.0,
                "y_pos": 0.0,
                "diameter": 0.2,
                "aspect": 0.0,
                "thickness": 5,
                "opacity": 0.6
            }
        super().__init__(num, cache_dir, params)
        self.name = "Ellipse"
        self._is_dragging = False

    def get_params_metadata(self):
        return {
            "act_in": {"type": "in_out", "default": -1},  # Наш триггер для UI
            "x_pos": {"type": "float", "min": -1.0, "max": 1.0, "default": 0.0},
            "y_pos": {"type": "float", "min": -1.0, "max": 1.0, "default": 0.0},
            "diameter": {"type": "float", "min": 0.01, "max": 1.0, "default": 0.2},
            "aspect": {"type": "float", "min": -1.0, "max": 1.0, "default": 0.0},
            "thickness": {"type": "int", "min": 1, "max": 50, "default": 5},
            "opacity": {"type": "float", "min": 0.0, "max": 1.0, "default": 0.6},
            "show_path": {"type": "bool", "default": True},
        }


    def _update_pos_from_mouse(self, pos, rect):
        """Математика перевода экранных координат в диапазон [-1, 1]"""
        # 1. Находим относительную позицию в прямоугольнике (0.0 до 1.0)
        rel_x = (pos.x() - rect.left()) / rect.width()
        rel_y = (pos.y() - rect.top()) / rect.height()

        # 2. Переводим в диапазон [-1, 1]
        val_x = clamp(rel_x * 2 - 1, -1.0, 1.0)
        val_y = clamp(rel_y * 2 - 1, -1.0, 1.0)

        self.set_param("x_pos", val_x)
        self.set_param("y_pos", val_y)

    # --- Отрисовка ---

    def _get_geometry(self, width, height):
        """
        Вычисляет физические координаты и размеры эллипса для заданного разрешения.
        Возвращает словарь: cx, cy, rx, ry
        """
        # Центр в пикселях
        cx = int((self.get_param("x_pos") + 1) / 2 * width)
        cy = int((self.get_param("y_pos") + 1) / 2 * height)

        # Базовый радиус (относительно ширины)
        base_r = (self.get_param("diameter") * width) / 2
        asp = self.get_param("aspect")

        # Радиусы по осям с учетом фактора сжатия
        rx = int(base_r * (1.0 + max(0, asp)))
        ry = int(base_r * (1.0 + max(0, -asp)))

        return {
            "cx": cx,
            "cy": cy,
            "rx": rx,
            "ry": ry
        }

    def process(self, frame, idx):
        h, w = frame.shape[:2]

        # Получаем геометрию
        geo = self._get_geometry(w, h)

        overlay = frame.copy()
        cv2.ellipse(
            overlay,
            (geo["cx"], geo["cy"]),
            (geo["rx"], geo["ry"]),
            0, 0, 360,
            (0, 0, 255),
            self.get_param("thickness"),
            cv2.LINE_AA
        )

        alpha = self.get_param("opacity")
        cv2.addWeighted(overlay, alpha, frame, 1 - alpha, 0, frame)
        return frame

    def render_overlay(self, painter, idx, viewport_rect):
        if not self.focused: return

        w, h = viewport_rect.width(), viewport_rect.height()
        sx, sy = viewport_rect.left(), viewport_rect.top()

        # 1. Получаем текущую геометрию для отрисовки текущего центра
        geo = self._get_geometry(w, h)
        curr_px = sx + geo["cx"]
        curr_py = sy + geo["cy"]

        # 2. Отрисовка траектории (если включена)
        if self.get_param("show_path", False):
            route_data = self.get_keyframes_data(["x_pos", "y_pos"])

            if len(route_data) >= 2:
                path_pen = QPen(QColor(255, 0, 0, 120), 2, Qt.DashLine)
                point_pen_normal = QPen(QColor(0, 255, 255), 5)
                point_pen_key = QPen(QColor(255, 255, 0), 8)  # Яркий желтый для ключа

                sorted_frames = sorted(route_data.keys())
                points = []

                # Собираем точки ключей
                for f_idx in sorted_frames:
                    data = route_data[f_idx]
                    px = int(sx + (data["x_pos"] + 1) / 2 * w)
                    py = int(sy + (data["y_pos"] + 1) / 2 * h)
                    points.append((px, py, f_idx))

                # Рисуем линии траектории
                painter.setPen(path_pen)
                for i in range(len(points) - 1):
                    painter.drawLine(points[i][0], points[i][1], points[i + 1][0], points[i + 1][1])

                # В цикле отрисовки точек ключей добавим условие:
                for px, py, f_idx in points:
                    is_current = (f_idx == self.current_frame_idx)
                    is_hovered = (f_idx == getattr(self, '_hovered_keyframe_idx', None))

                    if is_current:
                        # Текущий кадр (Желтый)
                        painter.setPen(QPen(QColor(255, 255, 0), 10))
                    elif is_hovered:
                        # Наведенная точка (Ярко-белый или Оранжевый с обводкой)
                        painter.setPen(QPen(QColor(255, 165, 0), 12))
                    else:
                        # Обычные ключи (Голубой)
                        painter.setPen(QPen(QColor(0, 255, 255), 6))

                    painter.drawPoint(px, py)

                    # Если точка под курсором, можно вывести номер кадра
                    if is_hovered:
                        painter.setPen(QColor(255, 255, 255))
                        painter.drawText(px + 12, py - 12, f"Key: {f_idx}")

        # 3. Рисуем "прицел" текущего положения (даже если эллипс выключен)
        # Это помогает понять, где находится центр прямо сейчас
        painter.setPen(QPen(QColor(255, 255, 255, 200), 1))

        # Рисуем маленькое перекрестие
        size = 10
        painter.drawLine(curr_px - size, curr_py, curr_px + size, curr_py)
        painter.drawLine(curr_px, curr_py - size, curr_px, curr_py + size)

    # --- Логика перетаскивания ---

    def _is_hovering_ellipse(self, pos, rect):
        """Проверка, находится ли курсор внутри эллипса"""
        if not rect.contains(pos): return False

        geo = self._get_geometry(rect.width(), rect.height())

        # Центр эллипса в координатах окна
        cx_global = rect.left() + geo["cx"]
        cy_global = rect.top() + geo["cy"]

        # Расстояние от мыши до центра
        dx = pos.x() - cx_global
        dy = pos.y() - cy_global

        # Уравнение эллипса (rx и ry берем из геометрии)
        # Защита от деления на ноль, если радиусы вдруг 0
        rx, ry = max(1, geo["rx"]), max(1, geo["ry"])
        return (dx ** 2) / (rx ** 2) + (dy ** 2) / (ry ** 2) <= 1

    def handle_mouse_press(self, pos, rect):
        if not rect.contains(pos): return

        w, h = rect.width(), rect.height()
        sx, sy = rect.left(), rect.top()

        # 1. Сначала проверяем нажатие на ключевые точки траектории (если путь включен)
        if self.get_param("show_path", False):
            route_data = self.get_keyframes_data(["x_pos", "y_pos"])
            for f_idx, data in route_data.items():
                px = sx + (data["x_pos"] + 1) / 2 * w
                py = sy + (data["y_pos"] + 1) / 2 * h

                # Если кликнули в радиусе 10 пикселей от ключа
                if (pos.x() - px) ** 2 + (pos.y() - py) ** 2 < 100:
                    self._is_dragging = True
                    self._dragging_keyframe_idx = f_idx  # Запоминаем, какой кадр правим
                    self._drag_offset_x = pos.x() - px
                    self._drag_offset_y = pos.y() - py
                    return

        # 2. Если в ключи не попали, проверяем нажатие на текущий эллипс (старая логика)
        if self._is_hovering_ellipse(pos, rect):
            self._is_dragging = True
            self._dragging_keyframe_idx = self.current_frame_idx  # Правим текущий кадр

            geo = self._get_geometry(w, h)
            self._drag_offset_x = pos.x() - (sx + geo["cx"])
            self._drag_offset_y = pos.y() - (sy + geo["cy"])

    def handle_mouse_move(self, pos, rect):
        if self._is_dragging:
            w, h = rect.width(), rect.height()
            sx, sy = rect.left(), rect.top()

            # Вычисляем новые координаты в формате [-1, 1]
            target_x = ((pos.x() - self._drag_offset_x - sx) / w) * 2 - 1
            target_y = ((pos.y() - self._drag_offset_y - sy) / h) * 2 - 1

            # Сохраняем оригинальный кадр
            original_frame = self.current_frame_idx

            # Переключаемся на кадр ключа, который тянем
            self.set_current_frame(self._dragging_keyframe_idx)

            # Записываем новые координаты (автоматически обновит ключ в словаре)
            self.set_param("x_pos", max(-1.0, min(1.0, target_x)))
            self.set_param("y_pos", max(-1.0, min(1.0, target_y)))

            # Возвращаемся на текущий кадр видео
            self.set_current_frame(original_frame)

            return Qt.ClosedHandCursor, True

        # 2. Проверка наведения на ключевые точки маршрута
        self._hovered_keyframe_idx = None
        if self.get_param("show_path", False):
            w, h = rect.width(), rect.height()
            sx, sy = rect.left(), rect.top()

            route_data = self.get_keyframes_data(["x_pos", "y_pos"])
            for f_idx, data in route_data.items():
                px = sx + (data["x_pos"] + 1) / 2 * w
                py = sy + (data["y_pos"] + 1) / 2 * h

                # Если курсор в радиусе 8-10 пикселей от точки
                if (pos.x() - px) ** 2 + (pos.y() - py) ** 2 < 100:
                    self._hovered_keyframe_idx = f_idx
                    # Меняем курсор на "указательный палец" или "перекрестие"
                    return Qt.PointingHandCursor, False

                    # 3. Проверка наведения на само тело эллипса
        if self._is_hovering_ellipse(pos, rect):
            return Qt.OpenHandCursor, False

        if rect.contains(pos):
            return Qt.CrossCursor, False

        return Qt.ArrowCursor, False

    def handle_mouse_release(self):
        self._is_dragging = False

    def get_timeline_data(self):
        # Получаем базовые данные (In/Out)
        data = super().get_timeline_data()

        # Добавляем все ключевые кадры как метки
        anim_keys = self.get_keyframe_indices()
        data["marks"].extend(anim_keys)

        return data


def clamp(n, minn, maxn):
    return max(min(maxn, n), minn)