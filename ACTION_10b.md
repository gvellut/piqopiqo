# ACTION_10b: Background EXIF Loading, Status Bar, and Grid Metadata Display

## Status: IMPLEMENTED

## Overview

This action enhances PiqoPiqo with:
1. Background EXIF data loading for editable fields (separate from thumbnail queue)
2. Status bar with combined progress for thumbnails and EXIF loading
3. Grid item metadata display from database fields
4. Code restructuring: separate DB management from edit panel
5. Constants and field mapping improvements

---

## Task 1: Define Constants for DB Field Names and Mappings

**New file:** `src/piqopiqo/db_fields.py`

**Goal:** Create a single source of truth for database field names, EXIF mappings, and display labels.

### 1.1 Database Field Constants

```python
# Database field names (column names in SQLite)
class DBFields:
    FILE_PATH = "file_path"
    FILE_NAME = "file_name"
    TITLE = "title"
    DESCRIPTION = "description"
    LATITUDE = "latitude"
    LONGITUDE = "longitude"
    KEYWORDS = "keywords"
    TIME_TAKEN = "time_taken"  # Renamed from datetime_original
    LABEL = "label"
    CREATED_AT = "created_at"
    UPDATED_AT = "updated_at"
```

### 1.2 EXIF to DB Field Mapping

```python
# Maps DB field -> list of EXIF fields to try (in order of preference)
EXIF_TO_DB_MAPPING = {
    DBFields.TITLE: ["XMP:Title", "EXIF:ImageDescription"],
    DBFields.DESCRIPTION: ["XMP:Description", "EXIF:UserComment"],
    DBFields.LATITUDE: ["EXIF:GPSLatitude"],  # Also needs GPSLatitudeRef
    DBFields.LONGITUDE: ["EXIF:GPSLongitude"],  # Also needs GPSLongitudeRef
    DBFields.KEYWORDS: ["IPTC:Keywords", "XMP:Subject"],
    DBFields.TIME_TAKEN: ["EXIF:DateTimeOriginal"],
    DBFields.LABEL: ["XMP:Label"],
}

# GPS reference fields (special handling)
GPS_REF_FIELDS = {
    DBFields.LATITUDE: "EXIF:GPSLatitudeRef",
    DBFields.LONGITUDE: "EXIF:GPSLongitudeRef",
}
```

### 1.3 Display Label Mapping

```python
# Maps DB field -> display label for the edit panel
FIELD_DISPLAY_LABELS = {
    DBFields.TITLE: "Title:",
    DBFields.DESCRIPTION: "Description:",
    DBFields.LATITUDE: "Latitude:",
    DBFields.LONGITUDE: "Longitude:",
    DBFields.KEYWORDS: "Keywords:",
    DBFields.TIME_TAKEN: "Time taken:",
    DBFields.LABEL: "Label:",
}
```

### 1.4 Editable Fields List

```python
# Ordered list of editable fields (determines panel order)
EDITABLE_FIELDS = [
    DBFields.TITLE,
    DBFields.DESCRIPTION,
    DBFields.LATITUDE,
    DBFields.LONGITUDE,
    DBFields.KEYWORDS,
    DBFields.TIME_TAKEN,
    DBFields.LABEL,
]
```

---

## Task 2: Rename datetime_original to time_taken

**Files to modify:**
- `src/piqopiqo/edit_panel.py`

**Goal:** Rename the database column and all references from `datetime_original` to `time_taken`.

### 2.1 Database Schema Update

Update `MetadataDB.SCHEMA`:
```python
SCHEMA = """
CREATE TABLE IF NOT EXISTS photo_metadata (
    ...
    time_taken TEXT,  -- Was: datetime_original TEXT
    ...
);
"""
```

### 2.2 Update All References

Search and replace throughout `edit_panel.py`:
- `datetime_original` -> `time_taken`
- `"datetime_original"` -> `DBFields.TIME_TAKEN`

**Note:** Use the constants from Task 1 for all string references.

### 2.3 Migration Consideration

Since this is a schema change:
- New databases will use `time_taken`
- Existing databases with `datetime_original` need migration
- Add migration check in `MetadataDB._ensure_db()`:
  ```python
  def _check_migration(self):
      """Check if database needs migration from datetime_original to time_taken."""
      # Check if old column exists
      cursor = self._connection.execute("PRAGMA table_info(photo_metadata)")
      columns = [row[1] for row in cursor.fetchall()]
      if "datetime_original" in columns and "time_taken" not in columns:
          self._connection.execute(
              "ALTER TABLE photo_metadata RENAME COLUMN datetime_original TO time_taken"
          )
          self._connection.commit()
  ```

---

## Task 3: Restructure Code - Separate DB Management from Edit Panel

**New files:**
- `src/piqopiqo/metadata_db.py` - Database classes and utilities
- `src/piqopiqo/exif_loader.py` - Background EXIF loading queue manager

**Files to modify:**
- `src/piqopiqo/edit_panel.py` - Remove DB classes, keep only UI

### 3.1 Create `metadata_db.py`

Move from `edit_panel.py`:
- `get_db_dir_for_folder()`
- `get_db_path_for_folder()`
- `exif_gps_to_decimal()`
- `parse_exif_gps()`
- `validate_latitude()`
- `validate_longitude()`
- `validate_datetime()`
- `MetadataDB` class
- `MetadataDBManager` class

Add new imports:
```python
from .db_fields import DBFields, EXIF_TO_DB_MAPPING, GPS_REF_FIELDS
```

Update all field string references to use `DBFields` constants.

### 3.2 Create `exif_loader.py`

**ExifLoaderManager class** (similar pattern to ThumbnailManager):

```python
class ExifLoaderManager(QObject):
    """Background EXIF loader for editable metadata fields."""

    # Signals
    exif_loaded = Signal(str, dict)  # file_path, metadata_dict
    exif_error = Signal(str, str)    # file_path, error_message
    progress_updated = Signal(int, int)  # completed, total

    def __init__(self, etHelper, db_manager: MetadataDBManager, parent=None):
        super().__init__(parent)
        self.etHelper = etHelper
        self.db_manager = db_manager
        self.thread_pool = QThreadPool()
        self.thread_pool.setMaxThreadCount(Config.MAX_WORKERS)
        self._pending: set[str] = set()
        self._total_queued = 0
        self._completed = 0
        self._errors: dict[str, str] = {}  # file_path -> error message

    def queue_image(self, file_path: str, source_folder: str):
        """Queue an image for EXIF loading."""
        # Skip if already in DB
        db = self.db_manager.get_db_for_folder(source_folder)
        if db.has_metadata(file_path):
            return

        if file_path in self._pending:
            return

        self._pending.add(file_path)
        self._total_queued += 1

        worker = ExifLoaderWorker(file_path, source_folder, self.etHelper, self.db_manager)
        worker.signals.finished.connect(self._on_worker_finished)
        worker.signals.error.connect(self._on_worker_error)
        self.thread_pool.start(worker)

    def queue_folder(self, images: list[ImageItem]):
        """Queue all images from a folder scan."""
        for item in images:
            self.queue_image(item.path, item.source_folder)

    def get_errors(self) -> dict[str, str]:
        """Get dictionary of file paths with errors."""
        return self._errors.copy()

    def reset(self):
        """Reset counters for new folder load."""
        self._total_queued = 0
        self._completed = 0
        self._errors.clear()
```

**ExifLoaderWorker class** (QRunnable):

```python
class ExifLoaderWorkerSignals(QObject):
    finished = Signal(str, dict)  # file_path, metadata
    error = Signal(str, str)      # file_path, error_message

class ExifLoaderWorker(QRunnable):
    def __init__(self, file_path: str, source_folder: str, etHelper, db_manager):
        super().__init__()
        self.file_path = file_path
        self.source_folder = source_folder
        self.etHelper = etHelper
        self.db_manager = db_manager
        self.signals = ExifLoaderWorkerSignals()

    def run(self):
        try:
            # Read EXIF data
            exif_data = self.etHelper.get_metadata(self.file_path)[0]

            # Extract editable fields
            metadata = extract_editable_metadata(exif_data)

            # Save to database
            db = self.db_manager.get_db_for_folder(self.source_folder)
            db.save_metadata(self.file_path, metadata)

            self.signals.finished.emit(self.file_path, metadata)
        except Exception as e:
            self.signals.error.emit(self.file_path, str(e))
```

**Extract helper function:**

```python
def extract_editable_metadata(exif_data: dict) -> dict:
    """Extract editable metadata fields from EXIF data."""
    result = {}

    for db_field, exif_fields in EXIF_TO_DB_MAPPING.items():
        value = None
        for exif_field in exif_fields:
            if exif_field in exif_data:
                value = exif_data[exif_field]
                break

        # Special handling for GPS
        if db_field in (DBFields.LATITUDE, DBFields.LONGITUDE):
            ref_field = GPS_REF_FIELDS[db_field]
            ref = exif_data.get(ref_field)
            value = parse_exif_gps(value, ref)

        # Special handling for keywords (may be array)
        if db_field == DBFields.KEYWORDS and isinstance(value, list):
            value = ", ".join(str(k) for k in value)

        result[db_field] = value

    return result
```

### 3.3 Update `edit_panel.py`

- Remove all database and utility classes (moved to other files)
- Add imports:
  ```python
  from .db_fields import DBFields, FIELD_DISPLAY_LABELS, EDITABLE_FIELDS
  from .metadata_db import MetadataDBManager
  ```
- Update field creation to use `FIELD_DISPLAY_LABELS`
- Update all field name strings to use `DBFields` constants

---

## Task 4: Update Label ComboBox Styling

**File to modify:** `src/piqopiqo/edit_panel.py`

**Goal:** Change from colored text to standard text with color swatch.

### 4.1 Create Custom Item Delegate

```python
class ColorSwatchDelegate(QStyledItemDelegate):
    """Delegate that draws a color swatch before item text."""

    SWATCH_SIZE = 12
    SWATCH_MARGIN = 4

    def paint(self, painter, option, index):
        # Get color from item data
        color = index.data(Qt.UserRole)

        # Draw background (selection highlight if selected)
        if option.state & QStyle.State_Selected:
            painter.fillRect(option.rect, option.palette.highlight())

        # Draw color swatch
        swatch_rect = QRect(
            option.rect.left() + self.SWATCH_MARGIN,
            option.rect.center().y() - self.SWATCH_SIZE // 2,
            self.SWATCH_SIZE,
            self.SWATCH_SIZE
        )
        painter.fillRect(swatch_rect, QColor(color) if color else QColor("#808080"))
        painter.drawRect(swatch_rect)

        # Draw text (standard color, not the label color)
        text_rect = option.rect.adjusted(
            self.SWATCH_MARGIN * 2 + self.SWATCH_SIZE, 0, 0, 0
        )
        text = index.data(Qt.DisplayRole)
        painter.setPen(option.palette.text().color())
        painter.drawText(text_rect, Qt.AlignVCenter | Qt.AlignLeft, text)

    def sizeHint(self, option, index):
        size = super().sizeHint(option, index)
        size.setWidth(size.width() + self.SWATCH_SIZE + self.SWATCH_MARGIN * 2)
        return size
```

### 4.2 Update StatusComboBox

```python
class StatusComboBox(QComboBox):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._original_value = ""
        self._populating = False

        # Use custom delegate for swatch display
        self.setItemDelegate(ColorSwatchDelegate(self))

        # Populate from config
        for label_name, color_hex in Config.STATUS_LABELS:
            self.addItem(label_name)
            idx = self.count() - 1
            # Store color in UserRole (for delegate), NOT ForegroundRole
            self.setItemData(idx, color_hex, Qt.UserRole)

        self.currentIndexChanged.connect(self._on_index_changed)
```

---

## Task 5: Add Refresh Button to Edit Panel

**File to modify:** `src/piqopiqo/edit_panel.py`

**Goal:** Add a Refresh button that reloads data from EXIF when DB data is missing.

### 5.1 Add Refresh Button to Panel

```python
class EditPanel(QWidget):
    refresh_requested = Signal(list)  # list of ImageItem to refresh

    def _setup_ui(self):
        # ... existing code ...

        # Add refresh button at top of panel
        header_layout = QHBoxLayout()
        header_layout.setContentsMargins(10, 5, 10, 5)

        self.refresh_btn = QPushButton()
        self.refresh_btn.setIcon(QIcon.fromTheme("view-refresh"))  # Or custom icon
        self.refresh_btn.setToolTip("Refresh from EXIF")
        self.refresh_btn.setFixedSize(24, 24)
        self.refresh_btn.setEnabled(False)
        self.refresh_btn.clicked.connect(self._on_refresh_clicked)

        header_layout.addStretch()
        header_layout.addWidget(self.refresh_btn)

        main_layout.addLayout(header_layout)
        # ... rest of setup ...

    def _on_refresh_clicked(self):
        """Request refresh of current items from EXIF."""
        if self._current_items:
            self.refresh_requested.emit(self._current_items)

    def update_for_selection(self, items: list[ImageItem]):
        # ... existing code ...

        # Enable refresh button only if some items have no DB data
        has_missing_data = False
        for item in items:
            db = self.db_manager.get_db_for_image(item.path)
            if not db.has_metadata(item.path):
                has_missing_data = True
                break
        self.refresh_btn.setEnabled(has_missing_data)
```

### 5.2 Connect in MainWindow

```python
# In MainWindow.__init__:
if self.edit_panel:
    self.edit_panel.refresh_requested.connect(self._on_refresh_requested)

def _on_refresh_requested(self, items: list[ImageItem]):
    """Handle refresh request from edit panel."""
    for item in items:
        # Force reload from EXIF
        self.exif_loader.queue_image(item.path, item.source_folder, force=True)
```

---

## Task 6: Add Status Bar with Progress

**New file:** `src/piqopiqo/status_bar.py`

**Goal:** Create a status bar showing combined thumbnail + EXIF loading progress.

### 6.1 Create StatusBar Widget

```python
class LoadingStatusBar(QWidget):
    """Status bar with photo count and loading progress."""

    show_errors_requested = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._setup_ui()

        self._thumb_total = 0
        self._thumb_completed = 0
        self._exif_total = 0
        self._exif_completed = 0
        self._photo_count = 0
        self._filtered_count = 0
        self._has_errors = False

    def _setup_ui(self):
        layout = QHBoxLayout(self)
        layout.setContentsMargins(10, 2, 10, 2)

        # Photo count label (left side)
        self.count_label = QLabel("0 photos")
        layout.addWidget(self.count_label)

        layout.addStretch()

        # Progress bar (center, hidden when complete)
        self.progress_bar = QProgressBar()
        self.progress_bar.setMaximumWidth(200)
        self.progress_bar.setTextVisible(True)
        self.progress_bar.hide()
        layout.addWidget(self.progress_bar)

        # Error button (right side, hidden when no errors)
        self.error_btn = QPushButton()
        self.error_btn.setIcon(QIcon.fromTheme("dialog-warning"))
        self.error_btn.setToolTip("There were errors")
        self.error_btn.setFlat(True)
        self.error_btn.clicked.connect(self.show_errors_requested.emit)
        self.error_btn.hide()
        layout.addWidget(self.error_btn)

    def set_photo_count(self, total: int, filtered: int | None = None):
        """Set the photo count display."""
        self._photo_count = total
        self._filtered_count = filtered if filtered is not None else total

        if filtered is not None and filtered != total:
            self.count_label.setText(f"{filtered} of {total} photos")
        else:
            self.count_label.setText(f"{total} photos")

    def set_thumb_progress(self, completed: int, total: int):
        """Update thumbnail loading progress."""
        self._thumb_completed = completed
        self._thumb_total = total
        self._update_progress()

    def set_exif_progress(self, completed: int, total: int):
        """Update EXIF loading progress."""
        self._exif_completed = completed
        self._exif_total = total
        self._update_progress()

    def _update_progress(self):
        """Update the combined progress bar."""
        # Combined progress: each photo counts once for thumb + once for exif
        total = self._thumb_total + self._exif_total
        completed = self._thumb_completed + self._exif_completed

        if total == 0:
            self.progress_bar.hide()
            return

        if completed >= total:
            self.progress_bar.hide()
        else:
            self.progress_bar.show()
            self.progress_bar.setMaximum(total)
            self.progress_bar.setValue(completed)
            self.progress_bar.setFormat(f"{completed}/{total}")

    def set_has_errors(self, has_errors: bool):
        """Show or hide the error button."""
        self._has_errors = has_errors
        self.error_btn.setVisible(has_errors)

    def reset(self):
        """Reset all progress for new folder load."""
        self._thumb_total = 0
        self._thumb_completed = 0
        self._exif_total = 0
        self._exif_completed = 0
        self._has_errors = False
        self.progress_bar.hide()
        self.error_btn.hide()
```

### 6.2 Create Error Dialog

```python
class ErrorListDialog(QDialog):
    """Dialog showing list of files with loading errors."""

    def __init__(self, thumb_errors: dict, exif_errors: dict, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Loading Errors")
        self.setMinimumSize(500, 300)

        layout = QVBoxLayout(self)

        # Create tree widget with two top-level items
        self.tree = QTreeWidget()
        self.tree.setHeaderLabels(["File", "Error"])
        self.tree.setColumnWidth(0, 250)

        if thumb_errors:
            thumb_item = QTreeWidgetItem(["Thumbnail Errors", ""])
            for path, error in thumb_errors.items():
                child = QTreeWidgetItem([os.path.basename(path), error])
                child.setToolTip(0, path)
                thumb_item.addChild(child)
            self.tree.addTopLevelItem(thumb_item)
            thumb_item.setExpanded(True)

        if exif_errors:
            exif_item = QTreeWidgetItem(["EXIF Errors", ""])
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
```

### 6.3 Integrate with MainWindow

```python
# In MainWindow.__init__:

# Add status bar
self.status_bar = LoadingStatusBar()
self.status_bar.show_errors_requested.connect(self._show_error_dialog)
self.setStatusBar(self.status_bar)  # Or add to layout

# Connect progress signals
self.thumb_manager.progress_updated.connect(self._on_thumb_progress)
self.exif_loader.progress_updated.connect(self._on_exif_progress)
self.exif_loader.all_completed.connect(self._on_loading_complete)

def _on_thumb_progress(self, completed: int, total: int):
    self.status_bar.set_thumb_progress(completed, total)

def _on_exif_progress(self, completed: int, total: int):
    self.status_bar.set_exif_progress(completed, total)

def _on_loading_complete(self):
    has_errors = bool(self.thumb_manager.get_errors()) or bool(self.exif_loader.get_errors())
    self.status_bar.set_has_errors(has_errors)

def _show_error_dialog(self):
    dialog = ErrorListDialog(
        self.thumb_manager.get_errors(),
        self.exif_loader.get_errors(),
        self
    )
    dialog.exec()
```

---

## Task 7: Add Progress Signals to ThumbnailManager

**File to modify:** `src/piqopiqo/thumb_man.py`

**Goal:** Add progress tracking and error collection to thumbnail manager.

### 7.1 Update ThumbnailManager

```python
class ThumbnailManager(QObject):
    thumb_ready = Signal(str, str, str)
    progress_updated = Signal(int, int)  # completed, total

    def __init__(self, parent=None):
        super().__init__(parent)
        # ... existing code ...
        self._total_queued = 0
        self._completed = 0
        self._errors: dict[str, str] = {}

    def queue_image(self, file_path: str):
        # ... existing code ...
        self._total_queued += 1
        self.progress_updated.emit(self._completed, self._total_queued)

    def on_task_done(self, result):
        thumb_type, file_path, cache_path = result

        self._completed += 1
        self.progress_updated.emit(self._completed, self._total_queued)

        if thumb_type is None:
            self._errors[file_path] = "Failed to generate thumbnail"

        # ... rest of existing code ...

    def get_errors(self) -> dict[str, str]:
        return self._errors.copy()

    def reset_progress(self):
        """Reset counters for new folder load."""
        self._total_queued = 0
        self._completed = 0
        self._errors.clear()
```

---

## Task 8: Grid Item Metadata Display Configuration

**File to modify:** `src/piqopiqo/config.py`

**Goal:** Add configuration for displaying DB fields on grid items.

### 8.1 Add Config Options

```python
# Grid item metadata display
# List of DB field names to show below filename
# Available: "title", "time_taken", "keywords", "description"
# Note: "label" is handled separately (shown as swatch, not text)
GRID_ITEM_FIELDS = ["title", "time_taken"]

# Show label as colored swatch on grid item
GRID_ITEM_SHOW_LABEL_SWATCH = True
```

---

## Task 9: Update PhotoCell to Display DB Metadata

**File to modify:** `src/piqopiqo/photo_grid.py`

**Goal:** Update grid item painting to show DB fields and label swatch.

### 9.1 Update ImageItem Model

**File:** `src/piqopiqo/model.py`

```python
@attr.s(auto_attribs=True)
class ImageItem:
    path: str
    name: str
    created: str
    source_folder: str = ""
    is_selected: bool = False
    pixmap: QPixmap | None = None
    state: int = 0
    _global_index: int = -1
    exif_data: dict | None = None
    db_metadata: dict | None = None  # NEW: Cached DB metadata
```

### 9.2 Update PhotoCell.paintEvent

```python
def paintEvent(self, event: QPaintEvent):
    if not self.layout_info:
        return

    painter = QPainter(self)
    rect = self.rect()

    # ... selection highlight code ...

    if self.current_data is None:
        return

    # Unpack Data
    name = self.current_data.name
    pixmap = self.current_data.pixmap
    db_meta = self.current_data.db_metadata or {}

    pad = self.layout_info.get("pad", 5)
    meta_h = self.layout_info.get("meta_h", 20)

    # Image Rect
    img_rect = rect.adjusted(pad, pad, -pad, -(pad + meta_h))

    # ... draw image code ...

    # Draw label swatch (top-right corner of image area)
    if Config.GRID_ITEM_SHOW_LABEL_SWATCH:
        label = db_meta.get(DBFields.LABEL)
        if label:
            color = self._get_label_color(label)
            if color:
                swatch_size = 16
                swatch_margin = 4
                swatch_rect = QRect(
                    img_rect.right() - swatch_size - swatch_margin,
                    img_rect.top() + swatch_margin,
                    swatch_size,
                    swatch_size
                )
                painter.fillRect(swatch_rect, QColor(color))
                painter.setPen(QPen(Qt.black, 1))
                painter.drawRect(swatch_rect)

    # Text area
    text_rect = QRect(
        rect.left() + pad,
        rect.bottom() - meta_h - pad,
        rect.width() - (2 * pad),
        meta_h,
    )

    painter.setPen(QPen(Qt.white))

    # Filename (first line)
    font_metrics = painter.fontMetrics()
    line_height = font_metrics.lineSpacing()

    elided_name = font_metrics.elidedText(name, Qt.ElideRight, text_rect.width())
    painter.drawText(text_rect, Qt.AlignTop | Qt.AlignHCenter, elided_name)

    # DB fields (subsequent lines)
    y_offset = line_height
    for field_name in Config.GRID_ITEM_FIELDS:
        if field_name == DBFields.LABEL:
            continue  # Label shown as swatch, not text

        value = db_meta.get(field_name, "")
        if value:
            field_rect = QRect(
                text_rect.left(),
                text_rect.top() + y_offset,
                text_rect.width(),
                line_height
            )
            elided_value = font_metrics.elidedText(str(value), Qt.ElideRight, text_rect.width())
            painter.drawText(field_rect, Qt.AlignTop | Qt.AlignHCenter, elided_value)
        y_offset += line_height

def _get_label_color(self, label: str) -> str | None:
    """Get color hex for a label name."""
    for name, color in Config.STATUS_LABELS:
        if name == label:
            return color
    return None
```

### 9.3 Dynamic Footer Height Calculation

**File:** `src/piqopiqo/photo_grid.py` in `PagedPhotoGrid`

```python
def _calculate_metadata_height(self) -> int:
    """Calculate the height needed for metadata display."""
    # Get font metrics
    font = QFont()
    font.setPointSize(Config.FONT_SIZE)
    fm = QFontMetrics(font)
    line_height = fm.lineSpacing()

    # Count lines: 1 for filename + 1 per configured field (excluding label)
    num_lines = 1  # filename
    for field in Config.GRID_ITEM_FIELDS:
        if field != DBFields.LABEL:  # Label is swatch, not text line
            num_lines += 1

    return num_lines * line_height + 4  # +4 for padding

def resizeEvent(self, event):
    # ... existing code ...

    # Calculate dynamic metadata height
    meta_h = self._calculate_metadata_height()

    # Use meta_h in layout calculations
    # ... existing row height calculation using meta_h ...
```

---

## Task 10: Update Data Flow for DB-First Reading

**Files to modify:**
- `src/piqopiqo/photo_grid.py` (MainWindow)
- `src/piqopiqo/edit_panel.py` (EditPanel)

**Goal:** Read editable fields from DB, not EXIF when a photo is selected.

### 10.1 Update EditPanel._gather_field_values

```python
def _gather_field_values(self, items: list[ImageItem]) -> dict:
    """Gather field values from items, using DB only (not EXIF fallback)."""
    fields = {field: set() for field in EDITABLE_FIELDS}

    for item in items:
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
```

### 10.2 Update MainWindow.on_exif_loaded

```python
def on_exif_loaded(self, file_path: str, metadata: dict):
    """Handle EXIF data loaded in background."""
    # Find the item and update its db_metadata
    for item in self._all_images_data:
        if item.path == file_path:
            item.db_metadata = metadata

            # Refresh grid item if visible
            self.grid.refresh_item(item._global_index)

            # If this item is selected, update edit panel
            if item in self._get_selected_items():
                self.edit_panel.update_for_selection(self._get_selected_items())
            break
```

### 10.3 Preload DB Metadata on Selection

```python
def on_selection_changed(self, selected_indices: set[int]):
    """Handle selection change."""
    selected_items = [self.images_data[i] for i in selected_indices]

    # Load db_metadata for selected items if not already loaded
    for item in selected_items:
        if item.db_metadata is None:
            db = self.db_manager.get_db_for_image(item.path)
            item.db_metadata = db.get_metadata(item.path)

    # Update panels
    if self.edit_panel:
        self.edit_panel.update_for_selection(selected_items)
    self.exif_panel.update_exif(selected_items)

    # Fetch full EXIF for display panel (non-editable fields)
    for item in selected_items:
        if item.exif_data is None:
            self.exif_manager.fetch_exif(item.path)
```

---

## Task 11: Initialize Background EXIF Loading on Folder Load

**File to modify:** `src/piqopiqo/photo_grid.py` (MainWindow)

**Goal:** Start background EXIF loading when a folder is loaded.

### 11.1 Update MainWindow.__init__

```python
def __init__(self, images, source_folders, root_folder, etHelper):
    # ... existing code ...

    # Create EXIF loader manager (after db_manager)
    self.exif_loader = ExifLoaderManager(etHelper, self.db_manager)
    self.exif_loader.exif_loaded.connect(self.on_exif_loaded)
    self.exif_loader.exif_error.connect(self.on_exif_error)
    self.exif_loader.progress_updated.connect(self._on_exif_progress)

    # ... rest of existing code ...

    # Start background EXIF loading for all images
    self._start_background_exif_loading()

def _start_background_exif_loading(self):
    """Queue all images for background EXIF loading."""
    self.exif_loader.reset()
    self.exif_loader.queue_folder(self._all_images_data)
    self.status_bar.set_exif_progress(0, len(self._all_images_data))
```

### 11.2 Update _load_folder

```python
def _load_folder(self, folder: str):
    # ... existing code ...

    # Reset loaders
    self.exif_loader.reset()
    self.thumb_manager.reset_progress()
    self.status_bar.reset()

    # ... existing code to update images ...

    # Start background EXIF loading
    self._start_background_exif_loading()

    # Update status bar photo count
    self.status_bar.set_photo_count(len(self._all_images_data))
```

---

## Task 12: Update Filter for Status Bar Photo Count

**File to modify:** `src/piqopiqo/photo_grid.py` (MainWindow)

**Goal:** Update photo count display when filter changes.

```python
def _apply_filter(self):
    """Apply the current filter to the images."""
    if self._current_filter is None:
        self.images_data = self._all_images_data
        self.status_bar.set_photo_count(len(self._all_images_data))
    else:
        self.images_data = [
            item for item in self._all_images_data
            if item.source_folder == self._current_filter
        ]
        self.status_bar.set_photo_count(
            len(self._all_images_data),
            len(self.images_data)
        )

    # ... rest of existing code ...
```

---

## File Summary

**New files to create:**
1. `src/piqopiqo/db_fields.py` - Constants for DB fields, EXIF mapping, display labels
2. `src/piqopiqo/metadata_db.py` - Database classes moved from edit_panel.py
3. `src/piqopiqo/exif_loader.py` - Background EXIF loading manager
4. `src/piqopiqo/status_bar.py` - Status bar widget with progress

**Files to modify:**
1. `src/piqopiqo/config.py` - Add GRID_ITEM_FIELDS, GRID_ITEM_SHOW_LABEL_SWATCH
2. `src/piqopiqo/model.py` - Add db_metadata field to ImageItem
3. `src/piqopiqo/edit_panel.py` - Remove DB classes, add refresh button, update label styling
4. `src/piqopiqo/thumb_man.py` - Add progress signals and error tracking
5. `src/piqopiqo/photo_grid.py` - Integrate status bar, EXIF loader, update cell painting

---

## Implementation Order

1. **Task 1** - DB field constants (foundation for other tasks)
2. **Task 2** - Rename datetime_original to time_taken
3. **Task 3** - Code restructuring (separate metadata_db.py)
4. **Task 4** - Label combobox styling (standalone UI change)
5. **Task 3 continued** - Create exif_loader.py
6. **Task 7** - ThumbnailManager progress signals
7. **Task 6** - Status bar implementation
8. **Task 8** - Grid config options
9. **Task 9** - PhotoCell metadata display
10. **Task 5** - Refresh button
11. **Task 10** - DB-first reading
12. **Task 11** - Background EXIF loading on folder load
13. **Task 12** - Filter status bar update

Tasks 1-4 can be done as a first phase (code cleanup and UI improvements).
Tasks 5-12 form the background loading feature and should be done together.

---

## Notes

### On Background Queue Design

The ExifLoaderManager follows the same pattern as ThumbnailManager:
- Uses QThreadPool for concurrent processing
- Separate queue from thumbnails (different thread pool)
- Signals for completion and progress
- Error collection for later display

### On Grid Item Footer Size

The footer height must be computed before the grid layout:
- Count: 1 (filename) + N (configured fields, excluding label)
- Line height from font metrics
- This affects row height calculation and visible row count

### On Label Display

Label is special-cased:
- In edit panel: color swatch on left of text
- In grid: color swatch on top-right of image (not in text area)
- Text color in combobox is standard (not colored)

### On DB-First Reading

When selecting a photo:
1. Check DB for metadata
2. If found: use DB values (don't read EXIF for editable fields)
3. If not found: show empty fields (background loader will populate later)
4. Still read EXIF for display panel (non-editable fields like camera info)
