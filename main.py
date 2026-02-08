import sys

from PySide6.QtGui import QFont
from PySide6.QtWidgets import QApplication
from vidlab.c_video import VideoController
from vidlab.v_main import MainView

def main():
    app = QApplication(sys.argv)

    # Создаем объект шрифта
    # "Segoe UI" хорошо подходит для Windows, 12 — размер
    app_font = QFont("Segoe UI", 11)

    # Устанавливаем шрифт для ВСЕГО приложения
    app.setFont(app_font)

    # Инициализация MVC
    controller = VideoController()
    view = MainView(controller)

    view.show()
    sys.exit(app.exec())

if __name__ == "__main__":
    main()