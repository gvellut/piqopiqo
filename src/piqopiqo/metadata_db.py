"""Metadata database management for photo metadata."""

from datetime import datetime
import logging
import os
from pathlib import Path
import re
import sqlite3

from .db_fields import DBFields
from .thumb_man import get_cache_dir_for_folder

logger = logging.getLogger(__name__)


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
        time_taken TEXT,
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

            # Check for migration from old schema
            self._check_migration()

            logger.debug(f"Created/opened database: {self.db_path}")

        return self._connection

    def _check_migration(self):
        """Check if database needs migration from datetime_original to time_taken."""
        if self._connection is None:
            return

        cursor = self._connection.execute("PRAGMA table_info(photo_metadata)")
        columns = [row[1] for row in cursor.fetchall()]

        if "datetime_original" in columns and "time_taken" not in columns:
            logger.info("Migrating database: datetime_original -> time_taken")
            self._connection.execute(
                "ALTER TABLE photo_metadata RENAME COLUMN datetime_original TO time_taken"
            )
            self._connection.commit()

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

        # Check for migration
        self._check_migration()

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
            DBFields.TITLE: row[DBFields.TITLE],
            DBFields.DESCRIPTION: row[DBFields.DESCRIPTION],
            DBFields.LATITUDE: row[DBFields.LATITUDE],
            DBFields.LONGITUDE: row[DBFields.LONGITUDE],
            DBFields.KEYWORDS: row[DBFields.KEYWORDS],
            DBFields.TIME_TAKEN: row[DBFields.TIME_TAKEN],
            DBFields.LABEL: row[DBFields.LABEL],
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
                    time_taken = ?,
                    label = ?,
                    updated_at = ?
                WHERE file_path = ?
                """,
                (
                    data.get(DBFields.TITLE),
                    data.get(DBFields.DESCRIPTION),
                    data.get(DBFields.LATITUDE),
                    data.get(DBFields.LONGITUDE),
                    data.get(DBFields.KEYWORDS),
                    data.get(DBFields.TIME_TAKEN),
                    data.get(DBFields.LABEL),
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
                 keywords, time_taken, label, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    file_path,
                    file_name,
                    data.get(DBFields.TITLE),
                    data.get(DBFields.DESCRIPTION),
                    data.get(DBFields.LATITUDE),
                    data.get(DBFields.LONGITUDE),
                    data.get(DBFields.KEYWORDS),
                    data.get(DBFields.TIME_TAKEN),
                    data.get(DBFields.LABEL),
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
