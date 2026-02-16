import os
import cv2
import numpy as np
from PySide6.QtGui import QPainter, QPen, QColor, QBrush, QPolygonF
from PySide6.QtCore import Qt, QPointF, QRectF

from .f_asinc_base import FilterAsyncBase

DATA_VERSION = 3


class FilterCameraTracker2D(FilterAsyncBase):
    def __init__(self, num, cache_dir, params=None):
        # Параметры по умолчанию для UI и логики
        default_params = {
            "show_map": True,
            "map_size": 0.25,  # Размер карты от размера экрана
            "map_pos_x": 0.02,  # Отступ слева
            "map_pos_y": 0.02,  # Отступ сверху
            "map_scale": 1.0,  # Дополнительный множитель зума
            "min_features": 50,  # Для детектора
            "smooth_map": 5  # Радиус сглаживания только для отрисовки карты
        }
        if params:
            default_params.update(params)

        super().__init__(num, cache_dir, default_params)
        self.name = "CameraTracker2D"

        # Данные в памяти
        self._abs_path = np.array([], dtype=np.float32)  # Накопленный путь [x, y, angle]
        self._marks = []  # Кадры смены сцен
        self._raw_deltas = []  # Список дельт, полученных от воркера

        self.load_data()

    def get_params_metadata(self):
        return {
            "act_in": {"type": "in_out", "default": -1},
            "show_map": {"type": "bool", "default": True},
            "map_size": {"type": "float", "min": 0.1, "max": 0.5, "default": 0.25},
            "map_pos_x": {"type": "float", "min": 0.0, "max": 0.9, "default": 0.02},
            "map_pos_y": {"type": "float", "min": 0.0, "max": 0.9, "default": 0.02},
            "map_scale": {"type": "float", "min": 0.1, "max": 10.0, "default": 1.0},
            "min_features": {"type": "int", "min": 10, "max": 500, "default": 50},
        }

    def get_npy_filename(self):
        return os.path.join(self.cache_dir, f"{self.get_id()}.npy")

    def save_data(self):
        if not self.cache_dir: return
        os.makedirs(self.cache_dir, exist_ok=True)

        payload = {
            "version": DATA_VERSION,
            "ranges": self._analyzed_ranges,
            "marks": self._detected_scenes,
            "raw_deltas": self._raw_deltas,
            "abs_path": self._abs_path
        }
        np.save(self.get_npy_filename(), payload)

    def load_data(self):
        path = self.get_npy_filename()
        if os.path.exists(path):
            try:
                payload = np.load(path, allow_pickle=True).item()
                if payload.get("version") == DATA_VERSION:
                    self._analyzed_ranges = payload.get("ranges", [])
                    self._detected_scenes = payload.get("marks", [])
                    self._raw_deltas = payload.get("raw_deltas", [])
                    self._abs_path = payload.get("abs_path", np.array([]))
            except Exception as e:
                print(f"Error loading {self.name} cache: {e}")

    def _update_abs_path(self):
        if not self._raw_deltas: return
        raw_np = np.array(self._raw_deltas)
        abs_path = np.zeros((len(raw_np), 3))

        cx, cy, cyaw = 0.0, 0.0, 0.0

        for i in range(len(raw_np)):
            dyaw, dpitch, droll, tx, ty, tz = raw_np[i]

            # 1. Обновляем угол
            cyaw += dyaw

            # 2. Движение вперед по направлению cyaw.
            # В камере Z(tz) - вперед. На карте мы хотим, чтобы
            # при cyaw=0 движение шло строго вверх (по оси Y).

            # Проекция локального tx, tz на глобальную карту:
            dx = tx * np.cos(cyaw) + tz * np.sin(cyaw)
            dy = -tx * np.sin(cyaw) + tz * np.cos(cyaw)  # Минус, так как Y на карте растет вверх

            cx += dx
            cy += dy

            abs_path[i] = [cx, cy, cyaw]

        self._abs_path = abs_path

    def process(self, frame, idx):
        # Сам кадр не меняем
        return frame

    def render_overlay(self, painter, idx, viewport_rect):
        """
        Отрисовка карты пути через QPainter.
        painter: экземпляр QPainter
        idx: текущий кадр
        viewport_rect: QRect текущего окна просмотра
        """
        if not self.get_param("show_map") or len(self._abs_path) <= idx:
            return

        # 1. Рассчитываем размеры и позицию виджета карты
        vw = viewport_rect.width()
        vh = viewport_rect.height()

        m_size = int(min(vw, vh) * self.get_param("map_size"))
        m_x = int(vw * self.get_param("map_pos_x")) + viewport_rect.left()
        m_y = int(vh * self.get_param("map_pos_y")) + viewport_rect.top()

        map_rect = QRectF(m_x, m_y, m_size, m_size)

        # 2. Настройки рисования
        painter.save()  # Сохраняем состояние (кисти, перья)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        # Рисуем фон карты (полупрозрачный темный квадрат)
        painter.setPen(QPen(QColor(100, 100, 100, 200), 2))
        painter.setBrush(QBrush(QColor(30, 30, 30, 150)))
        painter.drawRoundedRect(map_rect, 5, 5)

        # 3. Подготовка данных пути
        step = max(1, len(self._abs_path) // 600)
        path_to_draw = self._abs_path[::step]

        if len(path_to_draw) > 1:
            # Вычисляем границы для нормализации
            p_min = path_to_draw[:, :2].min(axis=0)
            p_max = path_to_draw[:, :2].max(axis=0)
            p_range = np.maximum(p_max - p_min, 1e-6)

            # Масштаб и смещение, чтобы вписать путь в map_rect (с отступом 15%)
            margin = m_size * 0.15
            draw_area_size = m_size - 2 * margin

            scale = draw_area_size / np.max(p_range)
            scale *= self.get_param("map_scale")

            # Центрирование пути внутри map_rect
            offset_x = map_rect.center().x() - ((p_min[0] + p_max[0]) / 2) * scale
            offset_y = map_rect.center().y() - ((p_min[1] + p_max[1]) / 2) * scale

            # 4. Рисуем траекторию
            path_pen = QPen(QColor(0, 255, 100, 180), 1.5)
            path_pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
            painter.setPen(path_pen)

            last_point = None
            for i in range(len(path_to_draw)):
                px = path_to_draw[i][0] * scale + offset_x
                py = path_to_draw[i][1] * scale + offset_y
                current_point = QPointF(px, py)

                if last_point and map_rect.contains(current_point) and map_rect.contains(last_point):
                    painter.drawLine(last_point, current_point)
                last_point = current_point

            # 5. Текущая позиция камеры и "конус обзора"
            curr_data = self._abs_path[idx]
            cx = curr_data[0] * scale + offset_x
            cy = curr_data[1] * scale + offset_y
            camera_pos = QPointF(cx, cy)

            if map_rect.contains(camera_pos):
                angle = curr_data[2]  # В радианах
                fov_len = 25.0
                fov_angle = 0.4  # Полуширина конуса

                # Создаем треугольник направления (конус)
                cone = QPolygonF()
                cone.append(camera_pos)
                cone.append(QPointF(cx + fov_len * np.cos(angle - fov_angle),
                                    cy + fov_len * np.sin(angle - fov_angle)))
                cone.append(QPointF(cx + fov_len * np.cos(angle + fov_angle),
                                    cy + fov_len * np.sin(angle + fov_angle)))

                painter.setPen(Qt.PenStyle.NoPen)
                painter.setBrush(QBrush(QColor(255, 150, 0, 180)))
                painter.drawPolygon(cone)

                # Точка самой камеры
                painter.setBrush(QBrush(QColor(255, 50, 50)))
                painter.setPen(QPen(Qt.GlobalColor.white, 1))
                painter.drawEllipse(camera_pos, 4, 4)

                # графики
                self._draw_data_gr(painter, idx, viewport_rect)


        painter.restore()  # Возвращаем настройки painter в исходное состояние

    def _draw_data_gr(self, painter, idx, viewport_rect):
        # --- ДИАГНОСТИЧЕСКИЕ ГРАФИКИ ---
        if len(self._raw_deltas) <= idx: return

        # Настройки диагностического окна
        margin = 20
        gh = 150  # Высота блока графиков
        gw = viewport_rect.width() - margin * 2
        rect_g = QRectF(viewport_rect.left() + margin, viewport_rect.bottom() - gh - margin, gw, gh)

        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, False)  # Для графиков лучше без сглаживания
        painter.setBrush(QColor(0, 0, 0, 200))
        painter.setPen(QPen(QColor(150, 150, 150), 1))
        painter.drawRect(rect_g)

        # Окно просмотра: 300 кадров (текущий в центре)
        view_range = 300
        half_v = view_range // 2
        start_f = max(0, idx - half_v)
        end_f = min(len(self._raw_deltas), idx + half_v)
        data_win = np.array(self._raw_deltas[start_f:end_f])

        if len(data_win) > 1:
            # Цвета для 6 кривых
            # Углы: Yaw(Red), Pitch(Green), Roll(Blue)
            # Смещение: TX(Yellow), TY(Cyan), TZ(Magenta)
            colors = [
                QColor(255, 50, 50),  # Yaw
                QColor(50, 255, 50),  # Pitch
                QColor(80, 80, 255),  # Roll
                QColor(255, 255, 0),  # TX
                QColor(0, 255, 255),  # TY
                QColor(255, 0, 255)  # TZ
            ]

            mid_y = rect_g.center().y()
            step_x = gw / view_range

            for c_idx in range(6):
                painter.setPen(QPen(colors[c_idx], 1))

                # Масштабирование: углы усиливаем (x100), смещение (x40)
                scale = 300 if c_idx < 3 else 50

                for i in range(len(data_win) - 1):
                    x1 = rect_g.left() + (i + (start_f - (idx - half_v))) * step_x
                    x2 = x1 + step_x

                    y1 = mid_y - data_win[i][c_idx] * scale
                    y2 = mid_y - data_win[i + 1][c_idx] * scale

                    # Ограничиваем отрисовку внутри прямоугольника
                    if rect_g.top() < y1 < rect_g.bottom() and rect_g.top() < y2 < rect_g.bottom():
                        painter.drawLine(QPointF(x1, y1), QPointF(x2, y2))

        # Текущий кадр (белая вертикальная линия)
        painter.setPen(QPen(Qt.GlobalColor.white, 1, Qt.PenStyle.DashLine))
        cursor_x = rect_g.left() + half_v * step_x
        painter.drawLine(QPointF(cursor_x, rect_g.top()), QPointF(cursor_x, rect_g.bottom()))

        # Легенда
        painter.setPen(Qt.GlobalColor.white)
        font = painter.font()
        font.setPointSize(8)
        painter.setFont(font)
        painter.drawText(rect_g.topLeft() + QPointF(5, 12),
                         "Angles: YAW(R), PITCH(G), ROLL(B) | Move: TX(Y), TY(C), TZ(M)")
        painter.restore()

    def run_internal_logic(self, worker):
        """Асинхронный сканер: только вычисления"""
        cap = cv2.VideoCapture(self.video_path)
        w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))

        # 1. Задаем матрицу камеры (K)
        focal_length = w * 7
        center = (w / 2, h / 2)
        K = np.array([
            [focal_length, 0, center[0]],
            [0, focal_length, center[1]],
            [0, 0, 1]
        ], dtype=np.float32)

        prev_gray = None
        prev_pts = None

        # Глобальные данные
        all_deltas = []  # Храним [yaw, move_x, move_z]
        marks = []
        frame_idx = 0
        prev_valid_delta = [0, 0, 0, 0, 0, 0]

        while worker.is_running:
            ret, frame = cap.read()
            if not ret: break

            curr_gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)

            if prev_gray is not None:
                # 2. Ищем точки
                if prev_pts is None or len(prev_pts) < 100:
                    prev_pts = cv2.goodFeaturesToTrack(prev_gray, maxCorners=300, qualityLevel=0.01, minDistance=30)

                if prev_pts is not None:
                    curr_pts, status, _ = cv2.calcOpticalFlowPyrLK(prev_gray, curr_gray, prev_pts, None)

                    good_prev = prev_pts[status == 1]
                    good_curr = curr_pts[status == 1]

                    if len(good_prev) > self.get_param("min_features"):
                        # 3. Находим Essential Matrix
                        E, mask = cv2.findEssentialMat(good_curr, good_prev, K, method=cv2.RANSAC, prob=0.999,
                                                       threshold=1.0)

                        if E is not None and E.shape == (3, 3):
                            # mask_pose покажет, сколько точек реально "согласны" с этой позой
                            num_inliers, R, t, mask_pose = cv2.recoverPose(E, good_curr, good_prev, K)

                            inlier_ratio = num_inliers / len(good_curr)

                            # 1. Если инлайеров меньше 50% или их абсолютное количество мало - это шум
                            if False and (num_inliers < 30 or inlier_ratio < 0.5):
                                all_deltas.append(prev_valid_delta)  # Оставляем прошлое движение
                                continue

                            # Извлекаем углы
                            yaw = np.arctan2(R[0, 2], R[2, 2])
                            pitch = np.arcsin(-R[1, 2])
                            roll = np.arctan2(R[1, 0], R[1, 1])
                            tx, ty, tz = t[0][0], t[1][0], t[2][0]

                            current_delta = [yaw, pitch, roll, tx, ty, tz]

                            # 2. Проверка на "разрыв реальности"
                            # Если yaw изменился более чем на 0.2 радиана (~11 град) за 1 кадр - это выброс
                            if  abs(yaw) > 0.2:
                                current_delta[0] = 0
                            else:
                                prev_valid_delta = current_delta

                            all_deltas.append(current_delta)

                            prev_pts = good_curr[mask.flatten() > 0].reshape(-1, 1, 2)
                        else:
                            all_deltas.append([0, 0, 0, 0, 0, 0])
                    else:
                        marks.append(frame_idx)
                        all_deltas.append([0, 0, 0, 0, 0, 0])
                        prev_pts = None

            prev_gray = curr_gray
            frame_idx += 1

            if frame_idx % 60 == 0:
                worker.progress.emit({
                    "raw_deltas": list(all_deltas),
                    "marks": list(marks),
                    "ranges": [[0, frame_idx]],
                    "progress": int(100 * frame_idx / total_frames)
                })

        cap.release()
        worker.progress.emit({
            "raw_deltas": list(all_deltas),
            "marks": list(marks),
            "ranges": [[0, frame_idx]],
            "progress": 100})

    def _on_worker_progress(self, data):
        """Принимаем пакеты данных и обновляем путь"""
        if "raw_deltas" in data:
            self._raw_deltas = data["raw_deltas"]
        # self._marks = data.get("marks", [])
        if "ranges" in data: self._analyzed_ranges = data["ranges"]
        if "marks" in data: self._detected_scenes = data["marks"]
        self._update_abs_path()
        self.save_data()

        if "progress" in data:
            self.progress = data["progress"]

