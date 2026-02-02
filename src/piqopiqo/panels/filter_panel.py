from __future__ import annotations

import logging
import os

from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLayout,
    QLineEdit,
    QPushButton,
    QSizePolicy,
    QStyle,
    QWidget,
)

from piqopiqo.components.scollable_strip import ScrollableStrip
from piqopiqo.config import Config
from piqopiqo.model import FilterCriteria

logger = logging.getLogger(__name__)

# Special value for "All folders" option
ALL_FOLDERS = "__ALL_FOLDERS__"
# Special value for "No Label" option
NO_LABEL = "__NO_LABEL__"


class ColorSwatch(QFrame):
    """A small colored square widget."""

    def __init__(self, color: str, parent=None):
        super().__init__(parent)
        self.setFixedSize(16, 16)
        self.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        self.setStyleSheet(f"background-color: {color}; border: 1px solid #888;")


class LabelCheckbox(QWidget):
    """A checkbox with a color swatch and label text."""

    stateChanged = Signal(int)

    def __init__(self, label_name: str, color: str, parent=None):
        super().__init__(parent)
        self._label_name = label_name

        obj_name = f"filter_label_{label_name.lower().replace(' ', '_')}"
        self.setObjectName(f"{obj_name}_container")

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)

        self.checkbox = QCheckBox()
        self.checkbox.setObjectName(obj_name)

        # On macOS, the checkbox indicator visual rect can be larger than reported,
        # or strict sizing causes overlap. Add padding to the fixed size.
        style = self.checkbox.style()
        ind_w = style.pixelMetric(QStyle.PM_IndicatorWidth, None, self.checkbox)
        ind_h = style.pixelMetric(QStyle.PM_IndicatorHeight, None, self.checkbox)
        self.checkbox.setFixedSize(ind_w + 10, max(16, ind_h))
        self.checkbox.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)

        self.checkbox.stateChanged.connect(self.stateChanged)
        layout.addWidget(self.checkbox)

        swatch = ColorSwatch(color)
        layout.addWidget(swatch)

        text_label = QLabel(label_name)
        text_label.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        layout.addWidget(text_label)

        # Ensure this composite widget always gets enough space for its children,
        # so the internal spacing doesn't collapse when placed in tight containers.
        layout.setSizeConstraint(QLayout.SetFixedSize)
        self.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)

    @property
    def label_name(self) -> str:
        return self._label_name

    def isChecked(self) -> bool:
        return self.checkbox.isChecked()

    def setChecked(self, checked: bool):
        self.checkbox.setChecked(checked)

    def setEnabled(self, enabled: bool):
        super().setEnabled(enabled)
        self.checkbox.setEnabled(enabled)


class FilterPanel(ScrollableStrip):
    filter_changed = Signal(FilterCriteria)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._folders: list[str] = []
        self._updating = False
        self._label_checkboxes: dict[str, LabelCheckbox] = {}  # label_name -> widget
        self._no_label_checkbox: QCheckBox | None = None
        self._setup_ui()
        # Start disabled until folders are set
        self._set_panel_enabled(False)

    def _setup_ui(self):
        # 1. Clear filter button
        self.clear_button = QPushButton("Clear filter")
        self.clear_button.setObjectName("filter_clear_button")
        self.clear_button.clicked.connect(self._on_clear_filter)
        self.add_widget(self.clear_button)

        # Add separator
        self._add_separator()

        # 2. Folder filter combobox (no checkbox)
        folder_label = QLabel("Folder:")
        folder_label.setObjectName("filter_folder_label")
        self.add_widget(folder_label)

        self.folder_combo = QComboBox()
        self.folder_combo.setObjectName("filter_folder_combo")
        self.folder_combo.setMinimumWidth(150)
        self.folder_combo.currentIndexChanged.connect(self._on_folder_changed)
        self.add_widget(self.folder_combo)

        # Add separator
        self._add_separator()

        # 3. Label filters
        label_title = QLabel("Labels:")
        label_title.setObjectName("filter_labels_title")
        self.add_widget(label_title)

        # "No Label" checkbox (first)
        self._no_label_checkbox = QCheckBox("No Label")
        self._no_label_checkbox.setObjectName("filter_label_no_label")
        self._no_label_checkbox.stateChanged.connect(self._on_label_filter_changed)
        self.add_widget(self._no_label_checkbox)

        # Label checkboxes from config
        for status_label in Config.STATUS_LABELS:
            label_checkbox = LabelCheckbox(status_label.name, status_label.color)
            label_checkbox.stateChanged.connect(self._on_label_filter_changed)
            self._label_checkboxes[status_label.name] = label_checkbox
            self.add_widget(label_checkbox)

        # Add separator
        self._add_separator()

        # 4. Search field
        search_label = QLabel("Search:")
        search_label.setObjectName("filter_search_label")
        self.add_widget(search_label)

        self.search_field = QLineEdit()
        self.search_field.setObjectName("filter_search_field")
        self.search_field.setPlaceholderText("Search ...")
        self.search_field.setMinimumWidth(150)
        self.search_field.returnPressed.connect(self._on_search_changed)
        self.search_field.editingFinished.connect(self._on_search_changed)
        self.add_widget(self.search_field)

    def _add_separator(self):
        """Add a vertical separator line."""
        separator = QFrame()
        separator.setFrameShape(QFrame.VLine)
        separator.setFrameShadow(QFrame.Sunken)
        self.add_widget(separator)

    def _set_panel_enabled(self, enabled: bool):
        """Enable or disable all filter widgets."""
        self.clear_button.setEnabled(enabled)
        self.folder_combo.setEnabled(enabled)
        self.search_field.setEnabled(enabled)
        if self._no_label_checkbox:
            self._no_label_checkbox.setEnabled(enabled)
        for checkbox in self._label_checkboxes.values():
            checkbox.setEnabled(enabled)

    def set_folders(self, folders: list[str]):
        """Set the list of folders to filter by.

        Args:
            folders: List of folder paths.
        """
        self._folders = folders
        self._updating = True

        self.folder_combo.clear()

        # Always add "All folders" as the first option
        self.folder_combo.addItem("All folders", ALL_FOLDERS)

        # Add folder names (just the last component)
        for folder in folders:
            folder_name = os.path.basename(folder) or folder
            self.folder_combo.addItem(folder_name, folder)
            # Set full path as tooltip
            idx = self.folder_combo.count() - 1
            self.folder_combo.setItemData(idx, folder, Qt.ToolTipRole)

        # Reset to "All folders"
        self.folder_combo.setCurrentIndex(0)

        # Enable/disable folder combo based on number of folders
        # If only one folder (or none), combobox is inactive
        has_multiple_folders = len(folders) > 1
        self.folder_combo.setEnabled(has_multiple_folders)

        # Enable the panel if we have folders
        panel_enabled = len(folders) > 0
        self._set_panel_enabled(panel_enabled)
        # But folder combo depends on multiple folders
        if panel_enabled:
            self.folder_combo.setEnabled(has_multiple_folders)

        self.setVisible(True)
        self._updating = False

    def set_no_folders(self):
        """Call this when no folder is open - disables the entire panel."""
        self._folders = []
        self._updating = True
        self.folder_combo.clear()
        self.folder_combo.addItem("All folders", ALL_FOLDERS)
        self._set_panel_enabled(False)
        self._updating = False

    def _on_folder_changed(self, index: int):
        """Handle combobox selection change."""
        if self._updating:
            return
        self._emit_filter()

    def _on_label_filter_changed(self, state: int):
        """Handle label checkbox state change."""
        if self._updating:
            return
        self._emit_filter()

    def _on_search_changed(self):
        """Handle search field change (Enter or focus lost)."""
        if self._updating:
            return
        self._emit_filter()

    def _on_clear_filter(self):
        """Reset all filters to default state."""
        self._updating = True

        # Reset folder to "All folders"
        self.folder_combo.setCurrentIndex(0)

        # Uncheck all label checkboxes
        if self._no_label_checkbox:
            self._no_label_checkbox.setChecked(False)
        for checkbox in self._label_checkboxes.values():
            checkbox.setChecked(False)

        # Clear search field
        self.search_field.clear()

        self._updating = False
        self._emit_filter()

    def _emit_filter(self):
        """Build and emit the current filter criteria."""
        criteria = self.get_current_filter()
        self.filter_changed.emit(criteria)

    def get_current_filter(self) -> FilterCriteria:
        """Get the current filter criteria.

        Returns:
            FilterCriteria with current filter settings.
        """
        # Folder filter
        folder = None
        folder_data = self.folder_combo.currentData()
        if folder_data and folder_data != ALL_FOLDERS:
            folder = folder_data

        # Label filter
        labels: set[str] = set()
        for label_name, checkbox in self._label_checkboxes.items():
            if checkbox.isChecked():
                labels.add(label_name)

        include_no_label = (
            self._no_label_checkbox.isChecked() if self._no_label_checkbox else False
        )

        # Search filter
        search_text = self.search_field.text().strip()

        return FilterCriteria(
            folder=folder,
            labels=labels,
            include_no_label=include_no_label,
            search_text=search_text,
        )

    def clear_filter(self):
        """Clear all filters (called externally)."""
        self._on_clear_filter()
