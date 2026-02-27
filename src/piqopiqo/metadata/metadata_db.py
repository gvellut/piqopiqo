"""Metadata database management for photo metadata."""

from datetime import datetime
import logging
import os
from pathlib import Path
import re
import sqlite3
import threading

from piqopiqo.cache_paths import get_cache_dir_for_folder

from .db_fields import DBFields

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


def parse_exif_datetime(value: str) -> datetime | None:
    """Parse an EXIF datetime string to a datetime object.

    Args:
        value: EXIF format string (YYYY:MM:DD HH:MM:SS)

    Returns:
        datetime object or None if parsing fails.
    """
    if not value or not value.strip():
        return None
    try:
        return datetime.strptime(value.strip(), "%Y:%m:%d %H:%M:%S")
    except ValueError:
        return None


def validate_datetime(value: str) -> tuple[bool, datetime | None]:
    """Validate a datetime string (ISO or EXIF format).

    Args:
        value: String value to validate (YYYY-MM-DD HH:MM:SS or YYYY:MM:DD HH:MM:SS)

    Returns:
        Tuple of (is_valid, parsed datetime or None)
    """
    if not value or not value.strip():
        return True, None
    text = value.strip()
    # Try ISO format first (preferred display/edit format)
    try:
        return True, datetime.strptime(text, "%Y-%m-%d %H:%M:%S")
    except ValueError:
        pass
    # Also accept EXIF format
    try:
        return True, datetime.strptime(text, "%Y:%m:%d %H:%M:%S")
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
        time_taken TIMESTAMP,
        label TEXT,
        orientation INTEGER,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL
    );
    CREATE INDEX IF NOT EXISTS idx_file_path ON photo_metadata(file_path);

    CREATE TABLE IF NOT EXISTS photo_exif_fields (
        file_path TEXT NOT NULL,
        field_key TEXT NOT NULL,
        field_value TEXT,
        updated_at TEXT NOT NULL,
        PRIMARY KEY (file_path, field_key)
    );
    CREATE INDEX IF NOT EXISTS idx_exif_fields_file_path
        ON photo_exif_fields(file_path);

    CREATE TABLE IF NOT EXISTS folder_metadata (
        data TEXT PRIMARY KEY,
        value TEXT
    );
    """

    _MANUAL_LENS_COLUMN_TYPES = {
        DBFields.MANUAL_LENS_MAKE: "TEXT",
        DBFields.MANUAL_LENS_MODEL: "TEXT",
        DBFields.MANUAL_FOCAL_LENGTH: "TEXT",
        DBFields.MANUAL_FOCAL_LENGTH_35MM: "TEXT",
    }

    def __init__(self, folder_path: str):
        """Initialize the database manager for a folder.

        Note: Does not create the database file until first write.

        Args:
            folder_path: Path to the source folder.
        """
        self.folder_path = folder_path
        self.db_path = get_db_path_for_folder(folder_path)
        self._connections: dict[int, sqlite3.Connection] = {}
        self._connections_lock = threading.Lock()

    def _ensure_db(self) -> sqlite3.Connection:
        """Create database file and tables if they don't exist.

        Returns:
            Database connection.
        """
        return self._get_connection(create=True)

    def _check_migration(self, connection: sqlite3.Connection):
        """Check if database needs migration."""
        cursor = connection.execute("PRAGMA table_info(photo_metadata)")
        columns = {row[1]: row[2] for row in cursor.fetchall()}

        if "datetime_original" in columns and "time_taken" not in columns:
            logger.info("Migrating database: datetime_original -> time_taken")
            connection.execute(
                "ALTER TABLE photo_metadata"
                " RENAME COLUMN datetime_original TO time_taken"
            )
            connection.commit()

        # Add orientation column if it doesn't exist
        if "orientation" not in columns:
            logger.info("Migrating database: adding orientation column")
            connection.execute(
                "ALTER TABLE photo_metadata ADD COLUMN orientation INTEGER"
            )
            connection.commit()

        # Migrate EXIF-format dates (YYYY:MM:DD) to ISO format (YYYY-MM-DD)
        # This handles both old TEXT columns and newly declared TIMESTAMP columns
        cursor = connection.execute(
            "SELECT id, time_taken FROM photo_metadata "
            "WHERE time_taken IS NOT NULL AND time_taken LIKE '____:__:__%'"
        )
        rows = cursor.fetchall()
        if rows:
            logger.info(f"Migrating {len(rows)} time_taken values to ISO format")
            for row in rows:
                old_val = row["time_taken"]
                # Convert YYYY:MM:DD to YYYY-MM-DD in the date part
                if len(old_val) >= 10 and old_val[4] == ":" and old_val[7] == ":":
                    new_val = old_val[:10].replace(":", "-") + old_val[10:]
                    connection.execute(
                        "UPDATE photo_metadata SET time_taken = ? WHERE id = ?",
                        (new_val, row["id"]),
                    )
            connection.commit()

    def _get_photo_metadata_columns(self, connection: sqlite3.Connection) -> set[str]:
        cursor = connection.execute("PRAGMA table_info(photo_metadata)")
        return {str(row["name"]) for row in cursor.fetchall()}

    def _ensure_manual_lens_columns(self, connection: sqlite3.Connection) -> None:
        columns = self._get_photo_metadata_columns(connection)
        missing = [
            (column_name, column_type)
            for column_name, column_type in self._MANUAL_LENS_COLUMN_TYPES.items()
            if column_name not in columns
        ]
        if not missing:
            return

        for column_name, column_type in missing:
            logger.info("Migrating database: adding %s column", column_name)
            connection.execute(
                f"ALTER TABLE photo_metadata ADD COLUMN {column_name} {column_type}"
            )
        connection.commit()

    def ensure_manual_lens_columns(self) -> None:
        """Create hidden manual lens columns lazily when first needed."""
        conn = self._ensure_db()
        self._ensure_manual_lens_columns(conn)

    def _get_connection(self, create: bool) -> sqlite3.Connection | None:
        """Get a connection bound to the current thread.

        Args:
            create: If True, create the DB file and schema if missing.

        Returns:
            SQLite connection or None if DB doesn't exist and create is False.
        """
        thread_id = threading.get_ident()
        with self._connections_lock:
            existing = self._connections.get(thread_id)
        if existing is not None:
            return existing

        if not create and not self.db_path.exists():
            return None

        if create:
            self.db_path.parent.mkdir(parents=True, exist_ok=True)

        connection = sqlite3.connect(str(self.db_path), check_same_thread=False)
        connection.row_factory = sqlite3.Row

        # Ensure schema exists for this connection
        connection.executescript(self.SCHEMA)
        connection.commit()
        self._check_migration(connection)

        with self._connections_lock:
            self._connections[thread_id] = connection
        logger.debug(f"Opened database connection: {self.db_path} (thread {thread_id})")
        return connection

    def _get_readonly_connection(self) -> sqlite3.Connection | None:
        """Get a read-only connection if database exists.

        Returns:
            Database connection or None if database doesn't exist.
        """
        return self._get_connection(create=False)

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

        row_keys = set(row.keys())

        # Parse time_taken string to datetime object
        time_taken_raw = row[DBFields.TIME_TAKEN]
        if isinstance(time_taken_raw, str) and time_taken_raw:
            try:
                time_taken_val = datetime.strptime(time_taken_raw, "%Y-%m-%d %H:%M:%S")
            except ValueError:
                # Fallback: try EXIF format for un-migrated data
                time_taken_val = parse_exif_datetime(time_taken_raw)
        elif isinstance(time_taken_raw, datetime):
            time_taken_val = time_taken_raw
        else:
            time_taken_val = None

        return {
            DBFields.TITLE: row[DBFields.TITLE],
            DBFields.DESCRIPTION: row[DBFields.DESCRIPTION],
            DBFields.LATITUDE: row[DBFields.LATITUDE],
            DBFields.LONGITUDE: row[DBFields.LONGITUDE],
            DBFields.KEYWORDS: row[DBFields.KEYWORDS],
            DBFields.TIME_TAKEN: time_taken_val,
            DBFields.LABEL: row[DBFields.LABEL],
            DBFields.ORIENTATION: row[DBFields.ORIENTATION],
            DBFields.MANUAL_LENS_MAKE: (
                row[DBFields.MANUAL_LENS_MAKE]
                if DBFields.MANUAL_LENS_MAKE in row_keys
                else None
            ),
            DBFields.MANUAL_LENS_MODEL: (
                row[DBFields.MANUAL_LENS_MODEL]
                if DBFields.MANUAL_LENS_MODEL in row_keys
                else None
            ),
            DBFields.MANUAL_FOCAL_LENGTH: (
                row[DBFields.MANUAL_FOCAL_LENGTH]
                if DBFields.MANUAL_FOCAL_LENGTH in row_keys
                else None
            ),
            DBFields.MANUAL_FOCAL_LENGTH_35MM: (
                row[DBFields.MANUAL_FOCAL_LENGTH_35MM]
                if DBFields.MANUAL_FOCAL_LENGTH_35MM in row_keys
                else None
            ),
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
        data_to_save = data.copy()

        # Convert datetime to ISO string for storage
        time_taken = data_to_save.get(DBFields.TIME_TAKEN)
        if isinstance(time_taken, datetime):
            data_to_save[DBFields.TIME_TAKEN] = time_taken.strftime("%Y-%m-%d %H:%M:%S")

        if any(field in data_to_save for field in DBFields.MANUAL_LENS_FIELDS):
            self._ensure_manual_lens_columns(conn)

        columns = self._get_photo_metadata_columns(conn)
        has_manual_lens_columns = all(
            field in columns for field in DBFields.MANUAL_LENS_FIELDS
        )

        # Check if entry exists
        cursor = conn.execute(
            "SELECT * FROM photo_metadata WHERE file_path = ?", (file_path,)
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
                    orientation = ?,
                    updated_at = ?
                WHERE file_path = ?
                """,
                (
                    data_to_save.get(DBFields.TITLE),
                    data_to_save.get(DBFields.DESCRIPTION),
                    data_to_save.get(DBFields.LATITUDE),
                    data_to_save.get(DBFields.LONGITUDE),
                    data_to_save.get(DBFields.KEYWORDS),
                    data_to_save.get(DBFields.TIME_TAKEN),
                    data_to_save.get(DBFields.LABEL),
                    data_to_save.get(DBFields.ORIENTATION),
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
                 keywords, time_taken, label, orientation, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    file_path,
                    file_name,
                    data_to_save.get(DBFields.TITLE),
                    data_to_save.get(DBFields.DESCRIPTION),
                    data_to_save.get(DBFields.LATITUDE),
                    data_to_save.get(DBFields.LONGITUDE),
                    data_to_save.get(DBFields.KEYWORDS),
                    data_to_save.get(DBFields.TIME_TAKEN),
                    data_to_save.get(DBFields.LABEL),
                    data_to_save.get(DBFields.ORIENTATION),
                    now,
                    now,
                ),
            )

        if has_manual_lens_columns:
            existing_keys = set(existing.keys()) if existing is not None else set()
            manual_values = []
            for field in DBFields.MANUAL_LENS_FIELDS:
                if field in data_to_save:
                    manual_values.append(data_to_save.get(field))
                elif field in existing_keys:
                    manual_values.append(existing[field])
                else:
                    manual_values.append(None)

            conn.execute(
                f"""
                UPDATE photo_metadata SET
                    {DBFields.MANUAL_LENS_MAKE} = ?,
                    {DBFields.MANUAL_LENS_MODEL} = ?,
                    {DBFields.MANUAL_FOCAL_LENGTH} = ?,
                    {DBFields.MANUAL_FOCAL_LENGTH_35MM} = ?,
                    updated_at = ?
                WHERE file_path = ?
                """,
                (*manual_values, now, file_path),
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

    def has_exif_fields(self, file_path: str, field_keys: list[str]) -> bool:
        """Check if EXIF field records exist for a photo.

        A photo is considered complete only if every requested key has a row in
        photo_exif_fields (value may be NULL when not present in the file).
        """
        if not field_keys:
            return True

        conn = self._get_readonly_connection()
        if conn is None:
            return False

        placeholders = ",".join("?" for _ in field_keys)
        row = conn.execute(
            "SELECT COUNT(*) AS cnt FROM photo_exif_fields "
            f"WHERE file_path = ? AND field_key IN ({placeholders})",
            (file_path, *field_keys),
        ).fetchone()
        return row is not None and int(row["cnt"]) == len(field_keys)

    def get_folder_value(self, data: str) -> str | None:
        """Get a folder-scoped metadata value.

        Args:
            data: Folder metadata key.

        Returns:
            Stored value or None.
        """
        conn = self._get_readonly_connection()
        if conn is None:
            return None

        row = conn.execute(
            "SELECT value FROM folder_metadata WHERE data = ?",
            (str(data),),
        ).fetchone()
        if row is None:
            return None
        value = row["value"]
        if value is None:
            return None
        return str(value)

    def set_folder_value(self, data: str, value: str | None) -> None:
        """Set or delete a folder-scoped metadata value.

        Args:
            data: Folder metadata key.
            value: Value to store, or None to delete.
        """
        conn = self._ensure_db()
        key = str(data)
        if value is None:
            conn.execute("DELETE FROM folder_metadata WHERE data = ?", (key,))
            conn.commit()
            return

        conn.execute(
            """
            INSERT INTO folder_metadata (data, value)
            VALUES (?, ?)
            ON CONFLICT(data) DO UPDATE SET
                value = excluded.value
            """,
            (key, str(value)),
        )
        conn.commit()

    def get_exif_fields(
        self, file_path: str, field_keys: list[str]
    ) -> dict[str, str | None] | None:
        """Get stored EXIF fields for a photo.

        Returns a mapping of field_key -> field_value (may be None).
        """
        conn = self._get_readonly_connection()
        if conn is None:
            return None

        if not field_keys:
            return {}

        placeholders = ",".join("?" for _ in field_keys)
        cursor = conn.execute(
            "SELECT field_key, field_value FROM photo_exif_fields "
            f"WHERE file_path = ? AND field_key IN ({placeholders})",
            (file_path, *field_keys),
        )
        rows = cursor.fetchall()
        if not rows:
            return None

        return {row["field_key"]: row["field_value"] for row in rows}

    def save_exif_fields(self, file_path: str, fields: dict[str, str | None]) -> None:
        """Upsert EXIF fields for a photo."""
        if not fields:
            return

        conn = self._ensure_db()
        now = datetime.now().isoformat()

        for key, value in fields.items():
            conn.execute(
                """
                INSERT INTO photo_exif_fields (
                    file_path, field_key, field_value, updated_at
                )
                VALUES (?, ?, ?, ?)
                ON CONFLICT(file_path, field_key) DO UPDATE SET
                    field_value = excluded.field_value,
                    updated_at = excluded.updated_at
                """,
                (file_path, key, value, now),
            )

        conn.commit()

    def delete_exif_fields(self, file_path: str, keys: list[str] | None = None) -> None:
        """Delete stored EXIF fields for a photo.

        If keys is None, deletes all stored keys for the file.
        """
        conn = self._get_readonly_connection()
        if conn is None:
            return

        if not keys:
            conn.execute(
                "DELETE FROM photo_exif_fields WHERE file_path = ?", (file_path,)
            )
            conn.commit()
            return

        placeholders = ",".join("?" for _ in keys)
        conn.execute(
            "DELETE FROM photo_exif_fields WHERE file_path = ? "
            f"AND field_key IN ({placeholders})",
            (file_path, *keys),
        )
        conn.commit()

    def delete_metadata(self, file_path: str) -> None:
        """Delete metadata for a photo.

        Args:
            file_path: Full path to the image file.
        """
        conn = self._get_readonly_connection()
        if conn is None:
            return

        conn.execute("DELETE FROM photo_exif_fields WHERE file_path = ?", (file_path,))
        conn.execute("DELETE FROM photo_metadata WHERE file_path = ?", (file_path,))
        conn.commit()

    def delete_all_metadata(self) -> None:
        """Delete all metadata entries from the database."""
        conn = self._get_readonly_connection()
        if conn is None:
            return

        conn.execute("DELETE FROM photo_exif_fields")
        conn.execute("DELETE FROM photo_metadata")
        conn.execute("DELETE FROM folder_metadata")
        conn.commit()
        logger.info(f"Deleted all metadata for folder: {self.folder_path}")

    def close(self) -> None:
        """Close the database connection."""
        with self._connections_lock:
            connections = list(self._connections.values())
            self._connections.clear()

        for connection in connections:
            connection.close()


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

    def ensure_items_metadata_ready(self, items) -> bool:
        """Ensure editable DB metadata exists for all items.

        Returns False if any item is still missing metadata (EXIF not read yet).
        """
        for item in items:
            if item.db_metadata is not None:
                continue
            db = self.get_db_for_image(item.path)
            meta = db.get_metadata(item.path)
            if meta is None:
                return False
            item.db_metadata = meta.copy()
        return True

    def delete_all_metadata(self) -> None:
        """Delete all metadata from all registered databases."""
        for db in self._databases.values():
            db.delete_all_metadata()

    def close_all(self) -> None:
        """Close all database connections."""
        for db in self._databases.values():
            db.close()
        self._databases.clear()
