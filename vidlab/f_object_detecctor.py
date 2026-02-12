import cv2
import os
import json
from ultralytics import YOLO
from .f_base import FilterBase

CASH_TO_FILE = False # сохраняем ли кеш на диск

class FilterObjectDetector(FilterBase):
    def __init__(self, num, cache_dir, params=None):
        # Настройки по умолчанию
        if not params:
            params = {
                "conf": 0.25,
                "show_labels": True,
                "use_cache": True
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
            "use_cache": {"type": "bool", "default": True}
        }

    def _get_model(self):
        """Ленивая инициализация модели YOLO"""
        if self._model is None:
            # При первом вызове скачает yolov8n.pt (около 6 МБ)
            # Указываем относительный или абсолютный путь.
            # Если файла там нет, YOLO скачает его именно туда.
            model_path = os.path.join(os.getcwd(), 'models', 'yolov8n.pt')
            self._model = YOLO(model_path)
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
        # Если фильтр не в фокусе — пропускаем обработку (Overlay mode)
        if not self.focused:
            return frame

        detections = None
        use_cache = self.get_param("use_cache")

        # 1. Пытаемся взять из кеша
        if use_cache and idx in self._memory_cache:
            detections = self._memory_cache[idx]
        else:
            # 2. Вызываем нейросеть
            model = self._get_model()
            results = model(frame, conf=self.get_param("conf"), verbose=False)

            if results and len(results[0].boxes) > 0:
                res = results[0]
                detections = []
                for box in res.boxes:
                    # Сохраняем только самое нужное
                    detections.append({
                        "bbox": box.xyxy[0].tolist(),  # [x1, y1, x2, y2]
                        "conf": float(box.conf[0]),
                        "cls": int(box.cls[0]),
                        "name": res.names[int(box.cls[0])]
                    })

                if use_cache:
                    self._memory_cache[idx] = detections
                    # Сохраняем на диск каждые 100 новых найденных кадров (опционально)
                    if CASH_TO_FILE and len(self._memory_cache) % 100 == 0:
                        self.save_cache()

        # 3. Отрисовка результатов
        if detections:
            for obj in detections:
                x1, y1, x2, y2 = map(int, obj["bbox"])

                # Рисуем стильную рамку
                color = (0, 255, 127)  # Ярко-зеленый
                cv2.rectangle(frame, (x1, y1), (x2, y2), color, 2)

                if self.get_param("show_labels"):
                    label_text = f"{obj['name']}" #  {obj['conf']:.2f}
                    # Параметры шрифта
                    font = cv2.FONT_HERSHEY_DUPLEX  # Более плотный шрифт
                    font_scale = 1
                    thickness = 2

                    # Считаем размер текста для подложки
                    (tw, th), baseline = cv2.getTextSize(label_text, font, font_scale, thickness)

                    # Рисуем заполненный прямоугольник (фон бирки)
                    # Делаем его чуть шире текста для отступов
                    cv2.rectangle(frame,
                                  (x1, y1 - th - 10),
                                  (x1 + tw + 4, y1),
                                  color, -1)  # -1 заполнит фигуру цветом

                    # Пишем текст черным цветом поверх зеленой плашки
                    cv2.putText(frame, label_text, (x1 + 2, y1 - 7),
                                font, font_scale, (0, 0, 0), thickness, cv2.LINE_AA)
        return frame

    def __del__(self):
        # При удалении фильтра сохраняем накопленный кеш
        if CASH_TO_FILE and self._memory_cache:
            self.save_cache()