from PySide6.QtCore import QObject, Signal, QThread
from .f_base import FilterBase
import traceback
import json
import os

class FilterAsincWorker(QObject):
    # Передаем словарь с данными (марки, области и т.д.)
    progress = Signal(dict)
    finished = Signal()
    error = Signal(str)

    def __init__(self, filter_obj):
        super().__init__()
        self.filter_obj = filter_obj
        self.is_running = True # Тот самый флаг-прерыватель


    def run(self):
        try:
            # Вызываем "тяжелую" функцию фильтра, передавая ссылку на воркера
            # чтобы функция могла проверять self.is_running
            self.filter_obj.run_internal_logic(self)
        except Exception as e:
            self.error.emit(f"{str(e)}\n{traceback.format_exc()}")
        finally:
            self.finished.emit()


class FilterAsyncBase(FilterBase):
    def __init__(self, num, cache_dir, params=None):
        super().__init__(num, cache_dir, params)
        self.video_path = None
        self.is_analyzing = False
        self.progress = 0

        self._thread = None
        self._worker = None

        # Временные списки для работы в памяти (не сериализуются автоматически)
        self._analyzed_ranges = []
        self._detected_scenes = []

    def get_data_filepath(self):
        """Формирует путь к файлу кеша на основе ID фильтра"""
        return os.path.join(self.cache_dir, f"{self.get_id()}.json")

    def save_data(self):
        """Сохраняет результаты анализа в файл кеша"""
        if not self.cache_dir:
            print(f"Warning: cache_dir not set for {self.name}")
            return

            # 2. Создаем папку, если её еще не существует
        try:
            os.makedirs(self.cache_dir, exist_ok=True)
        except Exception as e:
            print(f"Error creating cache directory {self.cache_dir}: {e}")
            return

        data = {
            "ranges": self._analyzed_ranges,
            "marks": self._detected_scenes
        }
        try:
            with open(self.get_data_filepath(), 'w') as f:
                json.dump(data, f)
        except Exception as e:
            print(f"Error saving cache for {self.name}: {e}")

    def load_data(self):
        """Загружает результаты анализа из файла кеша"""
        path = self.get_data_filepath()
        if os.path.exists(path):
            try:
                with open(path, 'r') as f:
                    data = json.load(f)
                    self._analyzed_ranges = data.get("ranges", [])
                    self._detected_scenes = data.get("marks", [])
            except Exception as e:
                print(f"Error loading cache for {self.name}: {e}")

    def start_analysis(self):
        """Запуск фонового процесса"""
        if self.is_analyzing or not self.video_path:
            return

        self.is_analyzing = True
        self.progress = 0

        # Создаем поток и воркер
        self._thread = QThread()
        self._worker = FilterAsincWorker(self)
        self._worker.moveToThread(self._thread)

        # Связываем сигналы
        self._thread.started.connect(self._worker.run)
        self._worker.progress.connect(self._on_worker_progress)
        self._worker.error.connect(self._on_worker_error)

        # Правильное завершение
        self._worker.finished.connect(self._thread.quit)
        self._thread.finished.connect(self._on_analysis_finished)

        self._thread.start()

    def stop_analysis(self):
        """Принудительная остановка"""
        if self._worker:
            self._worker.is_running = False
        if self._thread:
            self._thread.quit()
            self._thread.wait()  # Ждем реальной остановки

    def get_timeline_data(self):
        """Переопределяем, чтобы отдавать данные не из params, а из внутренних списков"""
        return {
            "ranges": self._analyzed_ranges,
            "marks": self._detected_scenes
        }

    def _on_worker_progress(self, data):
        """Обновление данных из потока (выполняется в UI-потоке)"""
        # Мы используем наши новые сеттеры/геттеры
        if "progress" in data:
            self.progress = data["progress"]

        if "ranges" in data:
            self._analyzed_ranges = data["ranges"]

        if "marks" in data:
            self._detected_scenes = data["marks"]

        self.save_data()

    def _on_worker_error(self, err_msg):
        print(f"Filter Analysis Error [{self.name}]: {err_msg}")
        self.is_analyzing = False

    def _on_analysis_finished(self):
        self.is_analyzing = False
        self._thread = None
        self._worker = None
        print(f"Analysis for {self.name} finished.")

    def run_internal_logic(self, worker):
        """Метод должен быть переопределен в конкретном фильтре"""
        raise NotImplementedError("Subclasses must implement run_internal_logic")

    def __del__(self):
        # Если объект удаляется, жестко гасим поток
        self.stop_analysis()