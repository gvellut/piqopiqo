from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import QMainWindow, QVBoxLayout, QWidget

from piqopiqo.gui.grid import PhotoGrid
from piqopiqo.gui.items import PhotoDelegate, PhotoModel
from piqopiqo.thumb_man import ThumbnailManager


class MainWindow(QMainWindow):
    def __init__(self, images):
        super().__init__()
        self.setWindowTitle("PiqoPiqo")
        self.resize(1200, 800)

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
