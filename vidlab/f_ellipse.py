import os
import random
from PySide6.QtCore import Qt, QPoint
import cv2
import numpy as np
from PySide6.QtGui import QPen, QColor

from .f_base import FilterBase
from .m_track_man import TrackerManager
from .m_track_storage import TrackerStorage


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

        self.storage = TrackerStorage(os.path.join(cache_dir, f"{self.get_id()}.dat"))
        self.tracker_mgr = TrackerManager(self.storage, self._set_manual_key_callback)


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

    # Калбек для менеджера
    def _set_manual_key_callback(self, frame_idx, x, y):
        old_idx = self.current_frame_idx
        self.set_current_frame(frame_idx)
        self.set_animation("x_pos",True)
        self.set_animation("y_pos",True)
        self.set_param("x_pos", x)
        self.set_param("y_pos", y)
        self.set_current_frame(old_idx)
        self.save_project()

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
        # 1. Берем базу из интерполяции JSON
        base_x = self.get_param("x_pos")
        base_y = self.get_param("y_pos")

        # 2. Добавляем дельту из менеджера
        dx, dy = self.tracker_mgr.get_offset_for_frame(
            self.current_frame_idx, (base_x, base_y))

        cx = int((base_x + dx + 1) / 2 * width)
        cy = int((base_y + dy + 1) / 2 * height)

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
                    dx, dy = self.tracker_mgr.get_offset_for_frame(f_idx, (0, 0))
                    data = route_data[f_idx]
                    px = int(sx + (data["x_pos"] + dx + 1) / 2 * w)
                    py = int(sy + (data["y_pos"] + dy + 1) / 2 * h)
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

    def handle_mouse_press(self, pos, rect, event):
        if not rect.contains(pos): return

        button = event.button()


        w, h = rect.width(), rect.height()
        sx, sy = rect.left(), rect.top()

        # 1. Сначала проверяем нажатие на ключевые точки траектории (если путь включен)
        if self.get_param("show_path", False):

            # Если нажата ПРАВАЯ кнопка и мы наведены на точку
            if button == Qt.RightButton:
                hovered_idx = getattr(self, '_hovered_keyframe_idx', None)
                if hovered_idx is not None:
                    # Удаляем ключи для позиции на этом кадре
                    self.remove_keyframe(hovered_idx, ["x_pos", "y_pos"])
                    self._hovered_keyframe_idx = None  # Сбрасываем наведение

                    # Сообщаем системе, что нужно сохранить проект и перерисовать
                    return True  # Сигнал "параметры изменились"
                return False

            route_data = self.get_keyframes_data(["x_pos", "y_pos"])
            for f_idx, data in route_data.items():
                dx, dy = self.tracker_mgr.get_offset_for_frame(f_idx, (0, 0))
                px = sx + (data["x_pos"] + dx + 1) / 2 * w
                py = sy + (data["y_pos"] + dy + 1) / 2 * h

                # Если кликнули в радиусе 10 пикселей от ключа
                if (pos.x() - px) ** 2 + (pos.y() - py) ** 2 < 100:
                    self._is_dragging = True
                    self._dragging_keyframe_idx = f_idx  # Запоминаем, какой кадр правим
                    self._drag_offset_x = pos.x() - px
                    self._drag_offset_y = pos.y() - py
                    return False


        # 2. Если в ключи не попали, проверяем нажатие на текущий эллипс (старая логика)
        if self._is_hovering_ellipse(pos, rect):
            self._is_dragging = True
            self._dragging_keyframe_idx = self.current_frame_idx  # Правим текущий кадр

            geo = self._get_geometry(w, h)
            self._drag_offset_x = pos.x() - (sx + geo["cx"])
            self._drag_offset_y = pos.y() - (sy + geo["cy"])

        return False

    def handle_mouse_move(self, pos, rect):
        if self._is_dragging:
            w, h = rect.width(), rect.height()
            sx, sy = rect.left(), rect.top()

            # 1. Вычисляем, где должен быть ВИЗУАЛЬНЫЙ центр в координатах [-1, 1]
            visual_target_x = ((pos.x() - self._drag_offset_x - sx) / w) * 2 - 1
            visual_target_y = ((pos.y() - self._drag_offset_y - sy) / h) * 2 - 1

            # 2. Получаем текущее смещение трекера для этого кадра
            # Передаем (0,0) как заглушку, так как нам нужна дельта из файла
            dx, dy = self.tracker_mgr.get_offset_for_frame(self._dragging_keyframe_idx, (0, 0))

            # 3. Новое значение ключа = Визуальный центр - Смещение трекера
            new_key_x = visual_target_x - dx
            new_key_y = visual_target_y - dy

            # Сохраняем оригинальный кадр
            original_frame = self.current_frame_idx

            # Переключаемся на кадр ключа, который тянем
            self.set_current_frame(self._dragging_keyframe_idx)

            # Записываем новые координаты (автоматически обновит ключ в словаре)
            self.set_param("x_pos", max(-1.0, min(1.0, new_key_x)))
            self.set_param("y_pos", max(-1.0, min(1.0, new_key_y)))

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
                dx, dy = self.tracker_mgr.get_offset_for_frame(f_idx, (0, 0))
                px = sx + (data["x_pos"] + dx + 1) / 2 * w
                py = sy + (data["y_pos"] + dy + 1) / 2 * h

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
        data["marks"] = list( self.get_keyframe_indices() )
        data["ranges"] = self.storage.get_ranges()

        return data

    def init_tracker(self, frame, frame_idx):
        """Инициализация трекера через TrackerManager"""
        h, w = frame.shape[:2]

        # 1. Получаем текущую экранную позицию (с учетом старых треков и ключей)
        # Это важно, чтобы начать трекинг именно оттуда, где сейчас находится эллипс
        geo = self._get_geometry(w, h)

        # ROI для OpenCV (центрируем по текущему положению)
        roi = (
            int(geo["cx"] - geo["rx"]),
            int(geo["cy"] - geo["ry"]),
            int(geo["rx"] * 2),
            int(geo["ry"] * 2)
        )

        # 2. Подготавливаем данные для менеджера
        # Текущая позиция в формате [-1, 1]
        current_pos = (self.get_param("x_pos"), self.get_param("y_pos"))

        # Собираем все будущие ручные ключи, чтобы менеджер знал, где делать "запекание"
        all_keys = self.get_keyframes_data(["x_pos", "y_pos"])
        future_keys = []
        for f_idx, val in all_keys.items():
            if f_idx > frame_idx:
                future_keys.append((f_idx, val["x_pos"], val["y_pos"]))

        # 3. Запускаем менеджер
        success = self.tracker_mgr.init_tracker(
            frame,
            frame_idx,
            roi,
            current_pos,
            future_keys
        )

        if success:
            # Если мы начали трекинг не на существующем ключе,
            # принудительно создаем ручной ключ в точке старта.
            # Это гарантирует, что Manual_Path начнется там же, где и Tracker_Path.
            if frame_idx not in all_keys:
                self._set_manual_key_callback(frame_idx, current_pos[0], current_pos[1])

            self._last_tracked_frame = frame_idx

        return success

    def update_tracker(self, frame, frame_idx):
        """Обновление позиции через менеджер"""
        if not self.tracker_mgr.is_active():
            return False

        if self._last_tracked_frame == frame_idx:
            return True

        # Защита от прыжков по таймлайну
        if frame_idx <= self._last_tracked_frame or frame_idx > self._last_tracked_frame + 5:
            # При резком прыжке останавливаем и запекаем то, что успели
            self.tracker_mgr.stop_and_save(self._last_tracked_frame)
            return False

        # Вся математика и запись в буфер теперь внутри менеджера
        success = self.tracker_mgr.update(frame, frame_idx)

        if success:
            self._last_tracked_frame = frame_idx

        return success

    def stop_tracker(self):
        """Остановка трекера с запеканием данных"""
        if self.tracker_mgr.is_active():
            self.tracker_mgr.stop_and_save(self._last_tracked_frame)

    def can_tracking(self):
        """доступен ли трекер"""
        return True

    def is_tracking(self):
        return self.tracker_mgr.is_active()

    def reset_tracking(self):
        """Полный сброс трекинга для этого фильтра."""
        self.tracker_mgr.clear_all_data()

        return True


def clamp(n, minn, maxn):
    return max(min(maxn, n), minn)