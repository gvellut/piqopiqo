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
    from .background.exif_man import ExifLoaderManager
    from .background.thumb_man import ThumbnailManager
    from .metadata.metadata_db import MetadataDBManager

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
        thumb_manager: ThumbnailManager,
        exif_loader: ExifLoaderManager,
        db_manager: MetadataDBManager,
        parent=None,
    ):
        super().__init__(parent)
        self._thumb_manager = thumb_manager
        self._exif_loader = exif_loader
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

        # Queue thumbnail and EXIF loading
        self._thumb_manager.register_folder(photo.source_folder)
        self._thumb_manager.queue_image(photo.path)
        self._exif_loader.queue_image(photo.path, photo.source_folder)

        # Check if it passes filter
        if self._passes_filter(photo):
            # Find insertion point to maintain sort order
            index = self._find_sorted_insertion_point(photo)
            self._filtered_photos.insert(index, photo)
            self._reindex_from(index)
            self.photo_added.emit(photo.path, index)
            return index

        return -1

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

        # Cleanup: delete metadata DB entry and thumbnail cache
        self._cleanup_photo_data(file_path, photo.source_folder)

        return former_index

    def _cleanup_photo_data(self, file_path: str, source_folder: str):
        """Clean up DB and cache data for a removed photo."""
        # Delete from metadata DB
        db = self._db_manager.get_db_for_folder(source_folder)
        db.delete_metadata(file_path)

        # Delete thumbnail cache files
        from .background.thumb_man import get_thumb_dir_for_folder

        thumb_dir = get_thumb_dir_for_folder(source_folder)
        basename = os.path.splitext(os.path.basename(file_path))[0]

        for suffix in ["_embedded.jpg", "_hq.jpg"]:
            cache_file = thumb_dir / f"{basename}{suffix}"
            if cache_file.exists():
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

    def set_filter(self, criteria: FilterCriteria | None):
        """Set the filter criteria.

        Args:
            criteria: Filter criteria, or None for no filter.
        """
        self._filter = criteria
        self._apply_filter_and_sort()
        self.photos_changed.emit()

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

            if self._filter.include_no_label and not photo_label:
                pass  # Matches "no label"
            elif photo_label and photo_label in self._filter.labels:
                pass  # Matches selected label
            else:
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

    def set_sort_order(self, order: SortOrder):
        """Set the sort order.

        Args:
            order: New sort order.
        """
        if self._sort_order != order:
            self._sort_order = order
            self._apply_filter_and_sort()
            self.sort_order_changed.emit(order)
            self.photos_changed.emit()

    def _get_sort_key(self, photo: ImageItem):
        """Get the sort key for a photo based on current sort order."""
        if self._sort_order == SortOrder.TIME_TAKEN:
            # Sort by time_taken, fallback to filename
            time_taken = None
            if photo.db_metadata:
                time_taken = photo.db_metadata.get(DBFields.TIME_TAKEN)
            # Use epoch 0 if no time, so they sort to beginning
            if time_taken is None:
                time_taken = datetime.min
            return (time_taken, photo.name.lower())

        elif self._sort_order == SortOrder.FILE_NAME:
            return photo.name.lower()

        elif self._sort_order == SortOrder.FILE_NAME_BY_FOLDER:
            return (photo.source_folder, photo.name.lower())

        return photo.name.lower()

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
        filtered.sort(key=self._get_sort_key)

        # Update indices
        for i, photo in enumerate(filtered):
            photo._global_index = i

        self._filtered_photos = filtered

    def _reindex_from(self, start_index: int):
        """Update _global_index for all photos from start_index onwards."""
        for i in range(start_index, len(self._filtered_photos)):
            self._filtered_photos[i]._global_index = i

    # --- Refresh ---

    def refresh_from_disk(self, root_folder: str) -> tuple[list[str], list[str]]:
        """Rescan folder and update model with changes.

        Args:
            root_folder: Root folder to scan.

        Returns:
            Tuple of (added_paths, removed_paths).
        """
        from .background.thumb_man import scan_folder

        # Scan disk
        new_images_data, new_folders = scan_folder(root_folder)

        # Build sets for comparison
        current_paths = {p.path for p in self._all_photos}
        new_paths = {d["path"] for d in new_images_data}

        # Find additions and removals
        added_paths = new_paths - current_paths
        removed_paths = current_paths - new_paths

        # Remove deleted photos
        for path in removed_paths:
            self.remove_photo(path)

        # Add new photos
        for data in new_images_data:
            if data["path"] in added_paths:
                photo = ImageItem(**data)
                self.add_photo(photo)

        # Update source folders
        self._source_folders = new_folders

        return list(added_paths), list(removed_paths)
