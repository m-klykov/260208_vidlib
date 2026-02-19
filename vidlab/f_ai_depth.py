from transformers import pipeline
from PIL import Image
import cv2
import os
import numpy as np
import torch
from ultralytics import YOLO
from .f_asinc_base import FilterAsyncBase


class FilterAiDepth(FilterAsyncBase):
    def __init__(self, num, cache_dir, params=None):
        if not params:
            params = {
                "conf": 0.25,
                "colormap": "MAGMA", # MAGMA дает красивый переход от черного к желтому
                "max_depth": 50.0  # Максимальная дистанция для нормализации (в метрах)
            }
        super().__init__(num, cache_dir, params)
        self.name = "AI Depth Visualizer"
        self._model = None
        self._pipe = None

        self.color_maps = {
            "MAGMA" : cv2.COLORMAP_MAGMA
        }

    def get_params_metadata(self):
        return {
            "conf": {"type": "float", "min": 0.1, "max": 1.0, "default": 0.25},
            "max_depth": {"type": "float", "min": 1.0, "max": 200.0, "default": 50.0},
            "colormap": {"type": "list", "values": ["MAGMA"], "default": "MAGMA"}
        }

    def _get_model(self):
        if self._pipe is None:
            # Выбираем девайс (0 для CUDA)
            device = 0 if torch.cuda.is_available() else -1

            local_model_path = os.path.join(os.getcwd(), 'models', 'depth_v2_local')

            print(f"Loading Depth Model from: {local_model_path}")


            try:
                self._pipe = pipeline(
                    task="depth-estimation",
                    model=local_model_path,  # Теперь здесь ПУТЬ, а не ID
                    device=device
                )

                # self._pipe = pipeline(
                #     task="depth-estimation",
                #     model="depth-anything/Depth-Anything-V2-Small-hf",
                #     device=device
                # )
                print("Depth Anything V2 loaded successfully via Transformers")
            except Exception as e:
                print(f"Failed to load depth model: {e}")
        return self._pipe

    def process(self, frame, idx):
        pipe = self._get_model()
        if pipe is None: return frame

        # Превращаем OpenCV (BGR) в PIL Image (RGB)
        color_frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        pil_img = Image.fromarray(color_frame)

        # Инференс
        result = pipe(pil_img)

        # 'depth' возвращает PIL изображение с картой глубин
        depth_map = np.array(result['predicted_depth'])

        # Нормализация для визуализации
        depth_min = depth_map.min()
        depth_max = depth_map.max()
        depth_norm = (depth_map - depth_min) / (depth_max - depth_min)
        depth_rescaled = (depth_norm * 255).astype(np.uint8)

        # Применяем Magma или Infermo
        color_depth = cv2.applyColorMap(depth_rescaled, cv2.COLORMAP_MAGMA)

        # Возвращаем размер к исходному (если pipeline его изменил)
        if color_depth.shape[:2] != frame.shape[:2]:
            color_depth = cv2.resize(color_depth, (frame.shape[1], frame.shape[0]))

        return color_depth

    def _colorize_depth(self, depth_map):
        # Ограничиваем глубину сверху для лучшего контраста
        max_d = self.get_param("max_depth")
        depth_norm = np.clip(depth_map, 0, max_d) / max_d

        # Инвертируем: ближе — ярче (белее), дальше — темнее
        # Или оставляем как есть для колормапа
        depth_rescaled = (depth_norm * 255).astype(np.uint8)

        # Применяем цветовую схему для наглядности
        # COLORMAP_MAGMA: Близко (белый/желтый), Далеко (фиолетовый/черный)
        colormap = self.color_maps[self.get_param("colormap")]
        color_depth = cv2.applyColorMap(depth_rescaled, colormap)

        # Опционально: можно наложить оригинальный кадр прозрачным слоем
        # return cv2.addWeighted(frame, 0.3, color_depth, 0.7, 0)

        return color_depth