"""Typed state and settings persistence using QSettings."""

from __future__ import annotations

from collections.abc import Callable
from copy import deepcopy
from enum import Enum, StrEnum, auto
import json
import logging
import os
from pathlib import Path
import shutil
from typing import Any

from attrs import define
from PySide6.QtCore import QByteArray, QSettings

from piqopiqo.color_management import ScreenColorProfileMode
from piqopiqo.model import (
    ExifField,
    ManualLensPreset,
    MapLinkOption,
    OnFullscreenExitMultipleSelected,
    StatusLabel,
    TimeShiftOcrProvider,
)
from piqopiqo.photo_model import SortOrder
from piqopiqo.shortcuts import Shortcut

logger = logging.getLogger(__name__)


# Application identity constants (used by QCoreApplication and support paths)
APP_NAME = "PiqoPiqo"
ORG_NAME = "Guilhem V"
ORG_DOMAIN = "vellut"  # com. is added by Qt

ENV_PREFIX = "PIQO_"


class SettingsPanelSaveMode(Enum):
    AUTOSAVE = auto()
    SAVE_CANCEL = auto()


class StateGroup(StrEnum):
    APP_STATE = "AppState"
    QT = "AppState/Qt"


class SettingsGroup(StrEnum):
    SETTINGS = "Settings"


class StateKey(StrEnum):
    # AppState group
    LAST_FOLDER = "lastFolder"
    RECENT_FOLDERS = "recentFolders"
    LAST_GPX_FOLDER = "lastGpxFolder"
    ARCHIVE_SAVE_EXIF = "archiveSaveExif"
    SORT_ORDER = "sortOrder"
    COPY_SD_EJECT = "copySDEject"
    COPY_SD_NAME_SUFFIX = "copySdNameSuffix"
    COPY_SD_DATE_SPEC = "copySdDateSpec"
    LAST_TIMESHIFT_BY_FOLDERS = "lastTimeshiftByFolders"
    LAST_TIMESHIFT = "lastTimeshift"
    NUM_COLUMNS = "numColumns"
    # AppState/Qt group
    WINDOW_GEOMETRY = "windowGeometry"
    WINDOW_STATE = "windowState"
    MAIN_SPLITTER = "mainSplitter"
    RIGHT_SPLITTER = "rightSplitter"


class UserSettingKey(StrEnum):
    CACHE_BASE_DIR = "cacheBaseDir"
    EXIFTOOL_PATH = "exiftoolPath"
    CUSTOM_EXIF_FIELDS = "customExifFields"
    ON_FULLSCREEN_EXIT_SELECTION_MODE = "onFullscreenExit"
    FORCE_SRGB = "forceSrgb"
    SCREEN_COLOR_PROFILE = "screenColorProfile"
    FAVORITE_FOLDER = "favoriteFolder"
    SHOW_DESCRIPTION_FIELD = "showDescriptionField"
    SHOW_HIDDEN_METADATA_FIELDS_IF_NOT_EMPTY = "showHiddenMetadataFieldsIfNotEmpty"
    PROTECT_NON_TEXT_METADATA = "protectNonTextMetadata"
    MAP_LINKS = "mapLinks"
    STATUS_LABELS = "statusLabels"
    EXTERNAL_VIEWER = "externalViewer"
    EXTERNAL_EDITOR = "externalEditor"
    SHORTCUTS = "shortcuts"
    FILTER_IN_FULLSCREEN = "filterInFullscreen"
    COPY_SD_BASE_EXTERNAL_FOLDER = "copySdBaseExternalFolder"
    ARCHIVE_DESTINATION = "archiveDestination"
    SDCARD_NAMES = "sdcardNames"
    GPX_TIMEZONE = "gpxTimezone"
    GPX_IGNORE_OFFSET = "gpxIgnoreOffset"
    GPX_KML_FOLDER = "gpxKmlFolder"
    TIME_SHIFT_UNKNOWN_FOLDER_IGNORE = "timeShiftUnknownFolderIgnore"
    GCP_PROJECT = "gcpProject"
    GCP_SA_KEY_PATH = "gcpSaKeyPath"
    FLICKR_API_KEY = "flickrApiKey"
    FLICKR_API_SECRET = "flickrApiSecret"
    FLICKR_UPLOAD_LABEL = "flickrUploadLabel"
    FLICKR_UPLOAD_REQUIRE_TITLE_AND_KEYWORDS = "flickrUploadRequireTitleAndKeywords"
    MANUAL_LENSES = "manualLenses"


class RuntimeSettingKey(StrEnum):
    DETACHED_KEYWORD_TREE = "detachedKeywordTree"
    INITIAL_RESOLUTION = "initialResolution"
    RECENT_FOLDERS_MENU_LIMIT = "recentFoldersMenuLimit"
    OCR_TIME_SHIFT_PROVIDER = "ocrTimeShiftProvider"
    TIME_TAKEN_LOAD_RESORT_BATCH_SIZE = "timeTakenLoadResortBatchSize"
    EXIF_PANEL_COLUMN_STRETCH = "exifPanelColumnStretch"
    EXIF_PANEL_ROW_SPACING = "exifPanelRowSpacing"
    SETTINGS_PANEL_ROW_SPACING = "settingsPanelRowSpacing"
    GRID_ITEM_SHOW_LABEL_SWATCH = "gridItemShowLabelSwatch"
    EXIF_AUTO_FORMAT = "exifAutoFormat"
    MAX_WORKERS = "maxWorkers"
    TIMESHIFT_CACHE_NUM = "timeshiftCacheNum"
    FLICKR_UPLOAD_MAX_WORKERS = "flickrUploadMaxWorkers"
    MIN_IDLE_WORKERS = "minIdleWorkers"
    MAX_EXIFTOOLS_IMAGE_BATCH = "maxExiftoolsImageBatch"
    SHUTDOWN_TIMEOUT_S = "shutdownTimeoutS"
    COPY_SD_EJECT_TIMEOUT_S = "copySdEjectTimeoutS"
    PADDING = "padding"
    FONT_SIZE = "fontSize"
    GRID_ITEM_TEXT_FIELDS_TOP_PADDING = "gridItemTextFieldsTopPadding"
    GRID_THUMB_BUFFER_ROWS = "gridThumbBufferRows"
    GRID_EMBEDDED_BUFFER_ROWS = "gridEmbeddedBufferRows"
    GRID_HQ_THUMB_DELAY_ENABLED = "gridHqThumbDelayEnabled"
    GRID_HQ_THUMB_LOAD_DELAY_MS = "gridHqThumbLoadDelayMs"
    GRID_NUM_COLUMNS_MIN = "gridNumColumnsMin"
    GRID_NUM_COLUMNS_MAX = "gridNumColumnsMax"
    GRID_LOWRES_ONLY = "gridLowresOnly"
    STATUS_BAR_SIDE_PADDING = "statusBarSidePadding"
    COLOR_MANAGE_EMBEDDED_THUMBNAILS = "colorManageEmbeddedThumbnails"
    COLOR_MANAGE_HQ_THUMBNAILS = "colorManageHqThumbnails"
    PILLOW_FOR_EXTRACT_IMAGE_COLOR_PROFILE = "pillowForExtractImageColorProfile"
    ZOOM_WHEEL_SENSITIVITY = "zoomWheelSensitivity"
    PAN_EMPTY_SPACE = "panEmptySpace"
    PAN_CURSOR_DELAY_MS = "panCursorDelayMs"
    INFO_PANEL_BACKGROUND_COLOR = "infoPanelBackgroundColor"
    INFO_PANEL_BACKGROUND_TRANSPARENCY = "infoPanelBackgroundTransparency"
    INFO_PANEL_TEXT_COLOR = "infoPanelTextColor"
    INFO_PANEL_MARGIN_BOTTOM = "infoPanelMarginBottom"
    INFO_PANEL_MARGIN_SIDE = "infoPanelMarginSide"
    INFO_PANEL_POSITION = "infoPanelPosition"
    INFO_PANEL_ZOOM_PERCENT_OVERLAY_TIMER_MS = "infoPanelZoomPercentOverlayTimerMs"
    SHOW_EDIT_PANEL = "showEditPanel"
    TITLE_MAX_LENGTH = "titleMaxLength"
    DESCRIPTION_MAX_LENGTH = "descriptionMaxLength"
    GRID_ITEM_FIELDS = "gridItemFields"
    EXIF_FIELDS = "exifFields"
    THUMB_MAX_DIM = "thumbMaxDim"
    GRID_BACKGROUND_COLOR = "gridBackgroundColor"
    GRID_BORDER_COLOR = "gridBorderColor"
    FULLSCREEN_BACKGROUND_COLOR = "fullscreenBackgroundColor"
    CLEAR_CACHE_ON_START = "clearCacheOnStart"
    SETTINGS_PANEL_SAVE_MODE = "settingsPanelSaveMode"


@define(frozen=True)
class SettingDef:
    default: object = None
    read_type: type = str
    json_storage: bool = False
    serializer: Callable[[Any], Any] | None = None
    deserializer: Callable[[Any], Any] | None = None
    env_parser: Callable[[str], Any] | None = None
    group: StateGroup | SettingsGroup | None = None


class MandatorySettingInputKind(Enum):
    DIRECTORY = auto()
    EXECUTABLE_PATH = auto()
    TEXT = auto()


@define(frozen=True)
class MandatorySettingSpec:
    key: UserSettingKey
    label: str
    input_kind: MandatorySettingInputKind
    can_create: bool
    validator: Callable[[str], bool]
    default_resolver: Callable[[], str | None] | None = None


@define(frozen=True)
class PendingMandatorySetting:
    spec: MandatorySettingSpec
    current_value: str
    auto_value: str | None
    is_empty: bool


def _parse_bool(raw: str) -> bool:
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _parse_json(raw: str) -> Any:
    return json.loads(raw)


def _parse_list_of_str(raw: str) -> list[str]:
    text = raw.strip()
    if not text:
        return []
    if text.startswith("["):
        data = _parse_json(text)
        if not isinstance(data, list):
            raise ValueError("Expected list JSON")
        return [str(x) for x in data]
    return [part.strip() for part in raw.split(",") if part.strip()]


def _normalize_optional_text(value: object) -> str:
    if value is None:
        return ""
    return str(value).strip()


def _validate_existing_directory(value: str) -> bool:
    path = value.strip()
    return bool(path) and os.path.isdir(path)


def _validate_executable_path(value: str) -> bool:
    path = value.strip()
    return bool(path) and os.access(path, os.F_OK | os.X_OK)


def _resolve_default_cache_base_dir_macos() -> str:
    return str(default_cache_base_dir_candidate_macos())


def _resolve_default_exiftool_path_macos() -> str | None:
    homebrew_path = "/opt/homebrew/bin/exiftool"
    if _validate_executable_path(homebrew_path):
        return homebrew_path

    which_path = shutil.which("exiftool")
    if not which_path:
        return None
    if not _validate_executable_path(which_path):
        return None
    return str(Path(which_path).resolve())


_list_of_strings_params = {
    "read_type": str,
    "json_storage": True,
    "serializer": lambda x: [str(v) for v in x],
    "deserializer": lambda x: [str(v) for v in x] if isinstance(x, list) else [],
    "env_parser": _parse_list_of_str,
}


def _serialize_status_labels(value: list[StatusLabel]) -> list[dict[str, Any]]:
    return [
        {
            "name": item.name,
            "color": item.color,
            "index": int(item.index),
        }
        for item in value
    ]


def _deserialize_status_labels(data: Any) -> list[StatusLabel]:
    if not isinstance(data, list):
        raise ValueError("Expected a list for status labels")
    out: list[StatusLabel] = []
    for row in data:
        if not isinstance(row, dict):
            continue
        out.append(
            StatusLabel(
                name=str(row.get("name", "")).strip(),
                color=str(row.get("color", "")).strip(),
                index=int(row.get("index", 0)),
            )
        )
    return out


def _serialize_manual_lenses(value: list[ManualLensPreset]) -> list[dict[str, str]]:
    out: list[dict[str, str]] = []
    for preset in value:
        out.append({
            "lens_make": str(preset.lens_make).strip(),
            "lens_model": str(preset.lens_model).strip(),
            "focal_length": str(preset.focal_length).strip(),
            "focal_length_35mm": str(preset.focal_length_35mm).strip(),
        })
    return out


def _deserialize_manual_lenses(data: Any) -> list[ManualLensPreset]:
    if not isinstance(data, list):
        raise ValueError("Expected a list for manual lenses")

    out: list[ManualLensPreset] = []
    for row in data:
        if not isinstance(row, dict):
            continue
        out.append(
            ManualLensPreset(
                lens_make=str(row.get("lens_make", "")).strip(),
                lens_model=str(row.get("lens_model", "")).strip(),
                focal_length=str(row.get("focal_length", "")).strip(),
                focal_length_35mm=str(row.get("focal_length_35mm", "")).strip(),
            )
        )
    return out


def _serialize_map_links(value: list[MapLinkOption]) -> list[dict[str, str]]:
    out: list[dict[str, str]] = []
    for option in value:
        out.append({
            "name": str(option.name).strip(),
            "url_template": str(option.url_template).strip(),
        })
    return out


def _deserialize_map_links(data: Any) -> list[MapLinkOption]:
    if not isinstance(data, list):
        raise ValueError("Expected a list for map links")

    out: list[MapLinkOption] = []
    for row in data:
        if not isinstance(row, dict):
            continue
        out.append(
            MapLinkOption(
                name=str(row.get("name", "")).strip(),
                url_template=str(row.get("url_template", "")).strip(),
            )
        )
    return out


def _deserialize_exif_fields(data: Any) -> list[ExifField]:
    if not isinstance(data, list):
        raise ValueError("Expected a list for exif fields")
    out: list[ExifField] = []
    for row in data:
        if not isinstance(row, dict):
            continue
        label = row.get("label")
        if label is not None:
            label = str(label)
        fmt = row.get("format")
        if fmt is not None:
            fmt = str(fmt).strip() or None
        out.append(
            ExifField(
                key=str(row.get("key", "")),
                label=label,
                format=fmt,
            )
        )
    return out


def _serialize_shortcuts(value: dict[Shortcut, str] | dict[str, str]) -> dict[str, str]:
    out: dict[str, str] = {}
    for key, shortcut in value.items():
        if isinstance(key, Shortcut):
            k = key.name
        else:
            k = str(key)
        out[k] = str(shortcut)
    return out


def _deserialize_shortcuts(data: Any) -> dict[Shortcut, str]:
    if not isinstance(data, dict):
        raise ValueError("Expected an object for shortcuts")

    out: dict[Shortcut, str] = {}
    for raw_key, raw_value in data.items():
        key_str = str(raw_key)
        shortcut = str(raw_value)

        key = None
        try:
            key = Shortcut[key_str]
        except KeyError:
            key = None

        if key is not None:
            out[key] = shortcut

    return out


def _serialize_on_fullscreen_exit_selection_mode(
    value: OnFullscreenExitMultipleSelected | str,
) -> str:
    if isinstance(value, OnFullscreenExitMultipleSelected):
        return value.name
    return str(value)


def _deserialize_on_fullscreen_exit_selection_mode(
    data: Any,
) -> OnFullscreenExitMultipleSelected:
    raw = str(data)
    try:
        return OnFullscreenExitMultipleSelected[raw]
    except KeyError:
        return OnFullscreenExitMultipleSelected.KEEP_SELECTION


def _serialize_screen_color_profile_mode(
    value: ScreenColorProfileMode | str,
) -> str:
    if isinstance(value, ScreenColorProfileMode):
        return value.name
    return str(value)


def _deserialize_screen_color_profile_mode(data: Any) -> ScreenColorProfileMode:
    raw = str(data)
    try:
        return ScreenColorProfileMode[raw]
    except KeyError:
        return ScreenColorProfileMode.FROM_MAIN_SCREEN


def _deserialize_time_shift_ocr_provider(data: Any) -> TimeShiftOcrProvider:
    raw = str(data)
    try:
        return TimeShiftOcrProvider[raw]
    except KeyError:
        return _RUNTIME_SETTING_REGISTRY[
            RuntimeSettingKey.OCR_TIME_SHIFT_PROVIDER
        ].default


def _deserialize_column_stretch(data: Any) -> tuple[int, int]:
    if isinstance(data, list) and len(data) >= 2:
        return (int(data[0]), int(data[1]))
    if isinstance(data, tuple) and len(data) >= 2:
        return (int(data[0]), int(data[1]))
    raise ValueError("Invalid EXIF panel column stretch")


def _parse_enum(env_value: str, enum_type: type[Enum], fallback: Enum) -> Enum:
    try:
        return enum_type[env_value]
    except KeyError:
        return fallback


_STATE_REGISTRY: dict[StateKey, SettingDef] = {
    StateKey.LAST_FOLDER: SettingDef(group=StateGroup.APP_STATE, read_type=str),
    StateKey.RECENT_FOLDERS: SettingDef(
        group=StateGroup.APP_STATE,
        default=[],
        **_list_of_strings_params,
    ),
    StateKey.LAST_GPX_FOLDER: SettingDef(group=StateGroup.APP_STATE, read_type=str),
    StateKey.ARCHIVE_SAVE_EXIF: SettingDef(
        group=StateGroup.APP_STATE,
        default=False,
        read_type=bool,
    ),
    StateKey.SORT_ORDER: SettingDef(
        group=StateGroup.APP_STATE,
        read_type=str,
        default=SortOrder.FILE_NAME.name,
    ),
    StateKey.COPY_SD_EJECT: SettingDef(
        group=StateGroup.APP_STATE,
        read_type=bool,
        default=True,
    ),
    StateKey.COPY_SD_NAME_SUFFIX: SettingDef(
        group=StateGroup.APP_STATE,
        read_type=str,
    ),
    StateKey.COPY_SD_DATE_SPEC: SettingDef(
        group=StateGroup.APP_STATE,
        read_type=str,
    ),
    StateKey.LAST_TIMESHIFT_BY_FOLDERS: SettingDef(
        group=StateGroup.APP_STATE,
        read_type=str,
        default={},
        json_storage=True,
    ),
    StateKey.NUM_COLUMNS: SettingDef(
        group=StateGroup.APP_STATE,
        read_type=int,
        default=6,
    ),
    StateKey.LAST_TIMESHIFT: SettingDef(group=StateGroup.APP_STATE, read_type=str),
    StateKey.WINDOW_GEOMETRY: SettingDef(group=StateGroup.QT, read_type=QByteArray),
    StateKey.WINDOW_STATE: SettingDef(group=StateGroup.QT, read_type=QByteArray),
    StateKey.MAIN_SPLITTER: SettingDef(group=StateGroup.QT, read_type=QByteArray),
    StateKey.RIGHT_SPLITTER: SettingDef(group=StateGroup.QT, read_type=QByteArray),
}


_USER_SETTING_REGISTRY: dict[UserSettingKey, SettingDef] = {
    UserSettingKey.CACHE_BASE_DIR: SettingDef(
        group=SettingsGroup.SETTINGS,
        default=None,
        read_type=str,
    ),
    UserSettingKey.EXIFTOOL_PATH: SettingDef(
        group=SettingsGroup.SETTINGS,
        default=None,
        read_type=str,
    ),
    # for now : just a list of exiffields : no fomatting or change of label beyond
    # default transformation
    UserSettingKey.CUSTOM_EXIF_FIELDS: SettingDef(
        group=SettingsGroup.SETTINGS,
        default=[],
        **_list_of_strings_params,
    ),
    # actually a State (not set in settings : but in GUI) but states and settings
    # are conceptually the same (just states are implicit)
    UserSettingKey.ON_FULLSCREEN_EXIT_SELECTION_MODE: SettingDef(
        group=SettingsGroup.SETTINGS,
        default=OnFullscreenExitMultipleSelected.KEEP_SELECTION,
        read_type=str,
        serializer=_serialize_on_fullscreen_exit_selection_mode,
        deserializer=_deserialize_on_fullscreen_exit_selection_mode,
        env_parser=_deserialize_on_fullscreen_exit_selection_mode,
    ),
    UserSettingKey.FORCE_SRGB: SettingDef(
        group=SettingsGroup.SETTINGS,
        default=False,
        read_type=bool,
    ),
    UserSettingKey.SCREEN_COLOR_PROFILE: SettingDef(
        group=SettingsGroup.SETTINGS,
        default=ScreenColorProfileMode.FROM_MAIN_SCREEN,
        read_type=str,
        serializer=_serialize_screen_color_profile_mode,
        deserializer=_deserialize_screen_color_profile_mode,
        env_parser=lambda raw: _parse_enum(
            raw,
            ScreenColorProfileMode,
            ScreenColorProfileMode.FROM_MAIN_SCREEN,
        ),
    ),
    UserSettingKey.FAVORITE_FOLDER: SettingDef(
        group=SettingsGroup.SETTINGS,
        default="",
        read_type=str,
    ),
    UserSettingKey.SHOW_DESCRIPTION_FIELD: SettingDef(
        group=SettingsGroup.SETTINGS,
        default=True,
        read_type=bool,
    ),
    UserSettingKey.SHOW_HIDDEN_METADATA_FIELDS_IF_NOT_EMPTY: SettingDef(
        group=SettingsGroup.SETTINGS,
        default=False,
        read_type=bool,
    ),
    UserSettingKey.PROTECT_NON_TEXT_METADATA: SettingDef(
        group=SettingsGroup.SETTINGS,
        default=True,
        read_type=bool,
    ),
    UserSettingKey.MAP_LINKS: SettingDef(
        group=SettingsGroup.SETTINGS,
        default=[],
        read_type=str,
        json_storage=True,
        serializer=_serialize_map_links,
        deserializer=_deserialize_map_links,
        env_parser=lambda raw: _deserialize_map_links(_parse_json(raw)),
    ),
    UserSettingKey.STATUS_LABELS: SettingDef(
        group=SettingsGroup.SETTINGS,
        default=[
            StatusLabel("Approved", "#FF0000", 1),
            StatusLabel("Rejected", "#FFFF00", 2),
            StatusLabel("Maybe", "#EA9412", 3),
            StatusLabel("Review", "#0000FF", 4),
            StatusLabel("Uploaded", "#00FF00", 5),
        ],
        read_type=str,
        json_storage=True,
        serializer=_serialize_status_labels,
        deserializer=_deserialize_status_labels,
        env_parser=lambda raw: _deserialize_status_labels(_parse_json(raw)),
    ),
    UserSettingKey.EXTERNAL_VIEWER: SettingDef(
        group=SettingsGroup.SETTINGS,
        default="",
        read_type=str,
    ),
    UserSettingKey.EXTERNAL_EDITOR: SettingDef(
        group=SettingsGroup.SETTINGS,
        default="",
        read_type=str,
    ),
    UserSettingKey.SHORTCUTS: SettingDef(
        group=SettingsGroup.SETTINGS,
        default={
            Shortcut.ZOOM_IN: "=",
            Shortcut.ZOOM_OUT: "-",
            Shortcut.ZOOM_RESET: "0",
            Shortcut.EJECT_FROM_LOOP: "\\",
            Shortcut.LABEL_1: "1",
            Shortcut.LABEL_2: "2",
            Shortcut.LABEL_3: "3",
            Shortcut.LABEL_4: "4",
            Shortcut.LABEL_5: "5",
            Shortcut.LABEL_6: "6",
            Shortcut.LABEL_7: "7",
            Shortcut.LABEL_8: "8",
            Shortcut.LABEL_9: "9",
            Shortcut.LABEL_NONE: "`",
            Shortcut.FILTER_LABEL_1: "Alt+1",
            Shortcut.FILTER_LABEL_2: "Alt+2",
            Shortcut.FILTER_LABEL_3: "Alt+3",
            Shortcut.FILTER_LABEL_4: "Alt+4",
            Shortcut.FILTER_LABEL_5: "Alt+5",
            Shortcut.FILTER_LABEL_6: "Alt+6",
            Shortcut.FILTER_LABEL_7: "Alt+7",
            Shortcut.FILTER_LABEL_8: "Alt+8",
            Shortcut.FILTER_LABEL_9: "Alt+9",
            Shortcut.FILTER_LABEL_NONE: "Alt+`",
            Shortcut.FILTER_FOLDER_ALL: "Alt+0",
            Shortcut.FILTER_FOLDER_NEXT: "Alt+=",
            Shortcut.FILTER_FOLDER_PREV: "Alt+-",
            Shortcut.FILTER_CLEAR_ALL: "Alt+\\",
            Shortcut.FILTER_FOCUS_SEARCH: "Ctrl+F",
            Shortcut.SELECT_ALL: "ctrl+a",
            Shortcut.COLLAPSE_TO_LAST_SELECTED: "Esc",
            Shortcut.TOGGLE_RIGHT_SIDEBAR: "Ctrl+]",
        },
        read_type=str,
        json_storage=True,
        serializer=_serialize_shortcuts,
        deserializer=_deserialize_shortcuts,
        env_parser=lambda raw: _deserialize_shortcuts(_parse_json(raw)),
    ),
    UserSettingKey.FILTER_IN_FULLSCREEN: SettingDef(
        group=SettingsGroup.SETTINGS,
        default=False,
        read_type=bool,
    ),
    UserSettingKey.COPY_SD_BASE_EXTERNAL_FOLDER: SettingDef(
        group=SettingsGroup.SETTINGS,
        default="",
        read_type=str,
    ),
    UserSettingKey.ARCHIVE_DESTINATION: SettingDef(
        group=SettingsGroup.SETTINGS,
        default="",
        read_type=str,
    ),
    UserSettingKey.SDCARD_NAMES: SettingDef(
        group=SettingsGroup.SETTINGS,
        default=[],
        **_list_of_strings_params,
    ),
    UserSettingKey.GPX_TIMEZONE: SettingDef(
        group=SettingsGroup.SETTINGS,
        default="",
        read_type=str,
    ),
    UserSettingKey.GPX_IGNORE_OFFSET: SettingDef(
        group=SettingsGroup.SETTINGS,
        default=False,
        read_type=bool,
    ),
    UserSettingKey.GPX_KML_FOLDER: SettingDef(
        group=SettingsGroup.SETTINGS,
        default="",
        read_type=str,
    ),
    UserSettingKey.TIME_SHIFT_UNKNOWN_FOLDER_IGNORE: SettingDef(
        group=SettingsGroup.SETTINGS,
        default=True,
        read_type=bool,
    ),
    UserSettingKey.GCP_PROJECT: SettingDef(
        group=SettingsGroup.SETTINGS,
        default="",
        read_type=str,
    ),
    UserSettingKey.GCP_SA_KEY_PATH: SettingDef(
        group=SettingsGroup.SETTINGS,
        default="",
        read_type=str,
    ),
    UserSettingKey.FLICKR_API_KEY: SettingDef(
        group=SettingsGroup.SETTINGS,
        default="",
        read_type=str,
    ),
    UserSettingKey.FLICKR_API_SECRET: SettingDef(
        group=SettingsGroup.SETTINGS,
        default="",
        read_type=str,
    ),
    UserSettingKey.FLICKR_UPLOAD_LABEL: SettingDef(
        group=SettingsGroup.SETTINGS,
        default="",
        read_type=str,
    ),
    UserSettingKey.FLICKR_UPLOAD_REQUIRE_TITLE_AND_KEYWORDS: SettingDef(
        group=SettingsGroup.SETTINGS,
        default=False,
        read_type=bool,
    ),
    UserSettingKey.MANUAL_LENSES: SettingDef(
        group=SettingsGroup.SETTINGS,
        default=[],
        read_type=str,
        json_storage=True,
        serializer=_serialize_manual_lenses,
        deserializer=_deserialize_manual_lenses,
        env_parser=lambda raw: _deserialize_manual_lenses(_parse_json(raw)),
    ),
}

# read_type is to deserialize from an env var
# TODO restrict the env vars to some of the keys ?
_RUNTIME_SETTING_REGISTRY: dict[RuntimeSettingKey, SettingDef] = {
    RuntimeSettingKey.DETACHED_KEYWORD_TREE: SettingDef(default=False, read_type=bool),
    RuntimeSettingKey.INITIAL_RESOLUTION: SettingDef(
        default=None,
        read_type=str,
        env_parser=lambda raw: raw,
    ),
    RuntimeSettingKey.RECENT_FOLDERS_MENU_LIMIT: SettingDef(
        default=10,
        read_type=int,
    ),
    RuntimeSettingKey.OCR_TIME_SHIFT_PROVIDER: SettingDef(
        default=TimeShiftOcrProvider.APPLE_VISION,
        read_type=str,
        env_parser=_deserialize_time_shift_ocr_provider,
        deserializer=_deserialize_time_shift_ocr_provider,
    ),
    RuntimeSettingKey.TIME_TAKEN_LOAD_RESORT_BATCH_SIZE: SettingDef(
        default=100,
        read_type=int,
    ),
    RuntimeSettingKey.EXIF_PANEL_COLUMN_STRETCH: SettingDef(
        default=(30, 70),
        read_type=str,
        env_parser=lambda raw: _deserialize_column_stretch(_parse_json(raw)),
    ),
    RuntimeSettingKey.EXIF_PANEL_ROW_SPACING: SettingDef(default=5, read_type=int),
    RuntimeSettingKey.SETTINGS_PANEL_ROW_SPACING: SettingDef(default=0, read_type=int),
    RuntimeSettingKey.GRID_ITEM_SHOW_LABEL_SWATCH: SettingDef(
        default=True, read_type=bool
    ),
    RuntimeSettingKey.MAX_WORKERS: SettingDef(default=4, read_type=int),
    RuntimeSettingKey.TIMESHIFT_CACHE_NUM: SettingDef(default=10, read_type=int),
    RuntimeSettingKey.FLICKR_UPLOAD_MAX_WORKERS: SettingDef(default=2, read_type=int),
    RuntimeSettingKey.MIN_IDLE_WORKERS: SettingDef(default=1, read_type=int),
    RuntimeSettingKey.MAX_EXIFTOOLS_IMAGE_BATCH: SettingDef(default=8, read_type=int),
    RuntimeSettingKey.SHUTDOWN_TIMEOUT_S: SettingDef(default=5.0, read_type=float),
    RuntimeSettingKey.COPY_SD_EJECT_TIMEOUT_S: SettingDef(
        default=5.0, read_type=float
    ),
    RuntimeSettingKey.PADDING: SettingDef(default=10, read_type=int),
    RuntimeSettingKey.FONT_SIZE: SettingDef(default=12, read_type=int),
    RuntimeSettingKey.GRID_ITEM_TEXT_FIELDS_TOP_PADDING: SettingDef(
        default=10, read_type=int
    ),
    RuntimeSettingKey.GRID_THUMB_BUFFER_ROWS: SettingDef(default=2, read_type=int),
    RuntimeSettingKey.GRID_EMBEDDED_BUFFER_ROWS: SettingDef(default=20, read_type=int),
    RuntimeSettingKey.GRID_HQ_THUMB_DELAY_ENABLED: SettingDef(
        default=True, read_type=bool
    ),
    RuntimeSettingKey.GRID_HQ_THUMB_LOAD_DELAY_MS: SettingDef(
        default=100, read_type=int
    ),
    RuntimeSettingKey.GRID_NUM_COLUMNS_MIN: SettingDef(default=3, read_type=int),
    RuntimeSettingKey.GRID_NUM_COLUMNS_MAX: SettingDef(default=10, read_type=int),
    RuntimeSettingKey.GRID_LOWRES_ONLY: SettingDef(default=False, read_type=bool),
    RuntimeSettingKey.STATUS_BAR_SIDE_PADDING: SettingDef(default=10, read_type=int),
    RuntimeSettingKey.COLOR_MANAGE_EMBEDDED_THUMBNAILS: SettingDef(
        default=True,
        read_type=bool,
    ),
    RuntimeSettingKey.COLOR_MANAGE_HQ_THUMBNAILS: SettingDef(
        default=True,
        read_type=bool,
    ),
    RuntimeSettingKey.PILLOW_FOR_EXTRACT_IMAGE_COLOR_PROFILE: SettingDef(
        default=False,
        read_type=bool,
    ),
    RuntimeSettingKey.ZOOM_WHEEL_SENSITIVITY: SettingDef(default=1, read_type=int),
    RuntimeSettingKey.PAN_EMPTY_SPACE: SettingDef(default=300, read_type=int),
    RuntimeSettingKey.PAN_CURSOR_DELAY_MS: SettingDef(default=100, read_type=int),
    RuntimeSettingKey.INFO_PANEL_BACKGROUND_COLOR: SettingDef(
        default="black", read_type=str
    ),
    RuntimeSettingKey.INFO_PANEL_BACKGROUND_TRANSPARENCY: SettingDef(
        default=80, read_type=int
    ),
    RuntimeSettingKey.INFO_PANEL_TEXT_COLOR: SettingDef(default="white", read_type=str),
    RuntimeSettingKey.INFO_PANEL_MARGIN_BOTTOM: SettingDef(default=10, read_type=int),
    RuntimeSettingKey.INFO_PANEL_MARGIN_SIDE: SettingDef(default=10, read_type=int),
    RuntimeSettingKey.INFO_PANEL_POSITION: SettingDef(default="bottom", read_type=str),
    RuntimeSettingKey.INFO_PANEL_ZOOM_PERCENT_OVERLAY_TIMER_MS: SettingDef(
        default=1000, read_type=int
    ),
    RuntimeSettingKey.SHOW_EDIT_PANEL: SettingDef(default=True, read_type=bool),
    RuntimeSettingKey.TITLE_MAX_LENGTH: SettingDef(default=128, read_type=int),
    RuntimeSettingKey.DESCRIPTION_MAX_LENGTH: SettingDef(default=128, read_type=int),
    RuntimeSettingKey.GRID_ITEM_FIELDS: SettingDef(
        default=["title", "time_taken"],
        read_type=str,
        env_parser=_parse_list_of_str,
    ),
    RuntimeSettingKey.EXIF_AUTO_FORMAT: SettingDef(default=True, read_type=bool),
    # TODO instead of raw strings : set ref to function (or a constant that refs to
    # function)
    RuntimeSettingKey.EXIF_FIELDS: SettingDef(
        default=[
            ExifField("EXIF:Model"),
            ExifField("EXIF:LensModel"),
            ExifField("EXIF:FocalLength", format="focal_mm"),
            ExifField(
                "EXIF:FocalLengthIn35mmFormat",
                "Focal Length (35 mm)",
                "focal_mm",
            ),
            ExifField("Composite:ShutterSpeed", "Shutter Speed", "shutter_speed"),
            ExifField("EXIF:FNumber", "F-Number"),
            ExifField("EXIF:ISO"),
            ExifField("EXIF:ExposureCompensation", "EV", "exposure_compensation"),
            ExifField("File:FileName", "File Name"),
        ],
        read_type=str,
        env_parser=lambda raw: _deserialize_exif_fields(_parse_json(raw)),
    ),
    RuntimeSettingKey.THUMB_MAX_DIM: SettingDef(default=1024, read_type=int),
    RuntimeSettingKey.GRID_BACKGROUND_COLOR: SettingDef(
        default="#4a4a4a", read_type=str
    ),
    RuntimeSettingKey.GRID_BORDER_COLOR: SettingDef(default="#888888", read_type=str),
    RuntimeSettingKey.FULLSCREEN_BACKGROUND_COLOR: SettingDef(
        default="#323232", read_type=str
    ),
    RuntimeSettingKey.CLEAR_CACHE_ON_START: SettingDef(default=False, read_type=bool),
    RuntimeSettingKey.SETTINGS_PANEL_SAVE_MODE: SettingDef(
        default=SettingsPanelSaveMode.SAVE_CANCEL,
        read_type=str,
        env_parser=lambda raw: _parse_enum(
            raw,
            SettingsPanelSaveMode,
            SettingsPanelSaveMode.SAVE_CANCEL,
        ),
    ),
}


_MANDATORY_SETTING_SPECS: tuple[MandatorySettingSpec, ...] = (
    MandatorySettingSpec(
        key=UserSettingKey.CACHE_BASE_DIR,
        label="Cache Base Directory",
        input_kind=MandatorySettingInputKind.DIRECTORY,
        can_create=True,
        validator=_validate_existing_directory,
        default_resolver=_resolve_default_cache_base_dir_macos,
    ),
    MandatorySettingSpec(
        key=UserSettingKey.EXIFTOOL_PATH,
        label="Exiftool Path",
        input_kind=MandatorySettingInputKind.EXECUTABLE_PATH,
        can_create=False,
        validator=_validate_executable_path,
        default_resolver=_resolve_default_exiftool_path_macos,
    ),
)

_MANDATORY_SETTING_SPECS_BY_KEY: dict[UserSettingKey, MandatorySettingSpec] = {
    spec.key: spec for spec in _MANDATORY_SETTING_SPECS
}


def get_mandatory_setting_specs() -> tuple[MandatorySettingSpec, ...]:
    return _MANDATORY_SETTING_SPECS


def get_mandatory_setting_spec(
    key: UserSettingKey,
) -> MandatorySettingSpec | None:
    return _MANDATORY_SETTING_SPECS_BY_KEY.get(key)


def validate_mandatory_setting_value(
    spec: MandatorySettingSpec,
    value: object,
) -> bool:
    text = _normalize_optional_text(value)
    if not text:
        return False
    return bool(spec.validator(text))


def evaluate_pending_mandatory_settings() -> list[PendingMandatorySetting]:
    pending: list[PendingMandatorySetting] = []
    for spec in _MANDATORY_SETTING_SPECS:
        current_value = _normalize_optional_text(get_user_setting(spec.key))
        auto_value = ""
        if spec.default_resolver is not None:
            auto_value = _normalize_optional_text(spec.default_resolver())

        is_empty = not current_value
        if not is_empty and validate_mandatory_setting_value(spec, current_value):
            continue

        pending.append(
            PendingMandatorySetting(
                spec=spec,
                current_value=current_value,
                auto_value=auto_value or None,
                is_empty=is_empty,
            )
        )
    return pending


class QSettingsStore:
    """Typed abstraction over QSettings with explicit groups for states/settings."""

    def __init__(self, dyn: bool = False):
        self._dyn = bool(dyn)
        self._memory: dict[str, object] = {}
        self._settings = None if self._dyn else QSettings()
        self._runtime_values: dict[RuntimeSettingKey, object] = {}
        self._load_runtime_values()

    # Backward-compatible alias for existing state store call sites.
    def get(self, key: StateKey):
        return self.get_state_value(key)

    # Backward-compatible alias for existing state store call sites.
    def set(self, key: StateKey, value: object) -> None:
        self.set_state_value(key, value)

    def get_state_value(self, key: StateKey):
        entry = _STATE_REGISTRY[key]
        env_value = (
            self._read_env_override(key.name, entry)
            if entry.group == StateGroup.APP_STATE
            else None
        )
        if env_value is not None:
            return env_value

        full_key = self._state_full_key(key)

        if full_key in self._memory:
            return self._memory[full_key]

        if self._settings is None:
            return deepcopy(entry.default)

        if not self._settings.contains(full_key):
            return deepcopy(entry.default)

        return self._read_persisted_value(full_key, entry)

    def set_state_value(self, key: StateKey, value: object) -> None:
        entry = _STATE_REGISTRY[key]
        full_key = self._state_full_key(key)
        self._memory[full_key] = value

        if self._dyn:
            return

        self._write_persisted_value(full_key, entry, value)

    def get_user_setting(self, key: UserSettingKey):
        entry = _USER_SETTING_REGISTRY[key]

        env_value = self._read_env_override(key.name, entry)
        if env_value is not None:
            return env_value

        full_key = self._user_setting_full_key(key)
        if full_key in self._memory:
            return self._memory[full_key]

        if self._settings is None:
            return deepcopy(entry.default)

        if not self._settings.contains(full_key):
            return deepcopy(entry.default)

        return self._read_persisted_value(full_key, entry)

    def set_user_setting(self, key: UserSettingKey, value: object) -> None:
        entry = _USER_SETTING_REGISTRY[key]
        full_key = self._user_setting_full_key(key)

        normalized_value = self._normalize_value(entry, value)
        self._memory[full_key] = normalized_value

        if self._dyn:
            return

        self._write_persisted_value(full_key, entry, normalized_value)

    def get_runtime_setting(self, key: RuntimeSettingKey):
        return self._runtime_values[key]

    def sync(self) -> None:
        if self._settings is not None:
            self._settings.sync()

    def _qsettings_file_name(self) -> str | None:
        if self._settings is None:
            return None
        return self._settings.fileName()

    def _load_runtime_values(self) -> None:
        for key, entry in _RUNTIME_SETTING_REGISTRY.items():
            env_value = self._read_env_override(key.name, entry)
            if env_value is None:
                self._runtime_values[key] = deepcopy(entry.default)
            else:
                self._runtime_values[key] = env_value

    def _state_full_key(self, key: StateKey) -> str:
        entry = _STATE_REGISTRY[key]
        return self._persisted_full_key(key.value, entry)

    def _user_setting_full_key(self, key: UserSettingKey) -> str:
        entry = _USER_SETTING_REGISTRY[key]
        return self._persisted_full_key(key.value, entry)

    def _persisted_full_key(self, key_value: str, entry: SettingDef) -> str:
        return f"{entry.group.value}/{key_value}"

    def _read_persisted_value(self, full_key: str, entry: SettingDef):
        assert self._settings is not None
        if entry.json_storage:
            raw: str = self._settings.value(full_key, type=str)  # type: ignore
            try:
                decoded = json.loads(raw)
                return self._deserialize(entry, decoded)
            except Exception:
                logger.warning("Invalid JSON in QSettings for %s", full_key)
                return deepcopy(entry.default)

        value = self._read_with_type(full_key, entry.read_type)
        return self._deserialize(entry, value)

    def _write_persisted_value(
        self,
        full_key: str,
        entry: SettingDef,
        value: object,
    ) -> None:
        assert self._settings is not None

        if entry.json_storage:
            encoded = self._serialize(entry, value)
            self._settings.setValue(full_key, json.dumps(encoded))
            return

        encoded = self._serialize(entry, value)
        self._settings.setValue(full_key, encoded)

    def _normalize_value(self, entry: SettingDef, value: object) -> object:
        # Run through serialize/deserialize pipeline to enforce types.
        if entry.json_storage:
            encoded = self._serialize(entry, value)
            return self._deserialize(entry, encoded)
        return self._deserialize(entry, self._serialize(entry, value))

    def _serialize(self, entry: SettingDef, value: object) -> object:
        if entry.serializer is None:
            return value
        return entry.serializer(value)

    def _deserialize(self, entry: SettingDef, value: object) -> object:
        if entry.deserializer is None:
            return value
        return entry.deserializer(value)

    def _read_with_type(self, full_key: str, read_type: type) -> object:
        assert self._settings is not None
        if read_type is QByteArray:
            return self._settings.value(full_key, type=QByteArray)
        if read_type is bool:
            return self._settings.value(full_key, type=bool)
        if read_type is int:
            return self._settings.value(full_key, type=int)
        if read_type is float:
            return self._settings.value(full_key, type=float)
        return self._settings.value(full_key, type=str)

    def _read_env_override(self, enum_name: str, entry: SettingDef) -> object | None:
        env_name = f"{ENV_PREFIX}{enum_name}"
        raw = os.environ.get(env_name)
        if raw is None:
            return None

        try:
            if entry.env_parser is not None:
                return entry.env_parser(raw)
            if entry.json_storage:
                return self._deserialize(entry, _parse_json(raw))
            if entry.read_type is bool:
                return _parse_bool(raw)
            if entry.read_type is int:
                return int(raw)
            if entry.read_type is float:
                return float(raw)
            return raw
        except Exception:
            logger.warning("Invalid env override %s=%r", env_name, raw)
            return None


# Module-level singleton
_store: QSettingsStore | None = None


def init_qsettings_store(dyn: bool = False) -> QSettingsStore:
    """Initialize the global QSettings store after QApplication identity setup."""
    global _store
    _store = QSettingsStore(dyn=dyn)
    qsettings_file_name = _store._qsettings_file_name()
    if qsettings_file_name is None:
        logger.info("QSettings location: memory only (--dyn)")
    else:
        logger.info("QSettings location: %s", qsettings_file_name)
    return _store


def get_qsettings_store() -> QSettingsStore:
    if _store is None:
        raise RuntimeError(
            "Settings not initialized. Call init_qsettings_store() first."
        )
    return _store


def get_state_value(key: StateKey):
    return get_qsettings_store().get_state_value(key)


def set_state_value(key: StateKey, value: object) -> None:
    get_qsettings_store().set_state_value(key, value)


def get_user_setting(key: UserSettingKey):
    return get_qsettings_store().get_user_setting(key)


def set_user_setting(key: UserSettingKey, value: object) -> None:
    get_qsettings_store().set_user_setting(key, value)


def get_runtime_setting(key: RuntimeSettingKey):
    return get_qsettings_store().get_runtime_setting(key)


def get_effective_exif_panel_fields() -> list[ExifField]:
    """Return EXIF panel fields: built-ins plus user custom fields.

    Built-in runtime fields keep their order and labels/formatters.
    User custom fields are appended, deduped by key, and use default label/formatter
    behavior (label=None, format=None).
    """
    base_fields = list(get_runtime_setting(RuntimeSettingKey.EXIF_FIELDS))  # type: ignore
    custom_keys = list(get_user_setting(UserSettingKey.CUSTOM_EXIF_FIELDS) or [])  # type: ignore

    out: list[ExifField] = []
    seen_keys: set[str] = set()

    for field in base_fields:
        key = str(field.key).strip()
        if not key or key in seen_keys:
            continue
        seen_keys.add(key)
        out.append(field)

    for raw_key in custom_keys:
        key = str(raw_key).strip()
        if not key or key in seen_keys:
            continue
        seen_keys.add(key)
        out.append(ExifField(key=key))

    return out


def get_effective_exif_panel_field_keys() -> list[str]:
    return [field.key for field in get_effective_exif_panel_fields()]


# Backward-compatible aliases for existing callsites.
def init_state(dyn: bool = False) -> QSettingsStore:
    return init_qsettings_store(dyn=dyn)


# Backward-compatible aliases for existing callsites.
def get_state() -> QSettingsStore:
    return get_qsettings_store()


def sync_qsettings_store() -> None:
    get_qsettings_store().sync()


# dir for default cache / additional files generated by the application
def _default_support_dir_path_macos(*, create=False) -> Path:
    base = Path.home() / "Library" / "Application Support"
    support_dir = base / APP_NAME
    if create:
        support_dir.mkdir(parents=True, exist_ok=True)
    return support_dir


def get_support_dir_macos() -> Path:
    """Get the platform-specific application support directory."""
    return _default_support_dir_path_macos(create=True)


def default_cache_base_dir_candidate_macos() -> Path:
    return _default_support_dir_path_macos() / "cache"


def get_cache_base_dir_macos() -> Path:
    """Get the default fallback base directory for cache data."""
    cache_dir = default_cache_base_dir_candidate_macos()
    cache_dir.mkdir(parents=True, exist_ok=True)
    return cache_dir
