"""Editable metadata panel for photo metadata."""

import logging

from PySide6.QtCore import Qt, QThreadPool, Signal
from PySide6.QtWidgets import (
    QDialog,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from piqopiqo.keyword_utils import format_keywords, parse_keywords
from piqopiqo.metadata.db_fields import EDITABLE_FIELDS, FIELD_DISPLAY_LABELS, DBFields
from piqopiqo.metadata.metadata_db import MetadataDBManager
from piqopiqo.metadata.save_workers import MetadataSaveWorker
from piqopiqo.model import ImageItem

from .edit_widgets import (
    MULTIPLE_VALUES,
    CoordinateEdit,
    DescriptionEdit,
    KeywordsEdit,
    TimeEdit,
    TitleEdit,
)
from .keyword.keyword_tree import KeywordTreeManager

logger = logging.getLogger(__name__)


class EditPanel(QWidget):
    """Panel for editing photo metadata."""

    edit_finished = Signal()  # Emitted when editing is complete (for focus return)
    metadata_saved = Signal(str)  # DBFields name for synchronization

    def __init__(self, db_manager: MetadataDBManager, parent=None):
        super().__init__(parent)
        self.db_manager = db_manager
        self._current_items: list[ImageItem] = []
        self._is_multi_select = False
        self._has_missing_data = False
        self._db_writer_pool = QThreadPool()
        self._keyword_tree_manager = KeywordTreeManager()

        self._setup_ui()

    def _setup_ui(self):
        """Create the panel UI."""
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        # Header
        header_widget = QWidget()
        header_layout = QHBoxLayout(header_widget)
        header_layout.setContentsMargins(10, 5, 10, 5)

        header_label = QLabel("Metadata")
        header_label.setStyleSheet("font-weight: bold;")
        header_layout.addWidget(header_label)

        header_layout.addStretch()

        main_layout.addWidget(header_widget)

        # Create scroll area
        scroll_area = QScrollArea()
        scroll_area.setWidgetResizable(True)
        scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll_area.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)

        # Container widget
        container = QWidget()
        container.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)
        self.layout = QGridLayout(container)
        self.layout.setContentsMargins(10, 10, 10, 10)
        self.layout.setSpacing(5)
        self.layout.setColumnStretch(0, 30)
        self.layout.setColumnStretch(1, 70)

        row = 0

        # Title
        self.layout.addWidget(
            QLabel(f"{FIELD_DISPLAY_LABELS[DBFields.TITLE]}:"), row, 0
        )
        self.title_edit = TitleEdit()
        self.title_edit.edit_finished.connect(
            lambda: self._on_field_saved(DBFields.TITLE)
        )
        self.title_edit.edit_cancelled.connect(self._on_edit_cancelled)
        self.layout.addWidget(self.title_edit, row, 1)
        row += 1

        # Description
        desc_label = QLabel(f"{FIELD_DISPLAY_LABELS[DBFields.DESCRIPTION]}:")
        self.layout.addWidget(desc_label, row, 0, Qt.AlignTop)
        self.description_edit = DescriptionEdit()
        self.description_edit.edit_finished.connect(
            lambda: self._on_field_saved(DBFields.DESCRIPTION)
        )
        self.description_edit.edit_cancelled.connect(self._on_edit_cancelled)
        self.layout.addWidget(self.description_edit, row, 1)
        row += 1

        # Latitude
        self.layout.addWidget(
            QLabel(f"{FIELD_DISPLAY_LABELS[DBFields.LATITUDE]}:"), row, 0
        )
        self.lat_edit = CoordinateEdit(is_latitude=True)
        self.lat_edit.edit_finished.connect(
            lambda: self._on_field_saved(DBFields.LATITUDE)
        )
        self.lat_edit.edit_cancelled.connect(self._on_edit_cancelled)
        self.layout.addWidget(self.lat_edit, row, 1)
        row += 1

        # Longitude
        self.layout.addWidget(
            QLabel(f"{FIELD_DISPLAY_LABELS[DBFields.LONGITUDE]}:"), row, 0
        )
        self.lon_edit = CoordinateEdit(is_latitude=False)
        self.lon_edit.edit_finished.connect(
            lambda: self._on_field_saved(DBFields.LONGITUDE)
        )
        self.lon_edit.edit_cancelled.connect(self._on_edit_cancelled)
        self.layout.addWidget(self.lon_edit, row, 1)
        row += 1

        # Keywords
        self.layout.addWidget(
            QLabel(f"{FIELD_DISPLAY_LABELS[DBFields.KEYWORDS]}:"), row, 0
        )
        self.keywords_edit = KeywordsEdit()
        self.keywords_edit.edit_finished.connect(
            lambda: self._on_field_saved(DBFields.KEYWORDS)
        )
        self.keywords_edit.edit_cancelled.connect(self._on_edit_cancelled)
        self.layout.addWidget(self.keywords_edit, row, 1)
        row += 1

        # Keyword tree button
        self.keyword_tree_btn = QPushButton("Open Keyword Tree")
        self.keyword_tree_btn.setEnabled(False)
        self.keyword_tree_btn.clicked.connect(self._on_open_keyword_tree)
        self.layout.addWidget(self.keyword_tree_btn, row, 1)
        row += 1

        # Time taken
        self.layout.addWidget(
            QLabel(f"{FIELD_DISPLAY_LABELS[DBFields.TIME_TAKEN]}:"), row, 0
        )
        self.time_edit = TimeEdit()
        self.time_edit.edit_finished.connect(
            lambda: self._on_field_saved(DBFields.TIME_TAKEN)
        )
        self.time_edit.edit_cancelled.connect(self._on_edit_cancelled)
        self.layout.addWidget(self.time_edit, row, 1)

        scroll_area.setWidget(container)
        main_layout.addWidget(scroll_area)

        # Status line (used when EXIF/DB data isn't ready yet)
        self.reading_label = QLabel("")
        self.reading_label.setContentsMargins(10, 5, 10, 5)
        self.reading_label.setStyleSheet("color: gray;")
        self.reading_label.hide()
        main_layout.addWidget(self.reading_label)

    def _set_editing_enabled(self, enabled: bool) -> None:
        for widget in (
            self.title_edit,
            self.description_edit,
            self.lat_edit,
            self.lon_edit,
            self.keywords_edit,
            self.time_edit,
            self.keyword_tree_btn,
        ):
            widget.setEnabled(enabled)

    def update_for_selection(self, items: list[ImageItem]):
        """Update the panel for a selection of items.

        Args:
            items: List of selected ImageItem objects.
        """
        self._current_items = items
        self._is_multi_select = len(items) > 1

        if not items:
            self._clear_fields()
            self._set_editing_enabled(False)
            self.reading_label.hide()
            return

        # Check if any items are still missing DB data (EXIF not read yet)
        self._has_missing_data = any(
            not self.db_manager.get_db_for_image(item.path).has_metadata(item.path)
            for item in items
        )

        if self._has_missing_data:
            self._clear_fields()
            self._set_editing_enabled(False)
            self.reading_label.setText("Reading...")
            self.reading_label.show()
            return

        self.reading_label.hide()
        self._set_editing_enabled(True)

        # Gather values for each field
        field_values = self._gather_field_values(items)

        # Update each field
        self._update_field(
            DBFields.TITLE, field_values[DBFields.TITLE], self.title_edit
        )
        self._update_field(
            DBFields.DESCRIPTION,
            field_values[DBFields.DESCRIPTION],
            self.description_edit,
        )
        self._update_coordinate_field(
            DBFields.LATITUDE, field_values[DBFields.LATITUDE], self.lat_edit
        )
        self._update_coordinate_field(
            DBFields.LONGITUDE, field_values[DBFields.LONGITUDE], self.lon_edit
        )
        self._update_field(
            DBFields.KEYWORDS, field_values[DBFields.KEYWORDS], self.keywords_edit
        )
        self._update_field(
            DBFields.TIME_TAKEN, field_values[DBFields.TIME_TAKEN], self.time_edit
        )

    def _gather_field_values(self, items: list[ImageItem]) -> dict:
        """Gather field values from items, preferring cached db_metadata.

        Uses item.db_metadata if available (most up-to-date after saves),
        otherwise falls back to querying the database.

        Returns:
            Dictionary mapping field names to values or MULTIPLE_VALUES.
        """
        fields = {field: set() for field in EDITABLE_FIELDS}

        for item in items:
            # Prefer cached db_metadata (updated synchronously after saves)
            db_data = item.db_metadata
            if not db_data:
                # Fall back to database query
                db = self.db_manager.get_db_for_image(item.path)
                db_data = db.get_metadata(item.path)

            if db_data:
                for field in fields:
                    value = db_data.get(field)
                    fields[field].add(value if value is not None else "")
            else:
                # No DB data yet - show empty for all fields
                for field in fields:
                    fields[field].add("")

        # Convert sets to single values or MULTIPLE_VALUES
        result = {}
        for field, values in fields.items():
            if len(values) == 1:
                result[field] = values.pop()
            else:
                result[field] = MULTIPLE_VALUES

        return result

    def _update_field(self, field_name: str, value, widget):
        """Update a text field widget."""
        if value == MULTIPLE_VALUES:
            widget.set_value(MULTIPLE_VALUES)
        else:
            widget.set_value(value if value else "")

    def _update_coordinate_field(self, field_name: str, value, widget):
        """Update a coordinate field widget."""
        if value == MULTIPLE_VALUES:
            widget.set_value(None)
            widget.setText(MULTIPLE_VALUES)
            widget._original_value = MULTIPLE_VALUES
            widget._validate()
        elif value == "" or value is None:
            widget.set_value(None)
        else:
            widget.set_value(float(value) if value else None)

    def _clear_fields(self):
        """Clear all fields."""
        self.title_edit.set_value("")
        self.description_edit.set_value("")
        self.lat_edit.set_value(None)
        self.lon_edit.set_value(None)
        self.keywords_edit.set_value("")
        self.time_edit.set_value("")

    def _on_field_saved(self, field_name: str):
        """Handle field save event."""
        if not self._current_items:
            return

        # Get the new value
        value = self._get_field_value(field_name)

        # If the value is MULTIPLE_VALUES, do not save (no edit was performed)
        if value == MULTIPLE_VALUES:
            return

        # Save to all selected items
        for item in self._current_items:
            self._save_field_for_item(item, field_name, value)

        self.metadata_saved.emit(field_name)
        self.edit_finished.emit()

    def _get_field_value(self, field_name: str):
        """Get the current value from a field widget."""
        if field_name == DBFields.TITLE:
            return self.title_edit.text() or None
        elif field_name == DBFields.DESCRIPTION:
            text = self.description_edit.toPlainText()
            return text if text else None
        elif field_name == DBFields.LATITUDE:
            return self.lat_edit.get_value()
        elif field_name == DBFields.LONGITUDE:
            return self.lon_edit.get_value()
        elif field_name == DBFields.KEYWORDS:
            return self.keywords_edit.text() or None
        elif field_name == DBFields.TIME_TAKEN:
            return self.time_edit.get_value()
        return None

    def _save_field_for_item(self, item: ImageItem, field_name: str, value):
        """Save a single field for an item."""
        db = self.db_manager.get_db_for_image(item.path)

        # Get existing data or create new
        existing = db.get_metadata(item.path)
        if existing:
            data = existing.copy()
        else:
            # Initialize with empty values
            data = {field: None for field in EDITABLE_FIELDS}

        # Update the specific field
        data[field_name] = value

        # Save to database in background (avoid GUI thread)
        worker = MetadataSaveWorker(db, item.path, data)
        self._db_writer_pool.start(worker)

        # Update item's cached db_metadata
        item.db_metadata = data

    def _on_edit_cancelled(self):
        """Handle edit cancellation."""
        self.edit_finished.emit()

    def _on_open_keyword_tree(self):
        """Open the keyword tree dialog."""
        if not self._current_items:
            return

        from .keyword.keyword_tree_dialog import KeywordTreeDialog

        dialog = KeywordTreeDialog(
            self._current_items,
            self._keyword_tree_manager,
            parent=self,
        )

        if dialog.exec() == QDialog.DialogCode.Accepted:
            modifications = dialog.get_modifications()
            if modifications:
                self._apply_keyword_modifications(modifications)

    def _apply_keyword_modifications(self, modifications: dict[str, bool]):
        """Apply keyword modifications to all selected items.

        Preserves original keyword order: removes deleted keywords from their
        positions, adds new keywords at the end.

        Args:
            modifications: Dict mapping keyword name to True (add) or False (remove).
        """
        for item in self._current_items:
            # Get current keywords as ordered list
            current_kws: list[str] = []
            if item.db_metadata and item.db_metadata.get(DBFields.KEYWORDS):
                current_kws = parse_keywords(item.db_metadata[DBFields.KEYWORDS])

            # Apply removals (filter out removed keywords, preserving order)
            result_kws = [
                kw for kw in current_kws if modifications.get(kw) is not False
            ]

            # Apply additions (add new keywords at the end)
            existing = set(result_kws)
            for keyword, is_add in modifications.items():
                if is_add and keyword not in existing:
                    result_kws.append(keyword)

            # Format and save
            new_value = format_keywords(result_kws)
            self._save_field_for_item(item, DBFields.KEYWORDS, new_value or None)

        # Update the keywords field display
        self.update_for_selection(self._current_items)
        self.metadata_saved.emit(DBFields.KEYWORDS)
        self.edit_finished.emit()
