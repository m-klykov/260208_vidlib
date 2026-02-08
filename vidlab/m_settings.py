from PySide6.QtCore import QSettings

# это ключи в реестре/файле настроек
SETT_ORG = "m.klykov"
SETT_APP = "260208_vidlib"

class SettingsModel:

    _instance = None

    def __init__(self):
        self.settings = QSettings(SETT_ORG, SETT_APP)
        self.max_recent_files = 10

    @classmethod
    def get_instance(cls):
        if cls._instance is None:
            cls._instance = cls()

        return cls._instance

    def get_recent_files(self):
        return self.settings.value("recent_files", [])

    def add_recent_file(self, file_path):
        files = self.get_recent_files()
        if file_path in files:
            files.remove(file_path)

        files.insert(0, file_path)
        files = files[:self.max_recent_files]
        self.settings.setValue("recent_files", files)

    def save_geometry(self, geometry, state):
        self.settings.setValue("geometry", geometry)
        self.settings.setValue("window_state", state)

    def load_geometry(self):
        return (self.settings.value("geometry"),
                self.settings.value("window_state"))