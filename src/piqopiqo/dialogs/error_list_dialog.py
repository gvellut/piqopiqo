"""Dialog showing list of files with loading errors."""

import os

from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
)


class ErrorListDialog(QDialog):
    """Dialog showing list of files with loading errors."""

    def __init__(
        self,
        thumb_errors: dict[str, str],
        exif_errors: dict[str, str],
        parent=None,
    ):
        super().__init__(parent)
        self.setWindowTitle("Loading Errors")
        self.setMinimumSize(500, 300)

        layout = QVBoxLayout(self)

        # Create tree widget with two top-level items
        self.tree = QTreeWidget()
        self.tree.setHeaderLabels(["File", "Error"])
        self.tree.setColumnWidth(0, 250)

        if thumb_errors:
            thumb_item = QTreeWidgetItem(
                [f"Thumbnail Errors ({len(thumb_errors)})", ""]
            )
            for path, error in thumb_errors.items():
                child = QTreeWidgetItem([os.path.basename(path), error])
                child.setToolTip(0, path)
                thumb_item.addChild(child)
            self.tree.addTopLevelItem(thumb_item)
            thumb_item.setExpanded(True)

        if exif_errors:
            exif_item = QTreeWidgetItem([f"EXIF Errors ({len(exif_errors)})", ""])
            for path, error in exif_errors.items():
                child = QTreeWidgetItem([os.path.basename(path), error])
                child.setToolTip(0, path)
                exif_item.addChild(child)
            self.tree.addTopLevelItem(exif_item)
            exif_item.setExpanded(True)

        layout.addWidget(self.tree)

        # Close button
        btn_box = QDialogButtonBox(QDialogButtonBox.Close)
        btn_box.rejected.connect(self.close)
        layout.addWidget(btn_box)
