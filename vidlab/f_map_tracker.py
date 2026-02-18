import os
import cv2
import numpy as np
from PySide6.QtGui import QPainter, QPen, QColor, QBrush, QPolygonF
from PySide6.QtCore import Qt, QPointF, QRectF

from .f_asinc_base import FilterAsyncBase
from .m_cam_tracker_cv2 import CameraTrackerCv2Model
from .m_cam_tracker_slam import CameraTrackerSlamModel

DATA_VERSION = 4


class FilterMapTracker(FilterAsyncBase):
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
        self.name = "Map Tracker"

        # Данные в памяти
        self._abs_path = np.array([], dtype=np.float32)  # Накопленный путь [x, y, angle]
        self._marks = []  # Кадры смены сцен
        self._map_cloud = []  # точки с возрастом

        self.load_data()

    def get_params_metadata(self):
        return {
            "act_in": {"type": "in_out", "default": -1},
            "show_map": {"type": "bool", "default": True},
            "map_size": {"type": "float", "min": 0.1, "max": 0.9, "default": 0.5},
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
            "map_cloud": self._map_cloud,
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
                    self._map_cloud = payload.get("map_cloud", np.array([]))
            except Exception as e:
                print(f"Error loading {self.name} cache: {e}")

    def process(self, frame, idx):
        # Сам кадр не меняем
        return frame

    def render_overlay(self, painter, idx, viewport_rect):
        if not self.get_param("show_map") or len(self._abs_path) <= idx:
            return

        # 1. Размеры и позиция карты
        vw, vh = viewport_rect.width(), viewport_rect.height()
        m_size = int(min(vw, vh) * self.get_param("map_size"))
        m_x = int(vw * self.get_param("map_pos_x")) + viewport_rect.left()
        m_y = int(vh * self.get_param("map_pos_y")) + viewport_rect.top()
        map_rect = QRectF(m_x, m_y, m_size, m_size)

        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        # Фон
        painter.setPen(QPen(QColor(100, 100, 100, 200), 2))
        painter.setBrush(QBrush(QColor(30, 30, 30, 150)))
        painter.drawRoundedRect(map_rect, 5, 5)

        # 2. Объединяем данные для расчета масштаба
        path_data = self._abs_path[:, :2]  # [N, 2]
        cloud_data = self._map_cloud[:, :2] if len(self._map_cloud) > 0 else path_data

        # Вычисляем общие границы (путь + облако)
        all_points = np.vstack([path_data, cloud_data])
        p_min = all_points.min(axis=0)
        p_max = all_points.max(axis=0)
        p_range = np.maximum(p_max - p_min, 1e-6)

        # Масштаб (с запасом 15%)
        margin = m_size * 0.15
        draw_area_size = m_size - 2 * margin
        scale = (draw_area_size / np.max(p_range)) * self.get_param("map_scale")

        # Центрирование
        offset_x = map_rect.center().x() - ((p_min[0] + p_max[0]) / 2) * scale
        offset_y = map_rect.center().y() - ((p_min[1] + p_max[1]) / 2) * scale

        # 3. Рисуем облако точек (Map Cloud)
        # Используем возраст точки для прозрачности или размера
        for i in range(len(self._map_cloud)):
            px = self._map_cloud[i][0] * scale + offset_x
            py = self._map_cloud[i][1] * scale + offset_y
            pt_pos = QPointF(px, py)

            if map_rect.contains(pt_pos):
                age = self._map_cloud[i][2]
                # Чем старше точка, тем она ярче (достовернее)
                alpha = int(min(255, 100 + age * 10))
                painter.setPen(Qt.PenStyle.NoPen)
                painter.setBrush(QBrush(QColor(0, 200, 255, alpha)))

                # Рисуем маленькие квадратики "препятствий"
                painter.drawRect(QRectF(px - 2, py - 2, 4, 4))

        # 4. Рисуем траекторию (упрощенно)
        step = max(1, len(self._abs_path) // 600)
        path_to_draw = self._abs_path[::step]

        path_pen = QPen(QColor(0, 255, 100, 180), 1.5)
        painter.setPen(path_pen)
        last_point = None
        for i in range(len(path_to_draw)):
            px = path_to_draw[i][0] * scale + offset_x
            py = path_to_draw[i][1] * scale + offset_y
            curr_pt = QPointF(px, py)
            if last_point and map_rect.contains(curr_pt) and map_rect.contains(last_point):
                painter.drawLine(last_point, curr_pt)
            last_point = curr_pt


        # 5. Текущая камера
        curr_data = self._abs_path[idx]
        cx = curr_data[0] * scale + offset_x
        cy = curr_data[1] * scale + offset_y
        camera_pos = QPointF(cx, cy)

        if map_rect.contains(camera_pos):
            # Конус обзора
            angle = curr_data[2]
            fov_len, fov_angle = 20.0, 0.4
            cone = QPolygonF([
                camera_pos,
                QPointF(cx + fov_len * np.cos(angle - fov_angle), cy + fov_len * np.sin(angle - fov_angle)),
                QPointF(cx + fov_len * np.cos(angle + fov_angle), cy + fov_len * np.sin(angle + fov_angle))
            ])
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QBrush(QColor(255, 150, 0, 150)))
            painter.drawPolygon(cone)

            # Маркер камеры
            painter.setBrush(QBrush(QColor(255, 50, 50)))
            painter.setPen(QPen(Qt.GlobalColor.white, 1))
            painter.drawEllipse(camera_pos, 3, 3)

        painter.restore()

    def run_internal_logic(self, worker):
        cap = cv2.VideoCapture(self.video_path)
        w, h = int(cap.get(3)), int(cap.get(4))
        total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))

        # Создаем модель
        params = {
                "min_features" : self.get_param("min_features"),
            }

        model = CameraTrackerSlamModel(w, h, params)

        for frame_idx in range(total_frames):
            if not worker.is_running: break
            ret, frame = cap.read()
            if not ret: break

            # Скармливаем кадр модели
            model.process_frame(frame, frame_idx)

            if frame_idx % 100 == 0:
                results = model.get_results()
                results.update({
                    "progress": int(100 * frame_idx / total_frames)
                })
                worker.progress.emit(results)

        cap.release()
        results = model.get_results()
        results.update({"progress": 100})
        worker.progress.emit(results)

    def _on_worker_progress(self, data):
        """Принимаем пакеты данных и обновляем путь"""
        if "abs_path" in data:
            self._abs_path = data["abs_path"]

        if "map_cloud" in data:
            self._map_cloud = data["map_cloud"]
            print(f"3d point count: {len(self._map_cloud)}")
            print(data["stats"])

        if "ranges" in data: self._analyzed_ranges = data["ranges"]
        if "marks" in data: self._detected_scenes = data["marks"]
        self.save_data()

        if "progress" in data:
            self.progress = data["progress"]



