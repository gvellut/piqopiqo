"""Photo list model with filtering, sorting, and selection management."""

from __future__ import annotations

from datetime import datetime
from enum import Enum, auto
import logging
import os
from typing import TYPE_CHECKING

from PySide6.QtCore import QObject, Signal

from .metadata.db_fields import DBFields
from .model import FilterCriteria, ImageItem

if TYPE_CHECKING:
    from .metadata.metadata_db import MetadataDBManager

from .metadata.metadata_db import MetadataDBUnavailableError

logger = logging.getLogger(__name__)


class SortOrder(Enum):
    """Sort order options for photos."""

    TIME_TAKEN = auto()  # Sort by time_taken (db_metadata), then filename
    FILE_NAME = auto()  # Sort by basename only
    FILE_NAME_BY_FOLDER = auto()  # Sort by (folder, basename) tuple


class PhotoListModel(QObject):
    """Model managing the photo list with filtering, sorting, and selection.

    Signals:
        photos_changed: Emitted when the filtered/sorted view changes
        photo_added: Emitted when a photo is added (path, index in filtered view)
        photo_removed: Emitted when a photo is removed (path, former index)
        selection_changed: Emitted when selection changes (set of indices)
        sort_order_changed: Emitted when sort order changes (SortOrder)
    """

    # Signals
    photos_changed = Signal()  # Full refresh needed
    photo_added = Signal(str, int)  # file_path, index
    photo_removed = Signal(str, int)  # file_path, former_index
    selection_changed = Signal(set)  # set of indices
    sort_order_changed = Signal(object)  # SortOrder

    def __init__(
        self,
        db_manager: MetadataDBManager,
        parent=None,
    ):
        super().__init__(parent)
        self._db_manager = db_manager

        # All photos (unfiltered, unsorted source)
        self._all_photos: list[ImageItem] = []

        # Filtered and sorted view
        self._filtered_photos: list[ImageItem] = []

        # Current filter and sort settings
        self._filter: FilterCriteria | None = None
        self._sort_order: SortOrder = SortOrder.FILE_NAME

        # Source folders
        self._source_folders: list[str] = []

    # --- Properties ---

    @property
    def all_photos(self) -> list[ImageItem]:
        """All photos (unfiltered)."""
        return self._all_photos

    @property
    def photos(self) -> list[ImageItem]:
        """Filtered and sorted photo view."""
        return self._filtered_photos

    @property
    def sort_order(self) -> SortOrder:
        """Current sort order."""
        return self._sort_order

    @property
    def source_folders(self) -> list[str]:
        """List of source folders."""
        return self._source_folders

    # --- Data Management ---

    def set_photos(self, photos: list[ImageItem], source_folders: list[str]):
        """Set the complete photo list (replaces existing).

        Args:
            photos: List of ImageItem objects.
            source_folders: List of source folder paths.
        """
        self._all_photos = photos
        self._source_folders = source_folders
        self._apply_filter_and_sort()
        self.photos_changed.emit()

    def add_photo(self, photo: ImageItem) -> int:
        """Add a photo to the model.

        Args:
            photo: ImageItem to add.

        Returns:
            Index in filtered view, or -1 if filtered out.
        """
        self._all_photos.append(photo)

        # Add source folder if not already tracked
        if photo.source_folder and photo.source_folder not in self._source_folders:
            self._source_folders.append(photo.source_folder)
            self._source_folders.sort()

        # Check if it passes filter
        if self._passes_filter(photo):
            # Find insertion point to maintain sort order
            index = self._find_sorted_insertion_point(photo)
            self._filtered_photos.insert(index, photo)
            self._reindex_from(index)
            self.photo_added.emit(photo.path, index)
            return index

        self.photo_added.emit(photo.path, -1)
        return -1

    def add_photos(self, photos: list[ImageItem]) -> list[str]:
        """Add multiple photos to the model with one refresh.

        Args:
            photos: Candidate ImageItems to add.

        Returns:
            Paths that were actually added.
        """
        if not photos:
            return []

        existing_paths = {photo.path for photo in self._all_photos}
        added_paths: list[str] = []
        added_photos: list[ImageItem] = []

        for photo in photos:
            path = getattr(photo, "path", None)
            if not path or path in existing_paths:
                continue
            existing_paths.add(path)
            added_photos.append(photo)
            added_paths.append(path)

        if not added_photos:
            return []

        self._all_photos.extend(added_photos)

        new_source_folders = {
            photo.source_folder
            for photo in added_photos
            if photo.source_folder and photo.source_folder not in self._source_folders
        }
        if new_source_folders:
            self._source_folders.extend(sorted(new_source_folders))
            self._source_folders.sort()

        self._apply_filter_and_sort()
        self.photos_changed.emit()
        return added_paths

    def update_photo_paths(
        self,
        moves: list[tuple[str, str]],
        *,
        emit_signals: bool = True,
    ) -> list[tuple[str, str]]:
        """Update existing photo paths in place.

        Selection and cached editable metadata stay attached to the ImageItem.
        Runtime thumbnail state is cleared because cache paths are path based.

        Args:
            moves: List of (old_path, new_path) pairs.
            emit_signals: Emit photos_changed when True.

        Returns:
            Move pairs that were applied.
        """
        if not moves:
            return []

        photos_by_path = {photo.path: photo for photo in self._all_photos}
        applied: list[tuple[str, str]] = []

        for old_path, new_path in moves:
            if not old_path or not new_path or old_path == new_path:
                continue

            photo = photos_by_path.get(old_path)
            if photo is None:
                continue

            existing_new = photos_by_path.get(new_path)
            if existing_new is not None and existing_new is not photo:
                logger.warning(
                    "Skipping path update %s -> %s: destination already exists",
                    old_path,
                    new_path,
                )
                continue

            photos_by_path.pop(old_path, None)
            photos_by_path[new_path] = photo

            photo.path = new_path
            photo.name = os.path.basename(new_path)
            photo.source_folder = os.path.dirname(new_path)
            photo.state = 0
            photo._cache_state_dirty = True
            photo.embedded_pixmap = None
            photo.hq_pixmap = None
            photo.pixmap = None
            photo.exif_data = None
            applied.append((old_path, new_path))

        if not applied:
            return []

        self._rebuild_source_folders()
        self._apply_filter_and_sort()
        if emit_signals:
            self.photos_changed.emit()
        return applied

    def remove_photo(self, file_path: str) -> int:
        """Remove a photo from the model.

        Args:
            file_path: Path to the photo to remove.

        Returns:
            Former index in filtered view, or -1 if not found.
        """
        # Find and remove from all_photos
        photo = None
        for i, p in enumerate(self._all_photos):
            if p.path == file_path:
                photo = self._all_photos.pop(i)
                break

        if photo is None:
            return -1

        self._rebuild_source_folders()

        # Find and remove from filtered view
        former_index = -1
        for i, p in enumerate(self._filtered_photos):
            if p.path == file_path:
                former_index = i
                self._filtered_photos.pop(i)
                break

        if former_index >= 0:
            self._reindex_from(former_index)
            self.photo_removed.emit(file_path, former_index)
        else:
            self.photo_removed.emit(file_path, -1)

        # Cleanup: delete metadata DB entry and thumbnail cache
        self._cleanup_photo_data(file_path, photo.source_folder)

        return former_index

    def _cleanup_photo_data(self, file_path: str, source_folder: str):
        """Clean up DB and cache data for a removed photo."""
        # Delete from metadata DB
        db = self._db_manager.get_db_for_folder(source_folder)
        try:
            db.delete_metadata(file_path)
        except MetadataDBUnavailableError:
            logger.warning("Skipping metadata cleanup while DB recovery is active")

        # Delete thumbnail cache files
        from .cache_paths import (
            get_thumb_dir_for_folder,
            get_thumb_embedded_dir_for_folder,
            get_thumb_hq_dir_for_folder,
        )

        thumb_dir = get_thumb_dir_for_folder(source_folder)
        basename = os.path.splitext(os.path.basename(file_path))[0]

        cache_files = [
            get_thumb_embedded_dir_for_folder(source_folder) / f"{basename}.jpg",
            get_thumb_hq_dir_for_folder(source_folder) / f"{basename}.jpg",
            # Legacy naming (pre split-folders)
            thumb_dir / f"{basename}_embedded.jpg",
            thumb_dir / f"{basename}_hq.jpg",
        ]

        for cache_file in cache_files:
            if not cache_file.exists():
                continue
            try:
                cache_file.unlink()
                logger.debug(f"Deleted cache file: {cache_file}")
            except OSError as e:
                logger.warning(f"Failed to delete cache file {cache_file}: {e}")

    # --- Selection ---

    def get_selected_photos(self) -> list[ImageItem]:
        """Get list of selected photos."""
        return [p for p in self._filtered_photos if p.is_selected]

    def get_selected_indices(self) -> set[int]:
        """Get set of selected indices in filtered view."""
        return {i for i, p in enumerate(self._filtered_photos) if p.is_selected}

    def select_photo(self, index: int, clear_others: bool = True):
        """Select a photo by index.

        Args:
            index: Index in filtered view.
            clear_others: If True, deselect all other photos first.
        """
        if clear_others:
            for p in self._filtered_photos:
                p.is_selected = False

        if 0 <= index < len(self._filtered_photos):
            self._filtered_photos[index].is_selected = True

        self.selection_changed.emit(self.get_selected_indices())

    def toggle_selection(self, index: int):
        """Toggle selection of a photo."""
        if 0 <= index < len(self._filtered_photos):
            photo = self._filtered_photos[index]
            photo.is_selected = not photo.is_selected
            self.selection_changed.emit(self.get_selected_indices())

    def select_range(self, start: int, end: int):
        """Select a range of photos (inclusive)."""
        for i in range(min(start, end), max(start, end) + 1):
            if 0 <= i < len(self._filtered_photos):
                self._filtered_photos[i].is_selected = True
        self.selection_changed.emit(self.get_selected_indices())

    def clear_selection(self):
        """Deselect all photos."""
        for p in self._filtered_photos:
            p.is_selected = False
        self.selection_changed.emit(set())

    # --- Filtering ---

    @staticmethod
    def normalize_filter_criteria(
        criteria: FilterCriteria | None,
    ) -> FilterCriteria | None:
        """Normalize a filter criteria object.

        Returns None when the criteria is effectively empty.
        """
        if criteria is None:
            return None

        folder = criteria.folder
        if folder == "":
            folder = None

        labels = {label for label in criteria.labels if label}
        include_no_label = bool(criteria.include_no_label)
        explicit_labels = {label for label in criteria.explicit_labels if label}
        search_text = (criteria.search_text or "").strip()

        if folder is None and not labels and not include_no_label and not search_text:
            return None

        return FilterCriteria(
            folder=folder,
            labels=labels,
            include_no_label=include_no_label,
            explicit_labels=explicit_labels,
            search_text=search_text,
        )

    def set_filter(
        self,
        criteria: FilterCriteria | None,
        *,
        emit_signals: bool = True,
    ) -> bool:
        """Set the filter criteria.

        Args:
            criteria: Filter criteria, or None for no filter.
            emit_signals: Emit photos_changed when True.

        Returns:
            True when the active filter changed.
        """
        normalized = self.normalize_filter_criteria(criteria)
        if normalized == self._filter:
            return False

        self._filter = normalized
        self._apply_filter_and_sort()
        if emit_signals:
            self.photos_changed.emit()
        return True

    def _passes_filter(self, photo: ImageItem) -> bool:
        """Check if a photo passes the current filter."""
        if self._filter is None:
            return True

        # Folder filter
        if self._filter.folder is not None:
            if photo.source_folder != self._filter.folder:
                return False

        # Label filter
        if self._filter.labels or self._filter.include_no_label:
            photo_label = None
            if photo.db_metadata:
                photo_label = photo.db_metadata.get(DBFields.LABEL)

            matches_explicit_label = (
                bool(photo_label) and photo_label in self._filter.labels
            )
            matches_no_label = self._filter.include_no_label and (
                not photo_label
                or (
                    bool(self._filter.explicit_labels)
                    and photo_label not in self._filter.explicit_labels
                )
            )

            if not matches_explicit_label and not matches_no_label:
                return False

        # Search filter
        if self._filter.search_text:
            search_lower = self._filter.search_text.lower()
            if not photo.db_metadata:
                return False

            title = (photo.db_metadata.get(DBFields.TITLE) or "").lower()
            keywords = (photo.db_metadata.get(DBFields.KEYWORDS) or "").lower()

            if search_lower not in title and search_lower not in keywords:
                return False

        return True

    # --- Sorting ---

    def set_sort_order(self, order: SortOrder, *, emit_signals: bool = True):
        """Set the sort order.

        Args:
            order: New sort order.
            emit_signals: Emit sort/photos changed signals when True.
        """
        if self._sort_order != order:
            self._sort_order = order
            self._apply_filter_and_sort()
            if emit_signals:
                self.sort_order_changed.emit(order)
                self.photos_changed.emit()

    def _get_sort_key(self, photo: ImageItem):
        """Get the sort key for a photo based on current sort order."""
        if self._sort_order == SortOrder.TIME_TAKEN:
            # Sort by time_taken, fallback to filename
            time_taken = None
            if photo.db_metadata:
                time_taken = photo.db_metadata.get(DBFields.TIME_TAKEN)
            if time_taken is None:
                # Fallback to FS created time (stored in ImageItem.created)
                try:
                    time_taken = datetime.strptime(photo.created, "%Y-%m-%d %H:%M:%S")
                except (ValueError, TypeError):
                    time_taken = datetime.min
            return (time_taken, photo.name.lower())

        elif self._sort_order == SortOrder.FILE_NAME:
            return photo.name.lower()

        elif self._sort_order == SortOrder.FILE_NAME_BY_FOLDER:
            return (photo.source_folder, photo.name.lower())

        return photo.name.lower()

    def sort_photos_for_current_order(self, photos: list[ImageItem]) -> list[ImageItem]:
        """Return a sorted copy of photos using the current sort order."""
        sorted_photos = list(photos)
        sorted_photos.sort(key=self._get_sort_key)
        return sorted_photos

    def _find_sorted_insertion_point(self, photo: ImageItem) -> int:
        """Find the correct insertion point for a photo to maintain sort order."""
        key = self._get_sort_key(photo)
        # Binary search would be more efficient, but for simplicity:
        for i, p in enumerate(self._filtered_photos):
            if self._get_sort_key(p) > key:
                return i
        return len(self._filtered_photos)

    # --- Internal ---

    def _apply_filter_and_sort(self):
        """Apply current filter and sort to generate filtered view.

        Selection is preserved for items that pass the filter.
        Items that are filtered out have their selection cleared.
        """
        # Filter
        if self._filter is None:
            filtered = list(self._all_photos)
        else:
            filtered = []
            for p in self._all_photos:
                if self._passes_filter(p):
                    filtered.append(p)
                else:
                    # Clear selection for items that are filtered out
                    p.is_selected = False

        # Sort
        filtered = self.sort_photos_for_current_order(filtered)

        # Update indices
        for i, photo in enumerate(filtered):
            photo._global_index = i

        self._filtered_photos = filtered

    def _rebuild_source_folders(self) -> None:
        self._source_folders = sorted(
            {
                photo.source_folder
                for photo in self._all_photos
                if photo.source_folder
            }
        )

    def _reindex_from(self, start_index: int):
        """Update _global_index for all photos from start_index onwards."""
        for i in range(start_index, len(self._filtered_photos)):
            self._filtered_photos[i]._global_index = i

    # --- Metadata updates ---

    def refresh_after_metadata_update(self) -> None:
        """Re-apply filter/sort after DB metadata changes."""
        self._apply_filter_and_sort()
        self.photos_changed.emit()
