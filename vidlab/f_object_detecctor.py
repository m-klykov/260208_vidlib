import cv2
import os
import json
import numpy as np
import torch
from ultralytics import YOLO
from .f_base import FilterBase

CASH_TO_FILE = False # сохраняем ли кеш на диск
USE_SEGMENTATION = True # Переключатель режима

class FilterObjectDetector(FilterBase):
    def __init__(self, num, cache_dir, params=None):
        # Настройки по умолчанию
        if not params:
            params = {
                "conf": 0.25,
                "show_labels": True,
                "use_cache": False,
                "mask_opacity": 0.3  # Добавим прозрачность для заливки
            }
        super().__init__(num, cache_dir, params)
        self.name = "AI Object Detector"

        # Модель загрузим только при необходимости (lazy loading)
        self._model = None

        # Кеш в оперативной памяти для текущей сессии
        self._memory_cache = {}

        # Пытаемся загрузить кеш с диска при инициализации
        if CASH_TO_FILE:
            self.load_cache()

    def get_params_metadata(self):
        return {
            "conf": {"type": "float", "min": 0.1, "max": 1.0, "default": 0.25},
            "show_labels": {"type": "bool", "default": True},
            # "use_cache": {"type": "bool", "default": True},
            "show_contour": {"type": "bool", "default": True},  # Новый флаг
            "mask_opacity": {"type": "float", "min": 0.0, "max": 1.0, "default": 0.3}
        }

    def _get_model(self):
        """Ленивая инициализация модели YOLO"""
        if self._model is None:
            # Выбираем файл модели в зависимости от константы
            model_name = 'yolov8n-seg.pt' if USE_SEGMENTATION else 'yolov8n.pt'
            model_path = os.path.join(os.getcwd(), 'models', model_name)
            self._model = YOLO(model_path)

            # Получаем словарь всех классов
            classes = self._model.names
            print(f"AI Detector loaded. Known objects: {len(classes)}")
            # print(classes) # Раскомментируйте, чтобы увидеть весь список {ID: 'Name'}

            if torch.cuda.is_available():
                self._model.to('cuda')
                print(f"AI Detector: Using GPU (CUDA) with {'Segmentation' if USE_SEGMENTATION else 'BBox'}")
        return self._model

    def get_cache_path(self):
        """Путь к JSON файлу с детекциями"""
        return os.path.join(self.cache_dir, f"{self.get_id()}.json")

    def load_cache(self):
        path = self.get_cache_path()
        if os.path.exists(path):
            try:
                with open(path, 'r') as f:
                    # Ключи в JSON всегда строки, преобразуем обратно в int (номер кадра)
                    raw_data = json.load(f)
                    self._memory_cache = {int(k): v for k, v in raw_data.items()}
            except Exception as e:
                print(f"Error loading AI cache: {e}")

    def save_cache(self):
        path = self.get_cache_path()
        os.makedirs(self.cache_dir, exist_ok=True)
        try:
            with open(path, 'w') as f:
                json.dump(self._memory_cache, f)
        except Exception as e:
            print(f"Error saving AI cache: {e}")

    def process(self, frame, idx):
        if not self.focused:
            return frame

        detections = None
        use_cache = self.get_param("use_cache")

        if use_cache and idx in self._memory_cache:
            detections = self._memory_cache[idx]
        else:
            model = self._get_model()
            device = 'cuda' if torch.cuda.is_available() else 'cpu'

            results = model.predict(
                frame,
                device=device,
                conf=self.get_param("conf"),
                half=(device == 'cuda'),
                imgsz=320,
                max_det=20,
                verbose=False
            )

            if results and len(results[0]) > 0:
                res = results[0].cpu()
                detections = []

                # Логика извлечения данных
                if USE_SEGMENTATION and res.masks is not None:
                    # Извлекаем контуры (полигоны)
                    for i, mask in enumerate(res.masks.xy):
                        detections.append({
                            "poly": mask.tolist(),  # Список точек [[x,y], [x,y]...]
                            "name": res.names[int(res.boxes.cls[i])],
                            "bbox": res.boxes.xyxy[i].tolist()  # Ббокс все равно берем для текста
                        })
                else:
                    # Старая логика с боксами
                    for box in res.boxes:
                        detections.append({
                            "bbox": box.xyxy[0].tolist(),
                            "name": res.names[int(box.cls[0])]
                        })

                if use_cache: self._add_to_cache(idx, detections)
                self._update_ranges(idx)

        # 3. Отрисовка
        if detections:
            self._draw_detections(frame, detections)

        return frame

    def _draw_detections(self, frame, detections):
        overlay = frame.copy() if self.get_param("mask_opacity") > 0 else None
        show_contour = self.get_param("show_contour")
        color = (0, 255, 127)  # Основной цвет

        for obj in detections:
            # 1. Рисуем контур или бокс
            if USE_SEGMENTATION and show_contour and "poly" in obj:
                pts = np.array(obj["poly"], np.int32)
                # Рисуем обводку
                cv2.polylines(frame, [pts], True, color, 2, cv2.LINE_AA)
                # Рисуем заливку на оверлее
                if overlay is not None:
                    cv2.fillPoly(overlay, [pts], color)
            else:
                x1, y1, x2, y2 = map(int, obj["bbox"])
                cv2.rectangle(frame, (x1, y1), (x2, y2), color, 2)

            # 2. Рисуем подпись (всегда по координатам bbox)
            if self.get_param("show_labels"):
                self._draw_label(frame, obj)

        # Применяем прозрачную заливку
        if overlay is not None:
            alpha = self.get_param("mask_opacity")
            cv2.addWeighted(overlay, alpha, frame, 1 - alpha, 0, frame)

    def _draw_label(self, frame, obj):
        x1, y1, x2, y2 = map(int, obj["bbox"])
        color = (0, 255, 127)
        label_text = obj["name"].upper()
        font = cv2.FONT_HERSHEY_DUPLEX
        scale, thick = 0.7, 1

        (tw, th), _ = cv2.getTextSize(label_text, font, scale, thick)
        cv2.rectangle(frame, (x1, y1 - th - 10), (x1 + tw + 4, y1), color, -1)
        cv2.putText(frame, label_text, (x1 + 2, y1 - 7), font, scale, (0, 0, 0), thick, cv2.LINE_AA)

    def _update_ranges(self, idx):
        # 1. Добавляем новый "микро-интервал"
        self._analyzed_ranges.append([idx, idx])

        # 2. Сортируем по началу (важно для правильной склейки)
        self._analyzed_ranges.sort(key=lambda x: x[0])

        # 3. Склеиваем накладывающиеся или идущие впритык
        merged = []
        if not self._analyzed_ranges:
            return

        curr_start, curr_end = self._analyzed_ranges[0]

        for i in range(1, len(self._analyzed_ranges)):
            next_start, next_end = self._analyzed_ranges[i]

            # Если интервалы пересекаются или идут подряд (допуск +1)
            if next_start <= curr_end + 1:
                # Расширяем текущий конец, если следующий интервал длиннее
                curr_end = max(curr_end, next_end)
            else:
                # Разрыв найден: сохраняем старый интервал и начинаем новый
                merged.append([curr_start, curr_end])
                curr_start, curr_end = next_start, next_end

        # Не забываем добавить последний интервал
        merged.append([curr_start, curr_end])
        self._analyzed_ranges = merged


    def _add_to_cache(self, idx, detections):
        # 1. Записываем сами данные

        self._memory_cache[idx] = detections

        # 3. Сохраняем (опционально)
        if  CASH_TO_FILE and len(self._memory_cache) % 100 == 0:
            self.save_cache()


    def __del__(self):
        # При удалении фильтра сохраняем накопленный кеш
        if CASH_TO_FILE and self._memory_cache:
            self.save_cache()