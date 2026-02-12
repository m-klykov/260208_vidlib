import cv2
import os
import json

import torch
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
                "use_cache": False
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

            # Проверяем доступность CUDA (NVIDIA GPU)
            if torch.cuda.is_available():
                self._model.to('cuda')
                print("AI Detector: Using GPU (CUDA)")
            else:
                print("AI Detector: GPU not found, using CPU")

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

            # ВАЖНО: Определяем устройство один раз
            device = 'cuda' if torch.cuda.is_available() else 'cpu'

            # ОПТИМИЗИРОВАННЫЙ ВЫЗОВ
            results = model.predict(
                frame,
                device=device,
                conf=self.get_param("conf"),
                half=(device == 'cuda'),  # Ускоряет GPU в 2 раза
                imgsz=320,  # Уменьшаем внутреннее разрешение нейросети (стандарт 640)
                max_det=20,  # Ограничиваем кол-во объектов для скорости
                verbose=False
            )

            if results and len(results[0].boxes) > 0:
                res = results[0].cpu() # Переносим результат обратно на CPU для отрисовки
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
                    self._add_to_cache(idx, detections)

                self._update_ranges(idx)


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

    def _update_ranges(self, idx):

        if not self._analyzed_ranges:
            self._analyzed_ranges.append([idx, idx])
            return

        # 2. Обновляем диапазоны
        new_ranges = []
        prev_range = None
        use_idx = False

        for range in self._analyzed_ranges:
            if range[1]+1 < idx:
                # блоки до нас
                new_ranges.append(range)
            elif range[1]+1 == idx:
                # добавляемся к блоку в конец
                prev_range = [range[0],idx]
                use_idx = True
            elif idx+1 == range[0]:
                # мы пишемся в начале блока
                if prev_range:
                    #склеили два блока
                    new_ranges.append([prev_range[0],range[1]])
                    prev_range = None

                else:
                    # расширяем в качале
                    new_ranges.append([idx, range[1]])
                use_idx = True
            else:
                if prev_range:
                    #пишем прошлую запись с idx в конце
                    new_ranges.append(prev_range)
                    prev_range = None

                if not use_idx and idx+1 < range[0]:
                    # все элементы с этого после нас, вписыавем себя отним кадром
                    new_ranges.append([idx, idx])
                    use_idx = True

                # элементы посте нас
                new_ranges.append(range)

        if prev_range:
            #пишем прошлую запись с idx в конце
            new_ranges.append(prev_range)
        elif not use_idx:
            new_ranges.append([idx, idx])

        self._analyzed_ranges = new_ranges


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