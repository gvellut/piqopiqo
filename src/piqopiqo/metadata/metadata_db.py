"""Metadata database management for photo metadata."""

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
import logging
import os
from pathlib import Path
import re
import sqlite3
import threading
from typing import Any

from PySide6.QtCore import QObject, Signal

from piqopiqo.cache_paths import get_cache_dir_for_folder
from piqopiqo.storage import storage_full_fault_from_error

from .db_fields import DBFields

logger = logging.getLogger(__name__)


_TRANSIENT_DB_ERROR_SNIPPETS = (
    "disk i/o error",
    "unable to open database file",
    "readonly database",
    "attempt to write a readonly database",
    "bad file descriptor",
)


@dataclass(frozen=True)
class MetadataDBFault:
    folder_path: str
    db_path: str
    operation: str
    error_message: str
    during_write: bool
    classification: str
    path_available: bool

    @property
    def is_transient(self) -> bool:
        return self.classification == "transient_unavailable"

    @property
    def is_storage_full(self) -> bool:
        return self.classification == "storage_full"


class MetadataDBUnavailableError(RuntimeError):
    """Raised when a DB write cannot complete because recovery is needed."""

    def __init__(self, fault: MetadataDBFault):
        self.fault = fault
        super().__init__(fault.error_message)


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

    def __init__(self, folder_path: str, *, manager=None):
        """Initialize the database manager for a folder.

        Note: Does not create the database file until first write.

        Args:
            folder_path: Path to the source folder.
        """
        self.folder_path = folder_path
        self.db_path = get_db_path_for_folder(folder_path)
        self._manager = manager
        self._connections: dict[int, sqlite3.Connection] = {}
        self._connections_lock = threading.Lock()

    def _ensure_db(self) -> sqlite3.Connection:
        """Create database file and tables if they don't exist.

        Returns:
            Database connection.
        """
        conn = self._get_connection(create=True)
        if conn is None:
            raise RuntimeError(f"Failed to create database connection: {self.db_path}")
        return conn

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
        self._run_db_operation(
            operation="ensure_manual_lens_columns",
            create=True,
            during_write=True,
            default=None,
            func=self._ensure_manual_lens_columns,
        )

    def _initialize_connection(self, connection: sqlite3.Connection) -> None:
        connection.row_factory = sqlite3.Row

        # Ensure schema exists for this connection
        connection.executescript(self.SCHEMA)
        connection.commit()
        self._check_migration(connection)

    def _open_connection(
        self, create: bool, *, cache_to_thread: bool
    ) -> sqlite3.Connection | None:
        if not create and not self.db_path.exists():
            return None

        if create:
            self.db_path.parent.mkdir(parents=True, exist_ok=True)

        connection = sqlite3.connect(str(self.db_path), check_same_thread=False)
        self._initialize_connection(connection)

        if cache_to_thread:
            with self._connections_lock:
                self._connections[threading.get_ident()] = connection
            logger.debug(
                "Opened database connection: %s (thread %s)",
                self.db_path,
                threading.get_ident(),
            )
        return connection

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
        return self._open_connection(create=create, cache_to_thread=True)

    def _get_readonly_connection(self) -> sqlite3.Connection | None:
        """Get a read-only connection if database exists.

        Returns:
            Database connection or None if database doesn't exist.
        """
        return self._get_connection(create=False)

    def _close_connection_for_thread(self, thread_id: int | None = None) -> None:
        target_thread_id = threading.get_ident() if thread_id is None else thread_id
        with self._connections_lock:
            connection = self._connections.pop(target_thread_id, None)
        if connection is None:
            return
        try:
            connection.close()
        except Exception:
            logger.debug(
                "Ignored error while closing database connection %s",
                self.db_path,
                exc_info=True,
            )

    def _quick_check_connection(
        self, connection: sqlite3.Connection
    ) -> tuple[bool, str]:
        row = connection.execute("PRAGMA quick_check").fetchone()
        if row is None:
            return False, "PRAGMA quick_check returned no result"
        message = str(row[0])
        return message == "ok", message

    @staticmethod
    def _probe_write_connection(connection: sqlite3.Connection) -> None:
        """Force and roll back a small write against the main database."""
        row = connection.execute("PRAGMA user_version").fetchone()
        current_version = int(row[0]) if row is not None else 0
        probe_version = 0 if current_version else 1
        try:
            connection.execute("BEGIN IMMEDIATE")
            connection.execute(f"PRAGMA user_version = {probe_version}")
            connection.rollback()
        except Exception:
            try:
                connection.rollback()
            except Exception:
                pass
            raise

    def _classify_open_failure(
        self,
        *,
        operation: str,
        exc: Exception,
        during_write: bool,
        path_available: bool,
    ) -> MetadataDBFault:
        message = str(exc) or exc.__class__.__name__
        lower_message = message.lower()
        classification = "unreadable_after_reconnect"
        storage_fault = storage_full_fault_from_error(
            exc,
            target_path=self.db_path.parent,
            operation=operation,
            confirm_ambiguous_sqlite=True,
        )
        if storage_fault is not None:
            classification = "storage_full"
        elif (not path_available) or any(
            snippet in lower_message for snippet in _TRANSIENT_DB_ERROR_SNIPPETS
        ):
            classification = "transient_unavailable"
        return MetadataDBFault(
            folder_path=self.folder_path,
            db_path=str(self.db_path),
            operation=operation,
            error_message=message,
            during_write=during_write,
            classification=classification,
            path_available=path_available,
        )

    def _attempt_reopen_after_failure(
        self,
        *,
        operation: str,
        during_write: bool,
        create: bool,
        expected_existing: bool,
    ) -> tuple[sqlite3.Connection | None, MetadataDBFault | None]:
        self._close_connection_for_thread()

        db_exists = self.db_path.exists()
        path_available = self.db_path.parent.exists() and (
            db_exists or not expected_existing
        )
        open_create = create and not expected_existing
        if not path_available and not open_create:
            return None, MetadataDBFault(
                folder_path=self.folder_path,
                db_path=str(self.db_path),
                operation=operation,
                error_message=f"Database path unavailable: {self.db_path}",
                during_write=during_write,
                classification="transient_unavailable",
                path_available=False,
            )

        try:
            connection = self._open_connection(
                create=open_create,
                cache_to_thread=True,
            )
            if connection is None:
                return None, MetadataDBFault(
                    folder_path=self.folder_path,
                    db_path=str(self.db_path),
                    operation=operation,
                    error_message=f"Database path unavailable: {self.db_path}",
                    during_write=during_write,
                    classification="transient_unavailable",
                    path_available=False,
                )
            quick_ok, quick_message = self._quick_check_connection(connection)
            if not quick_ok:
                self._close_connection_for_thread()
                return None, MetadataDBFault(
                    folder_path=self.folder_path,
                    db_path=str(self.db_path),
                    operation=operation,
                    error_message=quick_message,
                    during_write=during_write,
                    classification="unreadable_after_reconnect",
                    path_available=self.db_path.parent.exists()
                    and self.db_path.exists(),
                )
            return connection, None
        except (sqlite3.Error, OSError, RuntimeError) as reopen_exc:
            return None, self._classify_open_failure(
                operation=operation,
                exc=reopen_exc,
                during_write=during_write,
                path_available=self.db_path.parent.exists() and self.db_path.exists(),
            )

    def _report_fault(self, fault: MetadataDBFault) -> None:
        if self._manager is not None:
            self._manager.report_fault(fault)

    def _run_db_operation(
        self,
        *,
        operation: str,
        create: bool,
        during_write: bool,
        default: Any,
        func: Callable[[sqlite3.Connection], Any],
    ) -> Any:
        existing = None
        initial_exc: Exception | None = None
        try:
            existing = self._get_connection(create=create)
        except (sqlite3.Error, OSError, RuntimeError) as exc:
            initial_exc = exc
        expected_existing = existing is not None or self.db_path.exists()
        if existing is None and initial_exc is None:
            return default

        if initial_exc is None:
            try:
                return func(existing)
            except (sqlite3.Error, OSError, RuntimeError) as exc:
                logger.warning(
                    "Database operation failed for %s (%s): %s",
                    self.db_path,
                    operation,
                    exc,
                )
        else:
            logger.warning(
                "Database open failed for %s (%s): %s",
                self.db_path,
                operation,
                initial_exc,
            )

        reopened, fault = self._attempt_reopen_after_failure(
            operation=operation,
            during_write=during_write,
            create=create,
            expected_existing=expected_existing,
        )
        if reopened is not None:
            try:
                return func(reopened)
            except (sqlite3.Error, OSError, RuntimeError) as retry_exc:
                fault = self._classify_open_failure(
                    operation=operation,
                    exc=retry_exc,
                    during_write=during_write,
                    path_available=self.db_path.parent.exists()
                    and self.db_path.exists(),
                )
                self._close_connection_for_thread()

        if fault is None:
            fault = MetadataDBFault(
                folder_path=self.folder_path,
                db_path=str(self.db_path),
                operation=operation,
                error_message=f"Database operation failed: {operation}",
                during_write=during_write,
                classification="transient_unavailable",
                path_available=self.db_path.parent.exists() and self.db_path.exists(),
            )

        self._report_fault(fault)
        if during_write:
            raise MetadataDBUnavailableError(fault)
        return default

    def probe_health(
        self,
        *,
        allow_create: bool = False,
        require_write: bool = False,
    ) -> tuple[bool, MetadataDBFault | None]:
        """Probe whether the DB can be re-opened and passes quick_check."""
        self.close()
        reopened, fault = self._attempt_reopen_after_failure(
            operation="probe_health",
            during_write=False,
            create=allow_create,
            expected_existing=not allow_create,
        )
        if reopened is None:
            return False, fault
        if require_write:
            try:
                self._probe_write_connection(reopened)
            except (sqlite3.Error, OSError, RuntimeError) as exc:
                self._close_connection_for_thread()
                return False, self._classify_open_failure(
                    operation="probe_write_health",
                    exc=exc,
                    during_write=True,
                    path_available=self.db_path.parent.exists()
                    and self.db_path.exists(),
                )
        return True, None

    def get_metadata(self, file_path: str) -> dict | None:
        """Get metadata for a photo.

        Args:
            file_path: Full path to the image file.

        Returns:
            Dictionary with metadata or None if not found.
        """

        def _load(conn: sqlite3.Connection) -> dict | None:
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
                    time_taken_val = datetime.strptime(
                        time_taken_raw, "%Y-%m-%d %H:%M:%S"
                    )
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

        return self._run_db_operation(
            operation="get_metadata",
            create=False,
            during_write=False,
            default=None,
            func=_load,
        )

    def save_metadata(self, file_path: str, data: dict) -> None:
        """Save metadata for a photo.

        Creates the database file if it doesn't exist.

        Args:
            file_path: Full path to the image file.
            data: Dictionary with metadata fields.
        """

        def _save(conn: sqlite3.Connection) -> None:
            now = datetime.now().isoformat()
            file_name = os.path.basename(file_path)
            data_to_save = data.copy()

            # Convert datetime to ISO string for storage
            time_taken = data_to_save.get(DBFields.TIME_TAKEN)
            if isinstance(time_taken, datetime):
                data_to_save[DBFields.TIME_TAKEN] = time_taken.strftime(
                    "%Y-%m-%d %H:%M:%S"
                )

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
            logger.debug("Saved metadata for: %s", file_path)

        self._run_db_operation(
            operation="save_metadata",
            create=True,
            during_write=True,
            default=None,
            func=_save,
        )

    def update_title_and_keywords(
        self,
        file_path: str,
        changes: dict[str, str | None],
    ) -> bool:
        """Update only title/keywords on an existing metadata row."""
        allowed_fields = {DBFields.TITLE, DBFields.KEYWORDS}
        unsupported = set(changes) - allowed_fields
        if unsupported:
            raise ValueError(
                "Unsupported targeted metadata fields: "
                + ", ".join(sorted(unsupported))
            )
        ordered_fields = [
            field_name
            for field_name in (DBFields.TITLE, DBFields.KEYWORDS)
            if field_name in changes
        ]
        if not ordered_fields:
            return False

        def _update(conn: sqlite3.Connection) -> bool:
            assignments = ", ".join(
                f"{field_name} = ?" for field_name in ordered_fields
            )
            values = [changes[field_name] for field_name in ordered_fields]
            values.extend([datetime.now().isoformat(), file_path])
            cursor = conn.execute(
                f"UPDATE photo_metadata SET {assignments}, updated_at = ? "
                "WHERE file_path = ?",
                values,
            )
            conn.commit()
            return cursor.rowcount > 0

        return bool(
            self._run_db_operation(
                operation="update_title_and_keywords",
                create=False,
                during_write=True,
                default=False,
                func=_update,
            )
        )

    def has_metadata(self, file_path: str) -> bool:
        """Check if metadata exists for a photo.

        Args:
            file_path: Full path to the image file.

        Returns:
            True if metadata exists.
        """

        def _check(conn: sqlite3.Connection) -> bool:
            cursor = conn.execute(
                "SELECT 1 FROM photo_metadata WHERE file_path = ? LIMIT 1", (file_path,)
            )
            return cursor.fetchone() is not None

        return bool(
            self._run_db_operation(
                operation="has_metadata",
                create=False,
                during_write=False,
                default=False,
                func=_check,
            )
        )

    def has_exif_fields(self, file_path: str, field_keys: list[str]) -> bool:
        """Check if EXIF field records exist for a photo.

        A photo is considered complete only if every requested key has a row in
        photo_exif_fields (value may be NULL when not present in the file).
        """
        if not field_keys:
            return True

        def _check(conn: sqlite3.Connection) -> bool:
            placeholders = ",".join("?" for _ in field_keys)
            row = conn.execute(
                "SELECT COUNT(*) AS cnt FROM photo_exif_fields "
                f"WHERE file_path = ? AND field_key IN ({placeholders})",
                (file_path, *field_keys),
            ).fetchone()
            return row is not None and int(row["cnt"]) == len(field_keys)

        return bool(
            self._run_db_operation(
                operation="has_exif_fields",
                create=False,
                during_write=False,
                default=False,
                func=_check,
            )
        )

    def get_folder_value(self, data: str) -> str | None:
        """Get a folder-scoped metadata value.

        Args:
            data: Folder metadata key.

        Returns:
            Stored value or None.
        """

        def _load(conn: sqlite3.Connection) -> str | None:
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

        return self._run_db_operation(
            operation="get_folder_value",
            create=False,
            during_write=False,
            default=None,
            func=_load,
        )

    def set_folder_value(self, data: str, value: str | None) -> None:
        """Set or delete a folder-scoped metadata value.

        Args:
            data: Folder metadata key.
            value: Value to store, or None to delete.
        """

        def _save(conn: sqlite3.Connection) -> None:
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

        self._run_db_operation(
            operation="set_folder_value",
            create=True,
            during_write=True,
            default=None,
            func=_save,
        )

    def get_exif_fields(
        self, file_path: str, field_keys: list[str]
    ) -> dict[str, str | None] | None:
        """Get stored EXIF fields for a photo.

        Returns a mapping of field_key -> field_value (may be None).
        """

        def _load(conn: sqlite3.Connection) -> dict[str, str | None] | None:
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

        return self._run_db_operation(
            operation="get_exif_fields",
            create=False,
            during_write=False,
            default=None,
            func=_load,
        )

    def save_exif_fields(self, file_path: str, fields: dict[str, str | None]) -> None:
        """Upsert EXIF fields for a photo."""
        if not fields:
            return

        def _save(conn: sqlite3.Connection) -> None:
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

        self._run_db_operation(
            operation="save_exif_fields",
            create=True,
            during_write=True,
            default=None,
            func=_save,
        )

    def delete_exif_fields(self, file_path: str, keys: list[str] | None = None) -> None:
        """Delete stored EXIF fields for a photo.

        If keys is None, deletes all stored keys for the file.
        """

        def _delete(conn: sqlite3.Connection) -> None:
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

        self._run_db_operation(
            operation="delete_exif_fields",
            create=False,
            during_write=True,
            default=None,
            func=_delete,
        )

    def delete_metadata(self, file_path: str) -> None:
        """Delete metadata for a photo.

        Args:
            file_path: Full path to the image file.
        """

        def _delete(conn: sqlite3.Connection) -> None:
            conn.execute(
                "DELETE FROM photo_exif_fields WHERE file_path = ?", (file_path,)
            )
            conn.execute("DELETE FROM photo_metadata WHERE file_path = ?", (file_path,))
            conn.commit()

        self._run_db_operation(
            operation="delete_metadata",
            create=False,
            during_write=True,
            default=None,
            func=_delete,
        )

    def delete_all_metadata(self) -> None:
        """Delete all metadata entries from the database."""

        def _delete_all(conn: sqlite3.Connection) -> None:
            conn.execute("DELETE FROM photo_exif_fields")
            conn.execute("DELETE FROM photo_metadata")
            conn.execute("DELETE FROM folder_metadata")
            conn.commit()
            logger.info("Deleted all metadata for folder: %s", self.folder_path)

        self._run_db_operation(
            operation="delete_all_metadata",
            create=False,
            during_write=True,
            default=None,
            func=_delete_all,
        )

    def close(self) -> None:
        """Close the database connection."""
        with self._connections_lock:
            connections = list(self._connections.values())
            self._connections.clear()

        for connection in connections:
            connection.close()


class _MetadataDBManagerSignals(QObject):
    fault_reported = Signal(object)


class MetadataDBManager:
    """Manages MetadataDB instances for multiple folders."""

    def __init__(self):
        self._databases: dict[str, MetadataDB] = {}
        self.signals = _MetadataDBManagerSignals()

    def get_db_for_folder(self, folder_path: str) -> MetadataDB:
        """Get or create a MetadataDB for a folder.

        Args:
            folder_path: Path to the source folder.

        Returns:
            MetadataDB instance for the folder.
        """
        if folder_path not in self._databases:
            self._databases[folder_path] = MetadataDB(folder_path, manager=self)
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

    def report_fault(self, fault: MetadataDBFault) -> None:
        self.signals.fault_reported.emit(fault)

    def close_for_folder(self, folder_path: str) -> None:
        db = self._databases.get(folder_path)
        if db is None:
            return
        db.close()

    def probe_folder_health(
        self,
        folder_path: str,
        *,
        allow_create: bool = False,
        require_write: bool = False,
    ) -> tuple[bool, MetadataDBFault | None]:
        return self.get_db_for_folder(folder_path).probe_health(
            allow_create=allow_create,
            require_write=require_write,
        )

    def close_all(self) -> None:
        """Close all database connections."""
        for db in self._databases.values():
            db.close()
        self._databases.clear()
