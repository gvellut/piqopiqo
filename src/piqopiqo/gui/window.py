from PySide6.QtGui import QAction, QPixmap
from PySide6.QtWidgets import QMainWindow, QVBoxLayout, QWidget

from piqopiqo.config import Config
from piqopiqo.gui.grid import PhotoGrid
from piqopiqo.gui.items import PhotoDelegate, PhotoModel
from piqopiqo.thumb_man import ThumbnailManager


class MainWindow(QMainWindow):
    def __init__(self, images):
        super().__init__()
        self.setWindowTitle(Config.APP_NAME)
        self.showMaximized()

        # Menu Bar
        self._create_menu_bar()

        # Central Widget and Layout
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        layout = QVBoxLayout(central_widget)

        # Model
        self.model = PhotoModel(images)

        # View
        self.grid = PhotoGrid()
        self.grid.setModel(self.model)
        layout.addWidget(self.grid)

        # Delegate
        self.delegate = PhotoDelegate()
        self.grid.setItemDelegate(self.delegate)

        # Thumbnail Manager
        self.thumb_manager = ThumbnailManager()
        self.thumb_manager.thumb_ready.connect(self.on_thumb_ready)

        # Connect grid's request signal
        self.grid.request_thumb = self.request_thumb_handler

    def _create_menu_bar(self):
        menubar = self.menuBar()

        # 1. Create the File Menu
        file_menu = menubar.addMenu("File")

        # 2. Define Actions
        # PREFERENCES (Will automatically move to App Menu on macOS)
        settings_action = QAction("Settings...", self)
        settings_action.setMenuRole(QAction.MenuRole.PreferencesRole)
        settings_action.triggered.connect(self.on_settings)
        file_menu.addAction(settings_action)

        # QUIT (Will automatically move to App Menu on macOS)
        quit_action = QAction(f"Quit {Config.APP_NAME}", self)
        quit_action.setMenuRole(QAction.MenuRole.QuitRole)
        quit_action.setShortcut("Ctrl+Q")
        quit_action.triggered.connect(self.close)
        file_menu.addAction(quit_action)

        # ABOUT (Will automatically move to App Menu on macOS)
        # Usually placed in a 'Help' menu for Windows/Linux compatibility
        help_menu = menubar.addMenu("Help")

        about_action = QAction(f"About {Config.APP_NAME}", self)
        about_action.setMenuRole(QAction.MenuRole.AboutRole)
        about_action.triggered.connect(self.on_about)
        help_menu.addAction(about_action)

        # 3. Standard File Actions (Will stay in File Menu)
        open_action = QAction("Open...", self)
        open_action.setShortcut("Ctrl+O")
        open_action.triggered.connect(self.on_open)
        file_menu.addAction(open_action)

    def on_about(self):
        # TODO: Implement About dialog
        pass

    def on_settings(self):
        # TODO: Implement Settings dialog
        pass

    def on_open(self):
        # TODO: Implement Open folder dialog
        pass

    def on_thumb_ready(self, file_path, thumb_type, cache_path):
        # Find index for file_path
        for i, item in enumerate(self.model.items):
            if item["path"] == file_path:
                index = self.model.index(i)
                if index.isValid():
                    pixmap = QPixmap(cache_path)
                    state = 1 if thumb_type == "embedded" else 2
                    self.model.update_thumbnail(index, pixmap, state)
                break

    def request_thumb_handler(self, index):
        file_path = self.model.data(index, PhotoModel.Role_Path)
        self.thumb_manager.queue_image(file_path)

    def closeEvent(self, event):
        self.thumb_manager.stop()
        super().closeEvent(event)
