import os
import cv2
import numpy as np
from PySide6.QtGui import QPainter, QPen, QColor, QBrush, QPolygonF
from PySide6.QtCore import Qt, QPointF, QRectF

from vidlab.f_asinc_base import FilterAsyncBase
from .m_slam_base import SlamBaseModel  # Или конкретная реализация потомка
from .m_slam_cv2d import SlamCv2dModel

DATA_VERSION = 5

class FilterSlamTracker(FilterAsyncBase):
    def __init__(self, num, cache_dir, params=None):
        # Создаем временную модель, чтобы забрать метаданные параметров
        self.interactive_model = SlamCv2dModel(is_batch_mode=False)

        super().__init__(num, cache_dir, params)
        self.name = "SLAM Tracker"

        # Данные пути для карты
        self._abs_path = np.array([], dtype=np.float32)
        self.load_data()

    def get_params_metadata(self):
        # Базовые параметры UI
        meta = {
            "show_points": {"type": "bool", "default": True},

            "show_horizon": {"type": "bool", "default": True},
            "horizon_alpha": {"type": "float", "min": 0.0, "max": 1.0, "default": 0.7},

            "show_velocity": {"type": "bool", "default": True},
            "velocity_scale": {"type": "float", "min": 0.1, "max": 10.0, "default": 1.0},

            "show_map": {"type": "bool", "default": True},
            "map_size": {"type": "float", "min": 0.1, "max": 0.5, "default": 0.25},
            "map_pos_x": {"type": "float", "min": 0.0, "max": 0.9, "default": 0.02},
            "map_pos_y": {"type": "float", "min": 0.0, "max": 0.9, "default": 0.02},
            "map_scale": {"type": "float", "min": 0.1, "max": 10.0, "default": 1.0},
        }
        # Параметры логики из модели
        meta.update(self.interactive_model.get_params_metadata())
        return meta

    def save_data(self):
        if not self.cache_dir: return
        os.makedirs(self.cache_dir, exist_ok=True)

        payload = {
            "version": DATA_VERSION,
            "ranges": self._analyzed_ranges,
            "marks": self._detected_scenes,
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
                    self._abs_path = payload.get("abs_path", np.array([]))
            except Exception as e:
                print(f"Error loading {self.name} cache: {e}")

    # --- ЛОГИКА ОБРАБОТКИ ---

    def process(self, frame, idx):
        # 1. Синхронизируем параметры и обновляем интерактивную модель
        self.interactive_model.set_params(self.get_params())
        self.interactive_model.update(frame, idx)

        if self.focused:
            self._draw_area(frame)

        # 2. Рисуем слои оверлея OpenCV (точки, горизонт, скорость)
        if self.get_param("show_points"):
            self._draw_motion_cv(frame)

        if self.get_param("show_horizon"):
            self._draw_horizon_cv(frame)

        if self.get_param("show_velocity"):
            self._draw_velocity_cv(frame)

        return frame

    # --- ОТРИСОВКА CV2 (Интерактив) ---

    def _draw_area(self, frame):
        if self.get_param("roi_left",-1) < 0: return

        h, w = frame.shape[:2]
        x1 = int(w * self.get_param("roi_left")) - 1
        x2 = int(w * self.get_param("roi_right")) + 1
        y1 = int(h * self.get_param("roi_top")) - 1
        y2 = int(h * self.get_param("roi_bottom")) + 1
        cv2.rectangle(frame, (x1, y1), (x2, y2), (0, 20, 100), 2)  # Желтая рамка

    def _draw_motion_cv(self, frame):
        # Модель должна возвращать структуру, похожую на результат analyze_frame
        # Для теста SlamBaseModel просто отдает список pts
        pts = self.interactive_model.get_points()
        for p in pts:
            x, y = map(int, p['pt'])
            age = p['age']
            # Цвет от возраста (Градиент)
            t = min(age / 50, 1.0)
            color = (int(255 * t), int(255 * (1 - t)), int(255 * (1 - t)))
            cv2.circle(frame, (x, y), 2, color, -1)

    def _draw_horizon_cv(self, frame):
        pitch, roll, yaw = self.interactive_model.get_horizon_angles()
        h, w = frame.shape[:2]
        cx, cy = w // 2, h // 2

        overlay = frame.copy()
        R = cv2.getRotationMatrix2D((cx, cy), roll, 1.0)
        px_per_deg = w / self.get_param("fov_h", 111.0)

        # Тангаж (Pitch): инвертируем, чтобы при наклоне камеры вниз линия шла вверх
        pitch_offset = int( pitch * px_per_deg)

        # Рисуем риски шкалы
        # Берем диапазон вокруг текущего yaw
        fov_view = 60
        start_ang = int(yaw - fov_view)
        end_ang = int(yaw + fov_view)

        for ang in range(start_ang, end_ang + 1):
            if ang % 5 == 0:
                # rel_x: если ang > yaw, точка должна быть справа от центра
                rel_x = int((ang - yaw) * px_per_deg)

                pt_x = cx + rel_x
                pt_y = cy + pitch_offset

                # Применяем Roll через матрицу R
                tx = R[0, 0] * pt_x + R[0, 1] * pt_y + R[0, 2]
                ty = R[1, 0] * pt_x + R[1, 1] * pt_y + R[1, 2]

                if 0 <= tx < w and 0 <= ty < h:
                    is_major = (ang % 15 == 0)
                    # Положительные градусы приводим к 0-359 для подписи
                    display_deg = ang % 360

                    color = (255, 255, 255) if is_major else (10, 10, 10)
                    cv2.circle(overlay, (int(tx), int(ty)), 5, color, -1)

                    if is_major:
                        cv2.putText(overlay, str(display_deg), (int(tx) - 10, int(ty) - 10),
                                    cv2.FONT_HERSHEY_SIMPLEX, 1, color, 2)

        alpha = self.get_param("horizon_alpha")
        cv2.addWeighted(overlay, alpha, frame, 1 - alpha, 0, frame)

    def _draw_velocity_cv(self, frame):
        vel = self.interactive_model.get_fwd_velocity()
        h, w = frame.shape[:2]
        scale = self.get_param("velocity_scale")
        arrow_len = int(vel * scale * 20.0)

        cv2.arrowedLine(frame, (w // 2, int(h * 0.9)), (w // 2, int(h * 0.9) - arrow_len), (0, 255, 0), 2)

    # --- ОТРИСОВКА QPAINTER (Карта / Overlay) ---

    def render_overlay(self, painter, idx, viewport_rect):
        if not self.get_param("show_map") or len(self._abs_path) == 0:
            return

        # Используем твою логику отрисовки из FilterCameraTracker2D
        painter.save()
        self._draw_mini_map(painter, idx, viewport_rect)
        painter.restore()

    def _draw_mini_map(self, painter, idx, viewport_rect):
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

        path_to_draw = np.array(self._abs_path, dtype=np.float32)
        # 3. Подготовка данных пути
        step = max(1, len(self._abs_path) // 600)
        path_to_draw = path_to_draw[::step]

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
                angle = np.radians(curr_data[2])  # В радианах
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
                # self._draw_data_gr(painter, idx, viewport_rect)


    # --- АСИНХРОННЫЙ ПРОСЧЕТ ---

    def run_internal_logic(self, worker):
        cap = cv2.VideoCapture(self.video_path)
        total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))

        # Создаем пакетную модель
        batch_model = SlamCv2dModel(is_batch_mode=True)
        batch_model.set_params(self.get_params())

        for f_idx in range(total_frames):
            if not worker.is_running: break
            ret, frame = cap.read()
            if not ret: break

            batch_model.update(frame, f_idx)

            if f_idx % 200 == 0:
                worker.progress.emit({
                    "abs_path": batch_model.get_full_path(),
                    "progress": int(100 * f_idx / total_frames),
                    "ranges": [[0,f_idx]]
                })

        cap.release()
        worker.progress.emit({
            "abs_path": batch_model.get_full_path(),
            "ranges": [[0, f_idx]],
            "progress": 100
        })

    def _on_worker_progress(self, data):

        if "abs_path" in data: self._abs_path = data["abs_path"]

        if "ranges" in data: self._analyzed_ranges = data["ranges"]

        if "marks" in data: self._detected_scenes = data["marks"]

        if "progress" in data: self.progress = data["progress"]

        self.save_data()