"""Application state persistence using QSettings."""

from enum import StrEnum
import json
import logging

from PySide6.QtCore import QByteArray, QSettings

logger = logging.getLogger(__name__)

# Application identity constants (used by QCoreApplication and support paths)
APP_NAME = "PiqoPiqo"
ORG_NAME = "PiqoPiqo"
ORG_DOMAIN = "piqopiqo.app"


class StateGroup(StrEnum):
    AppState = "AppState"
    Qt = "AppState/Qt"


class StateKey(StrEnum):
    # AppState group
    lastFolder = "lastFolder"
    copySdEject = "copySdEject"
    copySdNameSuffix = "copySdNameSuffix"
    copySdDateSpec = "copySdDateSpec"
    # AppState/Qt group
    windowGeometry = "windowGeometry"
    windowState = "windowState"
    mainSplitter = "mainSplitter"
    rightSplitter = "rightSplitter"


# Default values for each state key.
# The type is inferred from the default (None defaults are treated as str).
STATE_DEFAULTS: dict[StateKey, object] = {
    StateKey.lastFolder: None,
    StateKey.copySdEject: True,
    StateKey.copySdNameSuffix: "",
    StateKey.copySdDateSpec: "since:last",
    StateKey.windowGeometry: QByteArray(),
    StateKey.windowState: QByteArray(),
    StateKey.mainSplitter: QByteArray(),
    StateKey.rightSplitter: QByteArray(),
}

# Which QSettings group each key belongs to.
_KEY_GROUPS: dict[StateKey, StateGroup] = {
    StateKey.lastFolder: StateGroup.AppState,
    StateKey.copySdEject: StateGroup.AppState,
    StateKey.copySdNameSuffix: StateGroup.AppState,
    StateKey.copySdDateSpec: StateGroup.AppState,
    StateKey.windowGeometry: StateGroup.Qt,
    StateKey.windowState: StateGroup.Qt,
    StateKey.mainSplitter: StateGroup.Qt,
    StateKey.rightSplitter: StateGroup.Qt,
}


class StateStore:
    """Abstraction over QSettings for typed state persistence.

    Supports a ``dyn`` mode where all reads/writes are in-memory only
    (nothing is persisted to disk).
    """

    def __init__(self, dyn: bool = False):
        self._dyn = dyn
        self._memory: dict[str, object] = {}

        if not dyn:
            self._settings = QSettings()
        else:
            self._settings = None

    def get(self, key: StateKey):
        """Read a state value. Returns the typed value or the default."""
        group = _KEY_GROUPS[key]
        default = STATE_DEFAULTS[key]
        typ = type(default) if default is not None else str
        full_key = f"{group}/{key}"

        # In-memory cache (values set this session)
        if full_key in self._memory:
            return self._memory[full_key]

        # In dyn mode, return default directly
        if self._dyn:
            return default

        # Read from QSettings with explicit type
        if default is None:
            # None-default keys: stored as "" in QSettings, returned as None if empty
            value = self._settings.value(full_key, defaultValue="", type=str)
            return value if value != "" else None
        elif typ is QByteArray:
            return self._settings.value(full_key, defaultValue=default, type=QByteArray)
        elif typ is bool:
            return self._settings.value(full_key, defaultValue=default, type=bool)
        elif typ is int:
            return self._settings.value(full_key, defaultValue=default, type=int)
        elif typ is float:
            return self._settings.value(full_key, defaultValue=default, type=float)
        elif typ in (dict, list, tuple):
            raw = self._settings.value(full_key, defaultValue="", type=str)
            if not raw:
                return default
            try:
                return json.loads(raw)
            except (json.JSONDecodeError, TypeError):
                return default
        else:
            return self._settings.value(full_key, defaultValue=default, type=str)

    def set(self, key: StateKey, value):
        """Write a state value. In dyn mode, only updates in-memory cache."""
        group = _KEY_GROUPS[key]
        default = STATE_DEFAULTS[key]
        typ = type(default) if default is not None else str
        full_key = f"{group}/{key}"

        self._memory[full_key] = value

        if self._dyn:
            return

        # Serialize for QSettings
        if value is None:
            self._settings.setValue(full_key, "")
        elif typ in (dict, list, tuple):
            self._settings.setValue(full_key, json.dumps(value))
        else:
            self._settings.setValue(full_key, value)


# Module-level singleton
_store: StateStore | None = None


def init_state(dyn: bool = False) -> StateStore:
    """Initialize the global StateStore. Call once after QCoreApplication setup."""
    global _store
    _store = StateStore(dyn=dyn)
    return _store


def get_state() -> StateStore:
    """Return the global StateStore instance."""
    if _store is None:
        raise RuntimeError("State not initialized. Call init_state() first.")
    return _store
