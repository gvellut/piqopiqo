"""Dialog showing workspace details and deferred cleanup actions."""

from __future__ import annotations

from dataclasses import dataclass

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from piqopiqo.external_apps import (
    get_reveal_in_file_manager_label_macos,
    reveal_path_in_file_manager_macos,
)


@dataclass(frozen=True)
class WorkspaceFolderSummary:
    """Display data for one source folder in the workspace properties dialog."""

    folder_path: str
    relative_path: str
    cache_folder_name: str
    photo_count: int


class WorkspacePropertiesDialog(QDialog):
    """Workspace details and deferred cleanup actions."""

    def __init__(
        self,
        *,
        root_folder: str,
        total_photo_count: int,
        folder_summaries: list[WorkspaceFolderSummary],
        parent=None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Workspace Property")
        self.setModal(True)
        self.setMinimumWidth(700)

        self._root_folder = str(root_folder)
        self._folder_summaries = list(folder_summaries)
        self._pending_clear_thumb_cache = False
        self._pending_clear_metadata = False
        self._selected_folder_path: str | None = None
        self._reveal_label = get_reveal_in_file_manager_label_macos()

        layout = QVBoxLayout(self)
        layout.setSpacing(10)

        workspace_group = QGroupBox("Current workspace", self)
        workspace_layout = QVBoxLayout(workspace_group)
        workspace_layout.setSpacing(8)

        root_row = QWidget(workspace_group)
        root_row_layout = QHBoxLayout(root_row)
        root_row_layout.setContentsMargins(0, 0, 0, 0)
        root_row_layout.setSpacing(8)
        root_label_title = QLabel("Folder:", root_row)
        root_row_layout.addWidget(root_label_title, 0)
        self.root_folder_label = QLabel(self._root_folder, root_row)
        self.root_folder_label.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
        )
        self.root_folder_label.setWordWrap(True)
        root_row_layout.addWidget(self.root_folder_label, 1)
        self.reveal_root_button = QPushButton(self._reveal_label, root_row)
        self.reveal_root_button.clicked.connect(self._on_reveal_root_folder)
        root_row_layout.addWidget(self.reveal_root_button, 0)
        workspace_layout.addWidget(root_row)

        self.total_photos_label = QLabel(
            f"Photos: {int(total_photo_count)}",
            workspace_group,
        )
        workspace_layout.addWidget(self.total_photos_label)
        layout.addWidget(workspace_group)

        cleanup_group = QGroupBox("Cleanup", self)
        cleanup_layout = QHBoxLayout(cleanup_group)
        cleanup_layout.setContentsMargins(10, 10, 10, 10)
        cleanup_layout.setSpacing(8)
        self.clear_thumb_cache_button = QPushButton(
            "Clear Thumbnail Cache (All Folders)",
            cleanup_group,
        )
        self.clear_thumb_cache_button.clicked.connect(
            self._on_request_clear_thumb_cache
        )
        cleanup_layout.addWidget(self.clear_thumb_cache_button, 1)

        self.clear_metadata_button = QPushButton(
            "Clear Metadata (All Folders)",
            cleanup_group,
        )
        self.clear_metadata_button.clicked.connect(self._on_request_clear_metadata)
        cleanup_layout.addWidget(self.clear_metadata_button, 1)
        layout.addWidget(cleanup_group)

        folders_group = QGroupBox("Folders with photos", self)
        folders_layout = QVBoxLayout(folders_group)
        folders_layout.setSpacing(8)

        self.folder_list_widget = QListWidget(folders_group)
        self.folder_list_widget.setSelectionMode(
            QAbstractItemView.SelectionMode.SingleSelection
        )
        self.folder_list_widget.currentRowChanged.connect(
            self._on_folder_selection_changed
        )
        folders_layout.addWidget(self.folder_list_widget)

        for index, summary in enumerate(self._folder_summaries):
            item = QListWidgetItem(summary.relative_path)
            item.setData(Qt.ItemDataRole.UserRole, index)
            item.setToolTip(summary.folder_path)
            self.folder_list_widget.addItem(item)

        self._set_folder_list_compact_height()
        layout.addWidget(folders_group)

        details_group = QGroupBox("Selected folder details", self)
        details_layout = QFormLayout(details_group)
        details_layout.setSpacing(8)
        self.selected_folder_value = QLabel("-", details_group)
        self.selected_folder_value.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
        )
        self.selected_cache_value = QLabel("-", details_group)
        self.selected_cache_value.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
        )
        self.selected_photo_count_value = QLabel("-", details_group)
        self.selected_photo_count_value.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
        )
        details_layout.addRow("Relative folder:", self.selected_folder_value)
        details_layout.addRow("Cache folder name:", self.selected_cache_value)
        details_layout.addRow("Photos:", self.selected_photo_count_value)

        self.reveal_selected_folder_button = QPushButton(
            self._reveal_label,
            details_group,
        )
        self.reveal_selected_folder_button.clicked.connect(
            self._on_reveal_selected_folder
        )
        details_layout.addRow("", self.reveal_selected_folder_button)
        layout.addWidget(details_group)

        button_box = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel,
            self,
        )
        button_box.accepted.connect(self.accept)
        button_box.rejected.connect(self.reject)
        layout.addWidget(button_box)

        if self.folder_list_widget.count() > 0:
            self.folder_list_widget.setCurrentRow(0)
        else:
            self.reveal_selected_folder_button.setEnabled(False)

    @property
    def clear_thumb_cache_requested(self) -> bool:
        return self._pending_clear_thumb_cache

    @property
    def clear_metadata_requested(self) -> bool:
        return self._pending_clear_metadata

    def _set_folder_list_compact_height(self) -> None:
        row_height = self.folder_list_widget.sizeHintForRow(0)
        if row_height <= 0:
            row_height = self.fontMetrics().height() + 10
        frame = 2 * self.folder_list_widget.frameWidth()
        min_rows = 3
        max_rows = 8
        self.folder_list_widget.setMinimumHeight((row_height * min_rows) + frame + 2)
        self.folder_list_widget.setMaximumHeight((row_height * max_rows) + frame + 2)

    def _on_request_clear_thumb_cache(self) -> None:
        if self._pending_clear_thumb_cache:
            return
        self._pending_clear_thumb_cache = True
        self.clear_thumb_cache_button.setEnabled(False)

    def _on_request_clear_metadata(self) -> None:
        if self._pending_clear_metadata:
            return

        answer = QMessageBox.warning(
            self,
            "Clear Metadata",
            "This will delete cached metadata databases for all loaded folders "
            "when the Property dialog is closed. If you haven't saved to EXIF, the "
            "data will be lost.\n\n"
            "This can be undone by pressing Cancel in the property dialog. Continue?",
            QMessageBox.StandardButton.Ok | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Cancel,
        )
        # align left
        # label = answer.findChild(QLabel, "qt_msgbox_label")
        # if label:
        #     label.setAlignment(
        #         Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter
        #     )

        if answer != QMessageBox.StandardButton.Ok:
            return

        self._pending_clear_metadata = True
        self.clear_metadata_button.setEnabled(False)

    def _on_folder_selection_changed(self, row: int) -> None:
        if row < 0 or row >= len(self._folder_summaries):
            self._selected_folder_path = None
            self.selected_folder_value.setText("-")
            self.selected_cache_value.setText("-")
            self.selected_photo_count_value.setText("-")
            self.reveal_selected_folder_button.setEnabled(False)
            return

        summary = self._folder_summaries[row]
        self._selected_folder_path = summary.folder_path
        self.selected_folder_value.setText(summary.relative_path)
        self.selected_cache_value.setText(summary.cache_folder_name)
        self.selected_photo_count_value.setText(str(int(summary.photo_count)))
        self.reveal_selected_folder_button.setEnabled(True)

    def _on_reveal_root_folder(self) -> None:
        reveal_path_in_file_manager_macos(self._root_folder)

    def _on_reveal_selected_folder(self) -> None:
        if self._selected_folder_path:
            reveal_path_in_file_manager_macos(self._selected_folder_path)
