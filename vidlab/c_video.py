import os

from PySide6.QtCore import QObject, QTimer, Signal, QUrl
from PySide6.QtGui import QDesktopServices, Qt

from .m_project import VideoProjectModel
from .m_project_ext import VideoProjectExtModel
from .m_video import VideoModel
from .m_video_export import VideoExport

class VideoController(QObject):
    video_loaded = Signal()  # Сигнал без параметров, так как View сама возьмет данные из модели
    scenes_updated = Signal(list) # сигнал для обновления виджета сцен
    filters_updated = Signal() # изменились фильтры
    frame_updated = Signal(object) # Передает кадр для отрисовки
    position_changed = Signal(int) # Передает текущий индекс кадра
    playing_changed = Signal(bool)  # True если играет, False если пауза
    cropped_mode_changed = Signal(bool)  # Сигнал для обновления UI
    filter_params_changed = Signal() # параметры филльтра изменены мышкой в видео окне

    def __init__(self):
        super().__init__()
        self.model = VideoModel()
        self.project = VideoProjectExtModel()  # Модель для JSON

        self.timer = QTimer()
        self.timer.timeout.connect(self._play_step)
        self._is_playing = False
        self.cropped_mode = False

    @property
    def is_playing(self):
        return self._is_playing

    def set_cropped_mode(self, enabled):
        if self.cropped_mode == enabled: return

        self.cropped_mode = enabled

        # Если включили режим, а мы вне диапазона — прыгаем в начало
        if enabled:
            in_f = self.get_in_index()
            out_f = self.get_out_index()

            if self.model.current_idx < in_f or self.model.current_idx > out_f:
                self.seek(in_f)

        self.cropped_mode_changed.emit(enabled)
        # Обновляем список и слайдер
        self.scenes_updated.emit(self.project.scenes)

    def load_video(self, path):
        print(f"c: open {path}")

        if self.model.open_video(path):
            self.stop()  # Сброс состояния
            self.seek(self.model.get_min_index())
            self.video_loaded.emit()  # Уведомляем всех подписанных

            # Загружаем сцены из JSON при открытии видео
            scenes = self.project.load_project(path)
            self.scenes_updated.emit(scenes)  # Сообщаем View, что сцены загружены
            self.filters_updated.emit()

            return True
        return False

    def toggle_play(self):
        if self._is_playing:
            self.stop()
        else:
            if self.model.cap:
                self._is_playing = True
                self.timer.start(int(1000 / self.model.fps))
                self.playing_changed.emit(True)

    def stop(self):
        self._is_playing = False
        self.timer.stop()
        self.playing_changed.emit(False)

    # Пример логики в контроллере/плеере
    def get_processed_frame(self, raw_frame, frame_idx):
        processed = raw_frame.copy()
        # Прогоняем через все включенные фильтры в порядке их следования в списке
        for f in self.project.filters:
            if f.enabled and f.is_active_at(frame_idx):
                f.set_current_frame(frame_idx)  # УВЕДОМЛЯЕМ ФИЛЬТР О КАДРЕ
                processed = f.process(processed, frame_idx)
        return processed

    def _process_and_out_frame(self,frame):
        if frame is not None:
            frame_idx = self.model.get_current_index()
            frame = self.get_processed_frame(frame, frame_idx)
            self.frame_updated.emit(frame)
            self.position_changed.emit(frame_idx)
            self.filter_params_changed.emit()

    def _play_step(self):
        frame = self.model.get_frame()
        if frame is not None:
            self._process_and_out_frame(frame)
        else:
            self.stop()

    def refresh_current_frame(self):
        frame = self.model.last_frame
        if frame is not None:
            self._process_and_out_frame(frame)


    def seek(self, position):
        self.stop() # Останавливаем при перемотке

        if self.cropped_mode:
            in_f = self.get_in_index()
            out_f = self.get_out_index()
            position = max(in_f, min(position, out_f))

        frame = self.model.get_frame(position)
        if frame is not None:
            self._process_and_out_frame(frame)

    def draw_filters_overlay(self, painter, viewport_rect):
        # Ищем фильтр, который сейчас выбран (в фокусе)
        for f in self.project.filters:
            if f.focused:
                # Передаем управление фильтру
                f.render_overlay(painter, self.model.get_current_index(), viewport_rect)
                break

    def get_active_range(self):
        """Возвращает границы, которые сейчас отображаются на таймлайне"""
        if self.cropped_mode:
            # В режиме обрезки - только рабочий участок
            return self.get_in_index(), self.get_out_index()
        else:
            # В обычном режиме - всё видео целиком
            return self.model.get_min_index(), self.model.get_max_index()

    def get_active_filter_timeline_data(self):
        """Просто возвращает данные для отрисовки от сфокусированного фильтра"""
        for f in self.project.filters:
            if f.focused:
                data = f.get_timeline_data()
                return data

        return {"marks": [], "ranges": [], "act_in": -1, "act_out": -1}

    def get_active_marks(self):
        """отсортированные времена маркеров пользователя и ефекта"""
        all_points = set()

        all_points.update(self.project.get_all_marks())

        filter_data = self.get_active_filter_timeline_data()

        all_points.update(filter_data["marks"])

        act_in = filter_data.get("act_in",-1)
        act_out = filter_data.get("act_out",-1)
        if act_in >= 0:
            all_points.update([act_in, act_out])


        sorted_points = sorted(list(all_points))

        return sorted_points

    def handle_mouse_move(self, pos, target_rect):
        # Ищем фильтр, который сейчас выбран (в фокусе)
        for f in self.project.filters:
            if f.focused:
                # Передаем управление фильтру
                curs, params_changes = f.handle_mouse_move(pos, target_rect)

                if params_changes:
                    self.refresh_current_frame()
                    self.filter_params_changed.emit()

                return curs

        return Qt.ArrowCursor

    def handle_mouse_press(self, pos, rect):
        # Ищем фильтр, который сейчас выбран (в фокусе)
        for f in self.project.filters:
            if f.focused:
                # Передаем управление фильтру
                f.handle_mouse_press(pos, rect)
                break

    def handle_mouse_release(self):
        # Ищем фильтр, который сейчас выбран (в фокусе)
        for f in self.project.filters:
            if f.focused:
                # Передаем управление фильтру
                f.handle_mouse_release()
                break


    def step_forward(self):
        self.stop()
        curr = self.model.get_current_index()
        self.seek(curr + 1)

    def step_backward(self):
        self.stop()
        curr = self.model.get_current_index()
        self.seek(max(0, curr - 2)) # -2 т.к. после чтения индекс уже смещен вперед

    def to_start(self):
        self.seek(self.model.get_min_index())

    def to_end(self):
        self.seek(self.model.get_max_index()-1)

    def get_in_index(self):
        return self.project.get_in_frame(self.model.get_min_index())

    def get_out_index(self):
        return self.project.get_out_frame(self.model.get_max_index())


    def to_in_point(self):
        self.seek(self.get_in_index())

    def to_out_point(self):
        self.seek(self.get_out_index())

    def to_next_marker(self):
        """Переход к ближайшему маркеру справа от плейхеда"""
        curr_frame = self.model.get_current_index()
        marks = self.get_active_marks()

        # Ищем первый маркер, который строго больше текущего кадра
        for m in marks:
            if m > curr_frame:
                self.seek(m)
                return

        # Если ничего не нашли (мы в самом конце), можно прыгнуть на Out-point или последний кадр
        # self.seek(self.get_out_index())

    def to_prev_marker(self):
        """Переход к ближайшему маркеру слева от плейхеда"""
        curr_frame = self.model.get_current_index()
        marks = self.get_active_marks()

        # Ищем маркеры в обратном порядке и берем первый, который меньше текущего
        for m in reversed(marks):
            if m < curr_frame:
                self.seek(m)
                return

        # Если ничего не нашли (мы в самом начале), прыгаем на In-point
        # self.seek(self.get_in_index())

    def add_current_scene(self):
        idx = self.model.current_idx
        self.project.add_scene(idx)
        self.scenes_updated.emit(self.project.scenes)

    def delete_scene(self, frame_idx):
        self.project.remove_scene(frame_idx)
        self.scenes_updated.emit(self.project.scenes)

    def rename_scene(self, frame_idx, full_text):
        # Извлекаем текст после последней закрывающей скобки
        # Строка: "00:00:01 [100] Моя сцена" -> "Моя сцена"
        if "]" in full_text:
            new_title = full_text.split("]")[-1].strip()
        else:
            new_title = full_text.strip()

        self.project.update_scene_title(frame_idx, new_title)
        self.scenes_updated.emit(self.project.scenes)

    def relocate_scene(self, old_frame_idx):
        new_idx = self.model.current_idx

        if self.project.update_scene_frame(old_frame_idx, new_idx):
            self.scenes_updated.emit(self.project.scenes)
            return True

        return False

    def add_special_mark(self, m_type):
        idx = self.model.current_idx
        # Модель сама разберется с удалением дубликатов типа
        self.project.add_special_mark(idx, m_type)
        self.scenes_updated.emit(self.project.scenes)

    def make_screenshot(self):
        if not self.model.file_path:
            return

        # Получаем директорию, имя файла без расширения и номер кадра
        dir_path = os.path.dirname(self.model.file_path)
        base_name = os.path.splitext(os.path.basename(self.model.file_path))[0]
        frame_idx = self.model.current_idx

        # Формируем путь: "путь/имя_кадр.png"
        filename = f"{base_name}_{frame_idx}.png"
        full_path = os.path.join(dir_path, filename)

        if self.model.save_screenshot(full_path):
            print(f"Скриншот сохранен: {full_path}")
            # Можно отправить сигнал для уведомления в статус-баре
            # self.status_message.emit(f"Сохранено: {filename}")
            return full_path
        else:
            print("Ошибка сохранения скриншота")
            return ''

    def open_video_folder(self):
        """Открывает папку, в которой лежит текущее видео"""
        if not self.model.file_path:
            return

        folder = os.path.dirname(self.model.file_path)
        # Кроссплатформенный способ открыть папку в проводнике
        QDesktopServices.openUrl(QUrl.fromLocalFile(folder))

    def export_video(self, output_path, progress_callback=None):
        """
        Метод экспорта видео в диапазоне In/Out.
        progress_callback: функция, принимающая (int) процента,
        возвращающая True для продолжения и False для отмены.
        """
        if not self.model.cap:
            return False

        # 1. Определяем диапазон и параметры
        start_frame = self.get_in_index()
        end_frame = self.get_out_index()
        total_to_export = end_frame - start_frame + 1

        if total_to_export <= 0:
            return False

        # 2. Определяем размер кадра (берем эталонный обработанный кадр)
        # Это важно, так как фильтр Resize мог изменить разрешение оригинала
        raw_sample = self.model.get_frame(start_frame)
        if raw_sample is None: return False

        curr_idx = self.model.get_current_index()

        processed_sample = self.get_processed_frame(raw_sample, start_frame)
        h, w = processed_sample.shape[:2]

        # 3. Инициализируем экспортер
        exporter = VideoExport(
            output_path=output_path,
            fps=self.model.fps,
            size=(w, h)
        )

        self.stop()  # Останавливаем предпросмотр на время экспорта

        try:
            for i in range(total_to_export):
                curr_idx = start_frame + i

                # Читаем кадр напрямую из модели
                frame = self.model.get_frame(curr_idx)
                if frame is None:
                    break

                # Применяем фильтры
                processed = self.get_processed_frame(frame, curr_idx)

                # Записываем
                exporter.write_frame(processed)

                # 4. Обработка прогресса и отмены
                if progress_callback and (i % 20 == 0 or i == total_to_export-1):
                    percent = int((i + 1) / total_to_export * 100)
                    # Если коллбек вернул False — прерываемся
                    if not progress_callback(percent):
                        exporter.cancel()
                        return False

            exporter.finish()
            return True

        except Exception as e:
            print(f"Export Error: {e}")
            exporter.cancel()
            return False
        finally:
            # Возвращаем плеер на место In-point после завершения
            self.seek(curr_idx)

