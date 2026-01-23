"""Editable metadata panel and database management."""

from datetime import datetime
import logging
import os
from pathlib import Path
import re
import sqlite3

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QComboBox,
    QGridLayout,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from .config import Config
from .model import ImageItem
from .thumb_man import get_cache_dir_for_folder

logger = logging.getLogger(__name__)

# Placeholder for multiple values
MULTIPLE_VALUES = "<Multiple Values>"


def get_db_dir_for_folder(folder_path: str) -> Path:
    """Get the database directory for a specific folder.

    Args:
        folder_path: Path to the source folder.

    Returns:
        Path to the db subdirectory in the cache.
    """
    return get_cache_dir_for_folder(folder_path) / "db"


def get_db_path_for_folder(folder_path: str) -> Path:
    """Get the database file path for a specific folder.

    Args:
        folder_path: Path to the source folder.

    Returns:
        Path to the metadata.db file.
    """
    return get_db_dir_for_folder(folder_path) / "metadata.db"


def exif_gps_to_decimal(
    degrees: float, minutes: float, seconds: float, ref: str
) -> float:
    """Convert EXIF GPS format to decimal degrees.

    Args:
        degrees: Degrees value (int or float)
        minutes: Minutes value (int or float)
        seconds: Seconds value (float)
        ref: Reference direction ('N', 'S', 'E', 'W')

    Returns:
        Decimal degrees (negative for S and W)
    """
    decimal = degrees + minutes / 60 + seconds / 3600
    if ref in ("S", "W"):
        decimal = -decimal
    return decimal


def parse_exif_gps(gps_value, gps_ref: str | None) -> float | None:
    """Parse GPS value from EXIF data.

    Handles various formats:
    - Already decimal: 48.8566
    - DMS string: "48 deg 51' 23.80\""
    - Tuple/list: (48, 51, 23.80)

    Args:
        gps_value: The GPS value from EXIF
        gps_ref: The reference direction (N/S/E/W) or None

    Returns:
        Decimal degrees or None if parsing fails
    """
    if gps_value is None:
        return None

    try:
        # Already a decimal number
        if isinstance(gps_value, (int, float)):
            decimal = float(gps_value)
            if gps_ref in ("S", "W"):
                decimal = -abs(decimal)
            return decimal

        # Tuple or list format (degrees, minutes, seconds)
        if isinstance(gps_value, (list, tuple)) and len(gps_value) >= 3:
            deg, min_val, sec = gps_value[0], gps_value[1], gps_value[2]
            return exif_gps_to_decimal(
                float(deg), float(min_val), float(sec), gps_ref or "N"
            )

        # String format - try to parse DMS
        if isinstance(gps_value, str):
            # Try direct float conversion first
            try:
                decimal = float(gps_value)
                if gps_ref in ("S", "W"):
                    decimal = -abs(decimal)
                return decimal
            except ValueError:
                pass

            # Try DMS pattern: "48 deg 51' 23.80""
            pattern = r"(\d+)\s*(?:deg|°)?\s*(\d+)\s*['\u2019]?\s*([\d.]+)"
            match = re.search(pattern, gps_value)
            if match:
                deg = float(match.group(1))
                min_val = float(match.group(2))
                sec = float(match.group(3))
                return exif_gps_to_decimal(deg, min_val, sec, gps_ref or "N")

    except (ValueError, TypeError, IndexError) as e:
        logger.debug(f"Failed to parse GPS value {gps_value}: {e}")

    return None


def validate_latitude(value: str) -> tuple[bool, float | None]:
    """Validate a latitude string.

    Args:
        value: String value to validate

    Returns:
        Tuple of (is_valid, parsed_value or None)
    """
    if not value or not value.strip():
        return True, None
    try:
        lat = float(value.strip())
        if -90 <= lat <= 90:
            return True, lat
        return False, None
    except ValueError:
        return False, None


def validate_longitude(value: str) -> tuple[bool, float | None]:
    """Validate a longitude string.

    Args:
        value: String value to validate

    Returns:
        Tuple of (is_valid, parsed_value or None)
    """
    if not value or not value.strip():
        return True, None
    try:
        lon = float(value.strip())
        if -180 <= lon <= 180:
            return True, lon
        return False, None
    except ValueError:
        return False, None


def validate_datetime(value: str) -> tuple[bool, str | None]:
    """Validate a datetime string in EXIF format.

    Args:
        value: String value to validate (expected: YYYY:MM:DD HH:MM:SS)

    Returns:
        Tuple of (is_valid, parsed_value or None)
    """
    if not value or not value.strip():
        return True, None
    try:
        # EXIF format: YYYY:MM:DD HH:MM:SS
        datetime.strptime(value.strip(), "%Y:%m:%d %H:%M:%S")
        return True, value.strip()
    except ValueError:
        # Also accept ISO format
        try:
            datetime.strptime(value.strip(), "%Y-%m-%d %H:%M:%S")
            # Convert to EXIF format
            dt = datetime.strptime(value.strip(), "%Y-%m-%d %H:%M:%S")
            return True, dt.strftime("%Y:%m:%d %H:%M:%S")
        except ValueError:
            return False, None


class MetadataDB:
    """SQLite database manager for photo metadata."""

    SCHEMA = """
    CREATE TABLE IF NOT EXISTS photo_metadata (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        file_path TEXT UNIQUE NOT NULL,
        file_name TEXT NOT NULL,
        title TEXT,
        description TEXT,
        latitude REAL,
        longitude REAL,
        keywords TEXT,
        datetime_original TEXT,
        label TEXT,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL
    );
    CREATE INDEX IF NOT EXISTS idx_file_path ON photo_metadata(file_path);
    """

    def __init__(self, folder_path: str):
        """Initialize the database manager for a folder.

        Note: Does not create the database file until first write.

        Args:
            folder_path: Path to the source folder.
        """
        self.folder_path = folder_path
        self.db_path = get_db_path_for_folder(folder_path)
        self._connection: sqlite3.Connection | None = None

    def _ensure_db(self) -> sqlite3.Connection:
        """Create database file and tables if they don't exist.

        Returns:
            Database connection.
        """
        if self._connection is None:
            # Create directory if needed
            self.db_path.parent.mkdir(parents=True, exist_ok=True)

            self._connection = sqlite3.connect(str(self.db_path))
            self._connection.row_factory = sqlite3.Row
            self._connection.executescript(self.SCHEMA)
            self._connection.commit()
            logger.debug(f"Created/opened database: {self.db_path}")

        return self._connection

    def _get_readonly_connection(self) -> sqlite3.Connection | None:
        """Get a read-only connection if database exists.

        Returns:
            Database connection or None if database doesn't exist.
        """
        if self._connection is not None:
            return self._connection

        if not self.db_path.exists():
            return None

        self._connection = sqlite3.connect(str(self.db_path))
        self._connection.row_factory = sqlite3.Row
        return self._connection

    def get_metadata(self, file_path: str) -> dict | None:
        """Get metadata for a photo.

        Args:
            file_path: Full path to the image file.

        Returns:
            Dictionary with metadata or None if not found.
        """
        conn = self._get_readonly_connection()
        if conn is None:
            return None

        cursor = conn.execute(
            "SELECT * FROM photo_metadata WHERE file_path = ?", (file_path,)
        )
        row = cursor.fetchone()

        if row is None:
            return None

        return {
            "title": row["title"],
            "description": row["description"],
            "latitude": row["latitude"],
            "longitude": row["longitude"],
            "keywords": row["keywords"],
            "datetime_original": row["datetime_original"],
            "label": row["label"],
        }

    def save_metadata(self, file_path: str, data: dict) -> None:
        """Save metadata for a photo.

        Creates the database file if it doesn't exist.

        Args:
            file_path: Full path to the image file.
            data: Dictionary with metadata fields.
        """
        conn = self._ensure_db()
        now = datetime.now().isoformat()
        file_name = os.path.basename(file_path)

        # Check if entry exists
        cursor = conn.execute(
            "SELECT id FROM photo_metadata WHERE file_path = ?", (file_path,)
        )
        existing = cursor.fetchone()

        if existing:
            # Update
            conn.execute(
                """
                UPDATE photo_metadata SET
                    title = ?,
                    description = ?,
                    latitude = ?,
                    longitude = ?,
                    keywords = ?,
                    datetime_original = ?,
                    label = ?,
                    updated_at = ?
                WHERE file_path = ?
                """,
                (
                    data.get("title"),
                    data.get("description"),
                    data.get("latitude"),
                    data.get("longitude"),
                    data.get("keywords"),
                    data.get("datetime_original"),
                    data.get("label"),
                    now,
                    file_path,
                ),
            )
        else:
            # Insert
            conn.execute(
                """
                INSERT INTO photo_metadata
                (file_path, file_name, title, description, latitude, longitude,
                 keywords, datetime_original, label, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    file_path,
                    file_name,
                    data.get("title"),
                    data.get("description"),
                    data.get("latitude"),
                    data.get("longitude"),
                    data.get("keywords"),
                    data.get("datetime_original"),
                    data.get("label"),
                    now,
                    now,
                ),
            )

        conn.commit()
        logger.debug(f"Saved metadata for: {file_path}")

    def has_metadata(self, file_path: str) -> bool:
        """Check if metadata exists for a photo.

        Args:
            file_path: Full path to the image file.

        Returns:
            True if metadata exists.
        """
        conn = self._get_readonly_connection()
        if conn is None:
            return False

        cursor = conn.execute(
            "SELECT 1 FROM photo_metadata WHERE file_path = ? LIMIT 1", (file_path,)
        )
        return cursor.fetchone() is not None

    def delete_metadata(self, file_path: str) -> None:
        """Delete metadata for a photo.

        Args:
            file_path: Full path to the image file.
        """
        conn = self._get_readonly_connection()
        if conn is None:
            return

        conn.execute("DELETE FROM photo_metadata WHERE file_path = ?", (file_path,))
        conn.commit()

    def close(self) -> None:
        """Close the database connection."""
        if self._connection is not None:
            self._connection.close()
            self._connection = None


class MetadataDBManager:
    """Manages MetadataDB instances for multiple folders."""

    def __init__(self):
        self._databases: dict[str, MetadataDB] = {}

    def get_db_for_folder(self, folder_path: str) -> MetadataDB:
        """Get or create a MetadataDB for a folder.

        Args:
            folder_path: Path to the source folder.

        Returns:
            MetadataDB instance for the folder.
        """
        if folder_path not in self._databases:
            self._databases[folder_path] = MetadataDB(folder_path)
        return self._databases[folder_path]

    def get_db_for_image(self, file_path: str) -> MetadataDB:
        """Get the MetadataDB for an image based on its folder.

        Args:
            file_path: Path to the image file.

        Returns:
            MetadataDB instance for the image's folder.
        """
        folder_path = os.path.dirname(file_path)
        return self.get_db_for_folder(folder_path)

    def close_all(self) -> None:
        """Close all database connections."""
        for db in self._databases.values():
            db.close()
        self._databases.clear()


class TitleEdit(QLineEdit):
    """Single-line title editor with special key handling."""

    edit_finished = Signal()
    edit_cancelled = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._original_value = ""
        self.setMaxLength(Config.TITLE_MAX_LENGTH)

    def set_value(self, value: str):
        """Set the field value and store as original."""
        self._original_value = value or ""
        self.setText(self._original_value)

    def keyPressEvent(self, event):
        key = event.key()
        modifiers = event.modifiers()

        if key == Qt.Key_Return or key == Qt.Key_Enter:
            if modifiers & Qt.ControlModifier:
                # Cmd+Enter does nothing for title
                return
            # Enter saves and finishes
            self.edit_finished.emit()
            return

        if key == Qt.Key_Escape:
            # Escape reverts and finishes
            self.setText(self._original_value)
            self.edit_cancelled.emit()
            return

        super().keyPressEvent(event)

    def focusOutEvent(self, event):
        """Save on focus out if value changed."""
        if self.text() != self._original_value:
            self.edit_finished.emit()
        super().focusOutEvent(event)

    def insertFromMimeData(self, source):
        """Remove newlines when pasting."""
        if source.hasText():
            text = source.text().replace("\n", " ").replace("\r", " ")
            self.insert(text)


class DescriptionEdit(QPlainTextEdit):
    """Multi-line description editor with special key handling."""

    edit_finished = Signal()
    edit_cancelled = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._original_value = ""
        self.setMaximumHeight(100)

    def set_value(self, value: str):
        """Set the field value and store as original."""
        self._original_value = value or ""
        self.setPlainText(self._original_value)

    def keyPressEvent(self, event):
        key = event.key()
        modifiers = event.modifiers()

        if key == Qt.Key_Return or key == Qt.Key_Enter:
            if modifiers & Qt.ControlModifier:
                # Cmd+Enter adds newline
                self.insertPlainText("\n")
                return
            # Enter saves and finishes
            self.edit_finished.emit()
            return

        if key == Qt.Key_Escape:
            # Escape reverts and finishes
            self.setPlainText(self._original_value)
            self.edit_cancelled.emit()
            return

        super().keyPressEvent(event)

    def focusOutEvent(self, event):
        """Save on focus out if value changed."""
        text = self.toPlainText()
        if len(text) > Config.DESCRIPTION_MAX_LENGTH:
            text = text[: Config.DESCRIPTION_MAX_LENGTH]
            self.setPlainText(text)
        if text != self._original_value:
            self.edit_finished.emit()
        super().focusOutEvent(event)


class CoordinateEdit(QLineEdit):
    """Coordinate editor with validation."""

    edit_finished = Signal()
    edit_cancelled = Signal()

    def __init__(self, is_latitude: bool, parent=None):
        super().__init__(parent)
        self._original_value = ""
        self._is_latitude = is_latitude
        self._is_valid = True

    def set_value(self, value: float | None):
        """Set the field value and store as original."""
        if value is not None:
            self._original_value = f"{value:.6f}"
        else:
            self._original_value = ""
        self.setText(self._original_value)
        self._validate()

    def _validate(self):
        """Validate current value and update styling."""
        text = self.text()
        if self._is_latitude:
            valid, _ = validate_latitude(text)
        else:
            valid, _ = validate_longitude(text)

        self._is_valid = valid
        if valid:
            self.setStyleSheet("")
        else:
            self.setStyleSheet("border: 1px solid red;")

    def get_value(self) -> float | None:
        """Get the validated value."""
        text = self.text()
        if self._is_latitude:
            valid, value = validate_latitude(text)
        else:
            valid, value = validate_longitude(text)
        return value if valid else None

    def keyPressEvent(self, event):
        key = event.key()

        if key == Qt.Key_Return or key == Qt.Key_Enter:
            if self._is_valid:
                self.edit_finished.emit()
            return

        if key == Qt.Key_Escape:
            self.setText(self._original_value)
            self._validate()
            self.edit_cancelled.emit()
            return

        super().keyPressEvent(event)
        self._validate()

    def focusOutEvent(self, event):
        """Save on focus out if value changed and valid."""
        if self._is_valid and self.text() != self._original_value:
            self.edit_finished.emit()
        super().focusOutEvent(event)


class KeywordsEdit(QPlainTextEdit):
    """Keywords editor (comma-separated) with word wrap and auto-height."""

    edit_finished = Signal()
    edit_cancelled = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._original_value = ""
        self.setLineWrapMode(QPlainTextEdit.WidgetWidth)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Minimum)
        self.document().contentsChanged.connect(self._adjust_height)
        self._adjust_height()

    def _adjust_height(self):
        """Adjust height to fit content."""
        doc = self.document()
        # Use widget width if viewport not yet sized
        width = self.viewport().width()
        if width <= 0:
            width = self.width() - self.frameWidth() * 2
        if width > 0:
            doc.setTextWidth(width)

        # Get block count and calculate height based on actual line count
        block_count = doc.blockCount()
        if block_count == 0:
            block_count = 1

        # Calculate wrapped line count
        total_lines = 0
        block = doc.begin()
        while block.isValid():
            block_layout = block.layout()
            if block_layout:
                total_lines += max(1, block_layout.lineCount())
            else:
                total_lines += 1
            block = block.next()

        if total_lines == 0:
            total_lines = 1

        line_height = self.fontMetrics().lineSpacing()
        margins = self.contentsMargins()
        frame = self.frameWidth() * 2

        height = (
            total_lines * line_height + margins.top() + margins.bottom() + frame + 4
        )
        self.setFixedHeight(height)

    def resizeEvent(self, event):
        """Recalculate height on resize."""
        super().resizeEvent(event)
        self._adjust_height()

    def set_value(self, value: str):
        """Set the field value and store as original."""
        self._original_value = value or ""
        self.setPlainText(self._original_value)
        self._adjust_height()

    def text(self) -> str:
        """Return the text content (compatibility with QLineEdit interface)."""
        return self.toPlainText()

    def keyPressEvent(self, event):
        key = event.key()

        if key == Qt.Key_Return or key == Qt.Key_Enter:
            self.edit_finished.emit()
            return

        if key == Qt.Key_Escape:
            self.setPlainText(self._original_value)
            self._adjust_height()
            self.edit_cancelled.emit()
            return

        super().keyPressEvent(event)

    def insertFromMimeData(self, source):
        """Remove newlines when pasting."""
        if source.hasText():
            text = source.text().replace("\n", " ").replace("\r", " ")
            self.insertPlainText(text)

    def focusOutEvent(self, event):
        """Save on focus out if value changed."""
        if self.toPlainText() != self._original_value:
            self.edit_finished.emit()
        super().focusOutEvent(event)


class TimeEdit(QLineEdit):
    """DateTime editor with validation."""

    edit_finished = Signal()
    edit_cancelled = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._original_value = ""
        self._is_valid = True
        self.setPlaceholderText("YYYY:MM:DD HH:MM:SS")

    def set_value(self, value: str):
        """Set the field value and store as original."""
        self._original_value = value or ""
        self.setText(self._original_value)
        self._validate()

    def _validate(self):
        """Validate current value and update styling."""
        valid, _ = validate_datetime(self.text())
        self._is_valid = valid
        if valid:
            self.setStyleSheet("")
        else:
            self.setStyleSheet("border: 1px solid red;")

    def get_value(self) -> str | None:
        """Get the validated value."""
        valid, value = validate_datetime(self.text())
        return value if valid else None

    def keyPressEvent(self, event):
        key = event.key()

        if key == Qt.Key_Return or key == Qt.Key_Enter:
            if self._is_valid:
                self.edit_finished.emit()
            return

        if key == Qt.Key_Escape:
            self.setText(self._original_value)
            self._validate()
            self.edit_cancelled.emit()
            return

        super().keyPressEvent(event)
        self._validate()

    def focusOutEvent(self, event):
        """Save on focus out if value changed and valid."""
        if self._is_valid and self.text() != self._original_value:
            self.edit_finished.emit()
        super().focusOutEvent(event)


class StatusComboBox(QComboBox):
    """Status label combobox."""

    value_changed = Signal(str)  # Emits the selected label or empty string

    def __init__(self, parent=None):
        super().__init__(parent)
        self._original_value = ""
        self._populating = False

        # Populate from config
        for label_name, color_hex in Config.STATUS_LABELS:
            self.addItem(label_name)
            # Set item color
            idx = self.count() - 1
            self.setItemData(idx, QColor(color_hex), Qt.ForegroundRole)

        self.currentIndexChanged.connect(self._on_index_changed)

    def set_value(self, value: str):
        """Set the field value."""
        self._original_value = value or ""
        self._populating = True

        if not value:
            self.setCurrentIndex(0)  # "No Label"
        else:
            idx = self.findText(value)
            if idx >= 0:
                self.setCurrentIndex(idx)
            else:
                self.setCurrentIndex(0)

        self._populating = False

    def _on_index_changed(self, index: int):
        """Handle selection change."""
        if self._populating:
            return

        label = self.currentText()
        # "No Label" means clear the value
        if label == "No Label":
            self.value_changed.emit("")
        else:
            self.value_changed.emit(label)


class EditPanel(QWidget):
    """Panel for editing photo metadata."""

    edit_finished = Signal()  # Emitted when editing is complete (for focus return)

    def __init__(self, db_manager: MetadataDBManager, parent=None):
        super().__init__(parent)
        self.db_manager = db_manager
        self._current_items: list[ImageItem] = []
        self._is_multi_select = False

        self._setup_ui()

    def _setup_ui(self):
        """Create the panel UI."""
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

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
        self.layout.addWidget(QLabel("Title:"), row, 0)
        self.title_edit = TitleEdit()
        self.title_edit.edit_finished.connect(lambda: self._on_field_saved("title"))
        self.title_edit.edit_cancelled.connect(self._on_edit_cancelled)
        self.layout.addWidget(self.title_edit, row, 1)
        row += 1

        # Description
        self.layout.addWidget(QLabel("Description:"), row, 0, Qt.AlignTop)
        self.description_edit = DescriptionEdit()
        self.description_edit.edit_finished.connect(
            lambda: self._on_field_saved("description")
        )
        self.description_edit.edit_cancelled.connect(self._on_edit_cancelled)
        self.layout.addWidget(self.description_edit, row, 1)
        row += 1

        # Latitude
        self.layout.addWidget(QLabel("Latitude:"), row, 0)
        self.lat_edit = CoordinateEdit(is_latitude=True)
        self.lat_edit.edit_finished.connect(lambda: self._on_field_saved("latitude"))
        self.lat_edit.edit_cancelled.connect(self._on_edit_cancelled)
        self.layout.addWidget(self.lat_edit, row, 1)
        row += 1

        # Longitude
        self.layout.addWidget(QLabel("Longitude:"), row, 0)
        self.lon_edit = CoordinateEdit(is_latitude=False)
        self.lon_edit.edit_finished.connect(lambda: self._on_field_saved("longitude"))
        self.lon_edit.edit_cancelled.connect(self._on_edit_cancelled)
        self.layout.addWidget(self.lon_edit, row, 1)
        row += 1

        # Keywords
        self.layout.addWidget(QLabel("Keywords:"), row, 0)
        self.keywords_edit = KeywordsEdit()
        self.keywords_edit.edit_finished.connect(
            lambda: self._on_field_saved("keywords")
        )
        self.keywords_edit.edit_cancelled.connect(self._on_edit_cancelled)
        self.layout.addWidget(self.keywords_edit, row, 1)
        row += 1

        # Time
        self.layout.addWidget(QLabel("Time:"), row, 0)
        self.time_edit = TimeEdit()
        self.time_edit.edit_finished.connect(
            lambda: self._on_field_saved("datetime_original")
        )
        self.time_edit.edit_cancelled.connect(self._on_edit_cancelled)
        self.layout.addWidget(self.time_edit, row, 1)
        row += 1

        # Status
        self.layout.addWidget(QLabel("Status:"), row, 0)
        self.status_combo = StatusComboBox()
        self.status_combo.value_changed.connect(self._on_status_changed)
        self.layout.addWidget(self.status_combo, row, 1)

        scroll_area.setWidget(container)
        main_layout.addWidget(scroll_area)

    def update_for_selection(self, items: list[ImageItem]):
        """Update the panel for a selection of items.

        Args:
            items: List of selected ImageItem objects.
        """
        self._current_items = items
        self._is_multi_select = len(items) > 1

        if not items:
            self._clear_fields()
            return

        # Gather values for each field
        field_values = self._gather_field_values(items)

        # Update each field
        self._update_field("title", field_values["title"], self.title_edit)
        self._update_field(
            "description", field_values["description"], self.description_edit
        )
        self._update_coordinate_field(
            "latitude", field_values["latitude"], self.lat_edit
        )
        self._update_coordinate_field(
            "longitude", field_values["longitude"], self.lon_edit
        )
        self._update_field("keywords", field_values["keywords"], self.keywords_edit)
        self._update_field(
            "datetime_original", field_values["datetime_original"], self.time_edit
        )
        self._update_status_field(field_values["label"])

    def _gather_field_values(self, items: list[ImageItem]) -> dict:
        """Gather field values from items, checking DB first then EXIF.

        Returns:
            Dictionary mapping field names to values or MULTIPLE_VALUES.
        """
        fields = {
            "title": set(),
            "description": set(),
            "latitude": set(),
            "longitude": set(),
            "keywords": set(),
            "datetime_original": set(),
            "label": set(),
        }

        for item in items:
            # Try database first
            db = self.db_manager.get_db_for_image(item.path)
            db_data = db.get_metadata(item.path)

            if db_data:
                # Use database values
                for field in fields:
                    value = db_data.get(field)
                    fields[field].add(value if value is not None else "")
            else:
                # Extract from EXIF
                exif = item.exif_data or {}
                fields["title"].add(
                    exif.get("XMP:Title") or exif.get("EXIF:ImageDescription") or ""
                )
                fields["description"].add(
                    exif.get("XMP:Description") or exif.get("EXIF:UserComment") or ""
                )

                # Parse GPS
                lat = parse_exif_gps(
                    exif.get("EXIF:GPSLatitude"), exif.get("EXIF:GPSLatitudeRef")
                )
                lon = parse_exif_gps(
                    exif.get("EXIF:GPSLongitude"), exif.get("EXIF:GPSLongitudeRef")
                )
                fields["latitude"].add(lat if lat is not None else "")
                fields["longitude"].add(lon if lon is not None else "")

                # Keywords (may be array, items may be int or str)
                keywords = exif.get("IPTC:Keywords") or exif.get("XMP:Subject") or ""
                if isinstance(keywords, list):
                    keywords = ", ".join(str(k) for k in keywords)
                fields["keywords"].add(keywords)

                fields["datetime_original"].add(exif.get("EXIF:DateTimeOriginal") or "")
                fields["label"].add(exif.get("XMP:Label") or "")

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
        elif value == "" or value is None:
            widget.set_value(None)
        else:
            widget.set_value(float(value) if value else None)

    def _update_status_field(self, value):
        """Update the status combobox."""
        if value == MULTIPLE_VALUES:
            self.status_combo.set_value("")
            # We can't easily show "Multiple Values" in a combobox
        else:
            self.status_combo.set_value(value if value else "")

    def _clear_fields(self):
        """Clear all fields."""
        self.title_edit.set_value("")
        self.description_edit.set_value("")
        self.lat_edit.set_value(None)
        self.lon_edit.set_value(None)
        self.keywords_edit.set_value("")
        self.time_edit.set_value("")
        self.status_combo.set_value("")

    def _on_field_saved(self, field_name: str):
        """Handle field save event."""
        if not self._current_items:
            return

        # Get the new value
        value = self._get_field_value(field_name)

        # Save to all selected items
        for item in self._current_items:
            self._save_field_for_item(item, field_name, value)

        self.edit_finished.emit()

    def _get_field_value(self, field_name: str):
        """Get the current value from a field widget."""
        if field_name == "title":
            return self.title_edit.text() or None
        elif field_name == "description":
            text = self.description_edit.toPlainText()
            return text if text else None
        elif field_name == "latitude":
            return self.lat_edit.get_value()
        elif field_name == "longitude":
            return self.lon_edit.get_value()
        elif field_name == "keywords":
            return self.keywords_edit.text() or None
        elif field_name == "datetime_original":
            return self.time_edit.get_value()
        elif field_name == "label":
            text = self.status_combo.currentText()
            return text if text != "No Label" else None
        return None

    def _save_field_for_item(self, item: ImageItem, field_name: str, value):
        """Save a single field for an item."""
        db = self.db_manager.get_db_for_image(item.path)

        # Get existing data or create new
        existing = db.get_metadata(item.path)
        if existing:
            data = existing.copy()
        else:
            # Initialize with current EXIF values
            data = self._get_initial_data_from_exif(item)

        # Update the specific field
        data[field_name] = value

        # Save to database
        db.save_metadata(item.path, data)

    def _get_initial_data_from_exif(self, item: ImageItem) -> dict:
        """Extract initial data from EXIF for database creation."""
        exif = item.exif_data or {}

        lat = parse_exif_gps(
            exif.get("EXIF:GPSLatitude"), exif.get("EXIF:GPSLatitudeRef")
        )
        lon = parse_exif_gps(
            exif.get("EXIF:GPSLongitude"), exif.get("EXIF:GPSLongitudeRef")
        )

        keywords = exif.get("IPTC:Keywords") or exif.get("XMP:Subject") or ""
        if isinstance(keywords, list):
            keywords = ", ".join(str(k) for k in keywords)

        return {
            "title": exif.get("XMP:Title") or exif.get("EXIF:ImageDescription"),
            "description": exif.get("XMP:Description") or exif.get("EXIF:UserComment"),
            "latitude": lat,
            "longitude": lon,
            "keywords": keywords if keywords else None,
            "datetime_original": exif.get("EXIF:DateTimeOriginal"),
            "label": exif.get("XMP:Label"),
        }

    def _on_status_changed(self, label: str):
        """Handle status combobox change."""
        if not self._current_items:
            return

        value = label if label else None

        for item in self._current_items:
            self._save_field_for_item(item, "label", value)

    def _on_edit_cancelled(self):
        """Handle edit cancellation."""
        self.edit_finished.emit()
