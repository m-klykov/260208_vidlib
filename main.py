import sys
from PySide6.QtWidgets import QApplication
from vidlab.c_video import VideoController
from vidlab.v_main import MainView

def main():
    app = QApplication(sys.argv)

    # Инициализация MVC
    controller = VideoController()
    view = MainView(controller)

    view.show()
    sys.exit(app.exec())

if __name__ == "__main__":
    main()