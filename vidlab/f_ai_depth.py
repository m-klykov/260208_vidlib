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
                "pos_x": 0.0,  # Центр по горизонтали
                "pos_y": 0.0,  # Центр по вертикали
                "alpha": 0.5,     # Прозрачность (0.0 - только видео, 1.0 - только глубина)
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
            "pos_x": {"type": "float", "min": -1, "max": 1, "default": 0},
            "pos_y": {"type": "float", "min": -1, "max": 1, "default": 0},
            "alpha": {"type": "float", "min": 0, "max": 1, "default": 0.5},
            "scale": {"type": "float", "min": 1.0, "max": 50.0, "default": 10.0},
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
                    device=device,
                    model_kwargs={"torch_dtype": torch.float16}  # Использовать половинную точность
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
        pipe = self._get_model()
        if pipe is None: return frame

        h, w = frame.shape[:2]

        # 1. Получаем карту глубины
        rgb_frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        pil_img = Image.fromarray(rgb_frame)
        with torch.inference_mode():
            result = pipe(pil_img)

        # 'depth' возвращает PIL изображение с картой глубин
        depth_map = np.array(result['predicted_depth']).astype(np.float32)

        # --- ЗАЩИТА ---
        # 1. Убираем лишние размерности (превращаем (1, H, W) в (H, W))
        if len(depth_map.shape) > 2:
            depth_map = np.squeeze(depth_map)

        # 2. Подготовка цветной карты глубины

        depth_rescaled = cv2.normalize(depth_map, None, 0, 255, cv2.NORM_MINMAX).astype(np.uint8)

        colormap = self.color_maps[self.get_param("colormap")]
        depth_colored = cv2.applyColorMap(depth_rescaled, colormap)

        # 3. Наложение (Transparency)
        # Формула: frame * (1 - alpha) + depth * alpha
        alpha = self.get_param("alpha")
        blended = cv2.addWeighted(frame, 1 - alpha, depth_colored, alpha, 0)

        # 4. Работа с точкой замера (pos_x, pos_y от -1 до 1)
        # Переводим [-1, 1] в координаты пикселей [0, w] и [0, h]
        pixel_x = int((self.get_param("pos_x") + 1) / 2 * (w - 1))
        pixel_y = int((self.get_param("pos_y") + 1) / 2 * (h - 1))

        # Ограничиваем, чтобы не вылететь за границы массива
        pixel_x = np.clip(pixel_x, 0, w - 1)
        pixel_y = np.clip(pixel_y, 0, h - 1)

        # Берем значение глубины в этой точке
        raw_val = depth_map[pixel_y, pixel_x]

        # 1. Параметры для калибровки (можно вынести в ползунки)
        # scale_factor подберем экспериментально (начни с 10.0)
        scale_factor = self.get_param("scale")
        shift = 0.01  # Защита от деления на 0

        # 2. Превращаем инвертированную глубину в линейную
        # Чем выше RawValue, тем меньше будет результат в "метрах"
        metric_depth = scale_factor / (depth_map + shift)

        dist_meters = metric_depth[pixel_y, pixel_x]

        # 5. Отрисовка прицела
        color = (0, 255, 0)  # Зеленый
        cv2.drawMarker(blended, (pixel_x, pixel_y), color, cv2.MARKER_CROSS, 20, 2)
        cv2.putText(blended, f"Val: {dist_meters:.2f}", (pixel_x + 10, pixel_y - 10),
                    cv2.FONT_HERSHEY_SIMPLEX, 2, color, 2)

        return blended

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

    def handle_mouse_press(self, pos, rect, event):
        if not rect.contains(pos): return

        w, h = rect.width(), rect.height()
        sx, sy = rect.left(), rect.top()

        # Переводим пиксели в диапазон [-1, 1]
        norm_x = (2.0 * (pos.x()-sx) / w) - 1.0
        norm_y = (2.0 * (pos.y()-sy) / h) - 1.0

        self.set_param("pos_x", max(-1.0, min(1.0,norm_x)))
        self.set_param("pos_y", max(-1.0, min(1.0, norm_y)))

        return True