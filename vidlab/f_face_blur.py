import cv2
import os
import torch
import numpy as np
from ultralytics import YOLO
from .f_asinc_base import FilterAsyncBase


class FilterFaceBlur(FilterAsyncBase):
    def __init__(self, num, cache_dir, params=None):
        if not params:
            params = {
                "conf": 0.3,
                "blur_size": 30,
                "pixelate": False,
                "ellipse": True
            }
        super().__init__(num, cache_dir, params)
        self.name = "AI Face Blur"
        self._model = None

        # Хранилище для сглаживания: { id: {'box': [x1,y1,x2,y2], 'lost_count': 0} }
        self._face_memory = {}
        self._max_lost_frames = 5  # Сколько кадров "держать" маску после исчезновения

    def get_params_metadata(self):
        return {
            "conf": {"type": "float", "min": 0.1, "max": 1.0, "default": 0.3},
            "blur_size": {"type": "int", "min": 1, "max": 150, "default": 30},
            "pixelate": {"type": "bool", "default": False},
            "ellipse": {"type": "bool", "default": True}
        }

    def _get_model(self):
        if self._model is None:
            # Можно использовать yolov8n-face.pt (нужно скачать в папку models)
            model_path = os.path.join(os.getcwd(), 'models', 'yolov8n-face.pt')
            self._model = YOLO(model_path)

            if torch.cuda.is_available():
                self._model.to('cuda')
                print("use cuda")
        return self._model

    def process(self, frame, idx):
        model = self._get_model()
        device = 'cuda' if torch.cuda.is_available() else 'cpu'

        current_boxes = []
        # 1. Быстрый поиск лиц
        results = model.predict( #predict track
            frame,
            device=device,
            # persist=True,
            conf=self.get_param("conf"),
            half=(device == 'cuda'),
            # imgsz=320,  # Уменьшаем размер для скорости
            verbose=False,
            max_det=50
        )

        if results and len(results[0]) > 0:
            res = results[0].cpu()

            for box in res.boxes:
                # Берем ID трекера, если есть, иначе просто индекс
                track_id = int(box.id[0]) if box.id is not None else len(current_boxes)
                coords = box.xyxy[0].tolist()
                current_boxes.append((track_id, coords))

        # Обновляем память
        # 1. Помечаем все старые лица как "потерянные" на +1 кадр
        for f_id in self._face_memory:
            self._face_memory[f_id]['lost_count'] += 1

        # 2. Записываем/обновляем те, что нашли сейчас
        for t_id, coords in current_boxes:
            self._face_memory[t_id] = {
                'box': coords,
                'lost_count': 0
            }

        # 3. Удаляем тех, кто потерялся слишком давно
        self._face_memory = {k: v for k, v in self._face_memory.items()
                             if v['lost_count'] < self._max_lost_frames}

        # Параметры размытия
        ksize = self.get_param("blur_size")
        if ksize % 2 == 0: ksize += 1
        use_pixelate = self.get_param("pixelate")
        use_ellipse = self.get_param("ellipse")

        # 4. Рендерим размытие для всех лиц из памяти
        h_img, w_img = frame.shape[:2]
        for f_id, data in self._face_memory.items():
            x1, y1, x2, y2 = map(int, data['box'])

            # Ограничиваем координаты границами кадра
            x1, y1 = max(0, x1), max(0, y1)
            x2, y2 = min(w_img, x2), min(h_img, y2)

            w, h = x2 - x1, y2 - y1
            if w <= 0 or h <= 0: continue

            # Извлекаем ROI (область лица)
            face_roi = frame[y1:y2, x1:x2]

            # 2. Применяем эффект
            if use_pixelate:
                # Пикселизация
                pw, ph = max(1, w // 15), max(1, h // 15)
                tmp = cv2.resize(face_roi, (pw, ph), interpolation=cv2.INTER_NEAREST)
                blurred = cv2.resize(tmp, (w, h), interpolation=cv2.INTER_NEAREST)
            else:
                # Размытие по Гауссу
                blurred = cv2.GaussianBlur(face_roi, (ksize, ksize), 0)

            # 3. Накладываем обратно
            if use_ellipse:
                # Создаем эллиптическую маску для мягких краев
                mask = np.zeros((h, w), dtype=np.uint8)
                cv2.ellipse(mask, (w // 2, h // 2), (w // 2, h // 2), 0, 0, 360, 255, -1)
                mask_inv = cv2.bitwise_not(mask)

                bg = cv2.bitwise_and(face_roi, face_roi, mask=mask_inv)
                fg = cv2.bitwise_and(blurred, blurred, mask=mask)
                frame[y1:y2, x1:x2] = cv2.add(bg, fg)
            else:
                frame[y1:y2, x1:x2] = blurred

        # Обновляем прогресс-бар на таймлайне (опционально)
        self._update_ranges(idx)
        return frame

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

    def run_internal_logic(self, worker):
        """Асинхронный скан только для визуализации 'где есть лица'"""
        cap = cv2.VideoCapture(self.video_path)
        total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        model = self._get_model()
        device = 'cuda' if torch.cuda.is_available() else 'cpu'

        frames_with_faces = []
        for f_idx in range(total_frames):
            if not worker.is_running: break

            ret, frame = cap.read()
            if not ret: break

            # Сканируем каждый 3-й кадр для скорости (этого хватит для таймлайна)
            if f_idx % 3 == 0:
                results = model.predict(frame, device=device, conf=self.get_param("conf"),
                                        imgsz=256, half=True, verbose=False)
                if results and len(results[0]) > 0:
                    frames_with_faces.append(f_idx)

            if f_idx % 100 == 0:
                worker.progress.emit({
                    "progress": int(f_idx / total_frames * 100),
                    "ranges": self._quick_merge(frames_with_faces)
                })

        cap.release()
        worker.progress.emit({"progress": 100, "ranges": self._quick_merge(frames_with_faces)})

    def _quick_merge(self, indices):
        if not indices: return []
        res, start, prev = [], indices[0], indices[0]
        gap = 10  # Допуск в 10 кадров для сплошной линии на таймлайне
        for curr in indices[1:]:
            if curr <= prev + gap:
                prev = curr
            else:
                res.append([start, prev])
                start = curr
                prev = curr
        res.append([start, prev])
        return res