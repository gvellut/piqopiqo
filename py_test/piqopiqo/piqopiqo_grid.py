from collections import namedtuple
import logging
import math
import os
import sys

import click
from PySide6 import QtCore, QtWidgets
from PySide6.QtCore import QAbstractTableModel, QPoint, QSize, Qt
from PySide6.QtGui import QImage, QPixmap
import PySide6.QtWidgets as qw

DIR_PATH = "/Volumes/CrucialX8/__test/piqopiqo"

# Create a custom namedtuple class to hold our data.
preview = namedtuple("preview", "id title image")

NUMBER_OF_COLUMNS = 4
CELL_PADDING = 20  # all sides

IMAGE_SIZE = QSize(300, 200)

TITLE = "PiqoPiqo"

# https://stackoverflow.com/a/13184390

# Optimize grid layout + scrollbar area
# https://forum.qt.io/topic/137658/table-with-large-amount-of-widgets-100-000/6

# Hi DPI


# setup logging
logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)

logger = logging.getLogger(__package__)


class PreviewTableView(qw.QTableView):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.item_size = IMAGE_SIZE
        self.initialized = False

    def set_item_size(self, width, height):
        self.item_size = QSize(width, height)

        self._computeRowColumnCount()
        self._updateLayout()

    def resizeEvent(self, event):
        # if not self.initialized:
        self._computeRowColumnCount()
        self._updateLayout()
        # self.initialized = True
        # otherwise keep the same column count : like with Adobe Bridge

        super().resizeEvent(event)

    def _updateLayout(self):
        logger.info(f"Row C {self.column_count}")
        logger.info(f"Col C {self.column_count}")
        logger.info(f"S {self.item_size}")

        for column in range(self.column_count):
            self.setColumnWidth(column, self.item_size.width())

        for row in range(self.row_count):
            self.setRowHeight(row, self.item_size.height())

        self.model().beginResetModel()
        self.model().column_count = self.column_count
        self.model().row_count = self.row_count
        self.model().endResetModel()

    def _computeRowColumnCount(self):
        width = self.viewport().width()
        height = self.viewport().height()

        logger.info(f"TV {width} {height}")
        self.column_count = max(1, width // self.item_size.width())
        self.row_count = max(1, height // self.item_size.height())


class PreviewDelegate(qw.QStyledItemDelegate):

    def paint(self, painter, option, index):
        # data is our preview object
        data = index.model().data(index, Qt.DisplayRole)
        if data is None:
            return

        width = option.rect.width() - CELL_PADDING * 2
        height = option.rect.height() - CELL_PADDING * 2

        # option.rect holds the area we are painting on the widget (our table cell)
        # scale our pixmap to fit
        scaled = data.image.scaled(
            width,
            height,
            aspectMode=Qt.KeepAspectRatio,
            mode=Qt.SmoothTransformation,
        )
        # Position in the middle of the area.
        x = CELL_PADDING + (width - scaled.width()) / 2
        y = CELL_PADDING + (height - scaled.height()) / 2

        anchor = QPoint(option.rect.x() + x, option.rect.y() + y)
        painter.drawImage(anchor, scaled)

    def sizeHint(self, option, index):
        return IMAGE_SIZE


class PreviewModel(QAbstractTableModel):
    def __init__(self, todos=None):
        super().__init__()
        self.column_count = 1
        self.row_count = 1

        self.previews = []

    def data(self, index, role):
        try:
            data = self.previews[index.row() * self.column_count + index.column()]
        except IndexError:
            # Incomplete last row.
            return

        if role == Qt.DisplayRole:
            return data  # Pass the data to our delegate to draw.

        if role == Qt.ToolTipRole:
            return data.title

    def columnCount(self, index):
        logger.info(f"Col C M {self.column_count}")
        return self.column_count

    def rowCount(self, index):
        logger.info(f"Row C M {self.column_count}")
        return self.row_count


def case_insensitive_glob(dir_path, suffix):
    l_suffix = suffix.lower()
    return [
        file_path
        for filename in os.listdir(dir_path)
        if (file_path := os.path.join(dir_path, filename)).lower().endswith(l_suffix)
        and os.path.isfile(file_path)
    ]


class MainWindow(qw.QMainWindow):
    def __init__(self, dir_path):
        super().__init__()

        self.setWindowTitle(TITLE)

        menubar = self.menuBar()
        fileMenu = menubar.addMenu("File")
        dummyAction = fileMenu.addAction("Dummy")

        central_widget = qw.QWidget(self)
        central_widget.setStyleSheet("background-color: #ff0000;")
        self.setCentralWidget(central_widget)

        # Set the layout on the central widget
        self.mainlayout = qw.QVBoxLayout(central_widget)

        self.view = PreviewTableView()
        self.view.horizontalHeader().hide()
        self.view.verticalHeader().hide()
        # self.view.setGridStyle(Qt.NoPen)
        self.view.setStyleSheet("background-color: #0000ff;")

        self.mainlayout.addWidget(self.view)

        delegate = PreviewDelegate()
        self.view.setItemDelegate(delegate)
        self.model = PreviewModel()
        self.view.setModel(self.model)

        files = case_insensitive_glob(dir_path, ".jpg")
        # Add a bunch of images.
        for n, fn in enumerate(files):
            image = QImage(fn)
            item = preview(n, fn, image)
            self.model.previews.append(item)
        self.model.layoutChanged.emit()

        self.view.resizeRowsToContents()
        self.view.resizeColumnsToContents()


# context_settings={"ignore_unknown_options": True}
@click.command()
@click.option(
    "-f",
    "--folder",
    "dir_path",
    type=click.Path(exists=True, file_okay=False, dir_okay=True, readable=True),
)
def main(dir_path):
    app = qw.QApplication()
    app.setApplicationName(TITLE.lower())
    app.setApplicationDisplayName(TITLE)
    window = MainWindow(DIR_PATH)
    window.resize(800, 600)
    window.show()

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
