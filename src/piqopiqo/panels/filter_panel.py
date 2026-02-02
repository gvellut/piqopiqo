from __future__ import annotations

import logging
import os

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QCheckBox, QComboBox

from piqopiqo.components.scollable_strip import ScrollableStrip

logger = logging.getLogger(__name__)


class FilterPanel(ScrollableStrip):
    filter_changed = Signal(object)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._setup_ui()

    def _setup_ui(self):
        # 1. Add widgets using the superclass method
        self.filter_checkbox = QCheckBox("Folder:")
        self.filter_checkbox.setChecked(False)
        self.filter_checkbox.stateChanged.connect(self._on_checkbox_changed)
        self.add_widget(self.filter_checkbox)

        self.folder_combo = QComboBox()
        self.folder_combo.setMinimumWidth(150)
        self.add_widget(self.folder_combo)

        # Add extra items to demonstrate scrolling
        # for i in range(100):
        #     self.add_widget(QCheckBox(f"Tag {i}"))

    def set_folders(self, folders: list[str]):
        """Set the list of folders to filter by.

        Args:
            folders: List of folder paths.
        """
        self._folders = folders
        self._updating = True

        self.folder_combo.clear()

        if len(folders) <= 1:
            # Hide if only one folder or none
            self.setVisible(False)
            self._updating = False
            return

        # Add folder names (just the last component)
        for folder in folders:
            folder_name = os.path.basename(folder) or folder
            self.folder_combo.addItem(folder_name)
            # Set full path as tooltip
            idx = self.folder_combo.count() - 1
            self.folder_combo.setItemData(idx, folder, Qt.ToolTipRole)

        self.setVisible(True)
        self.filter_checkbox.setChecked(False)
        self._updating = False

    def _on_checkbox_changed(self, state: int):
        """Handle checkbox state change."""
        if self._updating:
            return

        if state == Qt.Checked.value:
            # Enable filter with current selection
            idx = self.folder_combo.currentIndex()
            if 0 <= idx < len(self._folders):
                self.filter_changed.emit(self._folders[idx])
        else:
            # Disable filter
            self.filter_changed.emit(None)

    def _on_combo_changed(self, index: int):
        """Handle combobox selection change."""
        if self._updating:
            return

        if index < 0 or index >= len(self._folders):
            return

        # Auto-check the checkbox when selecting a folder
        self._updating = True
        self.filter_checkbox.setChecked(True)
        self._updating = False

        # Emit the filter change
        self.filter_changed.emit(self._folders[index])

    def get_current_filter(self) -> str | None:
        """Get the current filter folder path.

        Returns:
            Folder path if filtering is enabled, None otherwise.
        """
        if not self.filter_checkbox.isChecked():
            return None

        idx = self.folder_combo.currentIndex()
        if 0 <= idx < len(self._folders):
            return self._folders[idx]

        return None

    def clear_filter(self):
        """Clear the filter (uncheck checkbox)."""
        self._updating = True
        self.filter_checkbox.setChecked(False)
        self._updating = False
