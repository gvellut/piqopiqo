"""Color-management helpers shared by fullscreen and grid thumbnail display."""

from __future__ import annotations

from enum import auto
import logging
import sys

from PySide6.QtGui import QColorSpace, QPixmap

from .utils import UpperStrEnum

logger = logging.getLogger(__name__)

_MAIN_SCREEN_COLOR_SPACE_CACHE: QColorSpace | None = None


class ScreenColorProfileMode(UpperStrEnum):
    FROM_MAIN_SCREEN = auto()
    SRGB = auto()
    DISPLAY_P3 = auto()
    BT2020 = auto()
    NO_CONVERSION = auto()


def _is_valid_color_space(space: QColorSpace | None) -> bool:
    return bool(space is not None and space.isValid())


def refresh_main_screen_color_space_cache() -> QColorSpace | None:
    """Refresh and return the cached main-screen QColorSpace (macOS only)."""
    global _MAIN_SCREEN_COLOR_SPACE_CACHE

    if sys.platform != "darwin":
        _MAIN_SCREEN_COLOR_SPACE_CACHE = None
        return None

    try:
        import AppKit

        ns_screen = AppKit.NSScreen.mainScreen()
        if ns_screen is None:
            _MAIN_SCREEN_COLOR_SPACE_CACHE = None
            return None

        ns_color_space = ns_screen.colorSpace()
        if ns_color_space is None:
            _MAIN_SCREEN_COLOR_SPACE_CACHE = None
            return None

        icc_data = ns_color_space.ICCProfileData()
        if not icc_data:
            _MAIN_SCREEN_COLOR_SPACE_CACHE = None
            return None

        icc_bytes = icc_data.bytes().tobytes()
        color_space = QColorSpace.fromIccProfile(icc_bytes)
        _MAIN_SCREEN_COLOR_SPACE_CACHE = color_space if color_space.isValid() else None
        return _MAIN_SCREEN_COLOR_SPACE_CACHE
    except Exception:
        logger.exception("Failed to refresh main-screen ICC color profile")
        _MAIN_SCREEN_COLOR_SPACE_CACHE = None
        return None


def get_cached_main_screen_color_space() -> QColorSpace | None:
    """Return the cached main-screen QColorSpace, if available and valid."""
    if _is_valid_color_space(_MAIN_SCREEN_COLOR_SPACE_CACHE):
        return _MAIN_SCREEN_COLOR_SPACE_CACHE
    return None


def _extract_image_color_space_macos_pyobjc(image_path: str) -> QColorSpace | None:
    if sys.platform != "darwin":
        return None

    try:
        import AppKit
        import Quartz

        url = Quartz.CFURLCreateWithFileSystemPath(
            None,
            image_path,
            Quartz.kCFURLPOSIXPathStyle,
            False,
        )
        if not url:
            return None

        source = Quartz.CGImageSourceCreateWithURL(url, None)
        if not source:
            return None

        props = Quartz.CGImageSourceCopyPropertiesAtIndex(source, 0, None) or {}
        exif = props.get("{Exif}")
        if exif and exif.get(Quartz.kCGImagePropertyExifColorSpace) == 1:
            return QColorSpace(QColorSpace.NamedColorSpace.SRgb)

        cg_image = Quartz.CGImageSourceCreateImageAtIndex(source, 0, None)
        if not cg_image:
            return None

        cg_color_space = Quartz.CGImageGetColorSpace(cg_image)
        if cg_color_space is None:
            return None

        ns_color_space = AppKit.NSColorSpace.alloc().initWithCGColorSpace_(
            cg_color_space
        )
        if ns_color_space is None:
            return None

        icc_data = ns_color_space.ICCProfileData()
        if not icc_data:
            return None

        icc_bytes = icc_data.bytes().tobytes()
        color_space = QColorSpace.fromIccProfile(icc_bytes)
        return color_space if color_space.isValid() else None
    except Exception:
        logger.debug("PyObjC image color-profile extraction failed for %s", image_path)
        return None


def _extract_image_color_space_pillow(image_path: str) -> QColorSpace | None:
    try:
        from PIL import Image

        with Image.open(image_path) as img:
            icc_profile = img.info.get("icc_profile")
        if not icc_profile:
            return None

        color_space = QColorSpace.fromIccProfile(icc_profile)
        return color_space if color_space.isValid() else None
    except Exception:
        logger.debug("Pillow image color-profile extraction failed for %s", image_path)
        return None


def _coerce_screen_color_profile_mode(
    value: ScreenColorProfileMode | str | object,
) -> ScreenColorProfileMode:
    if isinstance(value, ScreenColorProfileMode):
        return value

    raw = str(value)
    try:
        return ScreenColorProfileMode(raw)
    except ValueError:
        pass
    try:
        return ScreenColorProfileMode[raw]
    except KeyError:
        return ScreenColorProfileMode.FROM_MAIN_SCREEN


def _named_color_space(name: str) -> QColorSpace | None:
    enum_value = getattr(QColorSpace.NamedColorSpace, name, None)
    if enum_value is None:
        return None
    color_space = QColorSpace(enum_value)
    return color_space if color_space.isValid() else None


def _resolve_target_color_space(mode: ScreenColorProfileMode) -> QColorSpace | None:
    if mode == ScreenColorProfileMode.NO_CONVERSION:
        return None
    if mode == ScreenColorProfileMode.FROM_MAIN_SCREEN:
        return get_cached_main_screen_color_space()
    if mode == ScreenColorProfileMode.SRGB:
        return _named_color_space("SRgb")
    if mode == ScreenColorProfileMode.DISPLAY_P3:
        return _named_color_space("DisplayP3")
    if mode == ScreenColorProfileMode.BT2020:
        return _named_color_space("Bt2020")
    return None


def _resolve_source_color_space(
    *,
    image_path: str,
    image,
    force_srgb: bool,
    allow_profile_extract_fallback: bool,
    prefer_pillow_extract: bool,
) -> QColorSpace | None:
    if force_srgb:
        return QColorSpace(QColorSpace.NamedColorSpace.SRgb)

    qt_space = image.colorSpace()
    if qt_space.isValid():
        return qt_space

    if not allow_profile_extract_fallback:
        return None

    if prefer_pillow_extract:
        return _extract_image_color_space_pillow(image_path)
    return _extract_image_color_space_macos_pyobjc(image_path)


def load_pixmap_with_color_management(
    image_path: str,
    *,
    force_srgb: bool,
    screen_profile_mode: ScreenColorProfileMode | str,
    allow_profile_extract_fallback: bool,
    prefer_pillow_extract: bool,
) -> QPixmap:
    """Load an image pixmap and apply optional source/target color management."""
    raw_pixmap = QPixmap(image_path)
    if raw_pixmap.isNull():
        return raw_pixmap

    try:
        image = raw_pixmap.toImage()
        if image.isNull():
            return raw_pixmap

        source_space = _resolve_source_color_space(
            image_path=image_path,
            image=image,
            force_srgb=bool(force_srgb),
            allow_profile_extract_fallback=bool(allow_profile_extract_fallback),
            prefer_pillow_extract=bool(prefer_pillow_extract),
        )
        if _is_valid_color_space(source_space):
            image.setColorSpace(source_space)

        mode = _coerce_screen_color_profile_mode(screen_profile_mode)
        if mode != ScreenColorProfileMode.NO_CONVERSION:
            target_space = _resolve_target_color_space(mode)
            if image.colorSpace().isValid() and _is_valid_color_space(target_space):
                image.convertToColorSpace(target_space)

        converted = QPixmap.fromImage(image)
        return converted if not converted.isNull() else raw_pixmap
    except Exception:
        logger.exception("Color-managed pixmap load failed for %s", image_path)
        return raw_pixmap
