"""EXIF orientation handling utilities.

EXIF Orientation values (1-8):
1 = Normal (no transform)
2 = Mirror horizontal
3 = Rotate 180
4 = Mirror vertical
5 = Mirror horizontal + rotate 270 CW (transpose)
6 = Rotate 90 CW
7 = Mirror horizontal + rotate 90 CW (transverse)
8 = Rotate 270 CW (= rotate 90 CCW)

Rotation mappings:
- Rotate left (90° CCW): 1->8, 8->3, 3->6, 6->1
- Rotate right (90° CW): 1->6, 6->3, 3->8, 8->1
"""

from PySide6.QtGui import QImage, QPixmap, QTransform

# Rotation mappings for non-mirrored orientations
# Maps current orientation -> new orientation after rotation
ROTATE_LEFT_MAP = {
    1: 8,  # Normal -> 270 CW
    8: 3,  # 270 CW -> 180
    3: 6,  # 180 -> 90 CW
    6: 1,  # 90 CW -> Normal
    # Mirrored orientations
    2: 5,  # Mirror H -> Mirror H + 270 CW
    5: 4,  # Mirror H + 270 CW -> Mirror V
    4: 7,  # Mirror V -> Mirror H + 90 CW
    7: 2,  # Mirror H + 90 CW -> Mirror H
}

ROTATE_RIGHT_MAP = {
    1: 6,  # Normal -> 90 CW
    6: 3,  # 90 CW -> 180
    3: 8,  # 180 -> 270 CW
    8: 1,  # 270 CW -> Normal
    # Mirrored orientations
    2: 7,  # Mirror H -> Mirror H + 90 CW
    7: 4,  # Mirror H + 90 CW -> Mirror V
    4: 5,  # Mirror V -> Mirror H + 270 CW
    5: 2,  # Mirror H + 270 CW -> Mirror H
}


def rotate_orientation_left(current: int | None) -> int:
    """Get new orientation after rotating 90° counter-clockwise.

    Args:
        current: Current orientation (1-8) or None for default.

    Returns:
        New orientation value (1-8).
    """
    if current is None:
        current = 1
    return ROTATE_LEFT_MAP.get(current, 8)


def rotate_orientation_right(current: int | None) -> int:
    """Get new orientation after rotating 90° clockwise.

    Args:
        current: Current orientation (1-8) or None for default.

    Returns:
        New orientation value (1-8).
    """
    if current is None:
        current = 1
    return ROTATE_RIGHT_MAP.get(current, 6)


def get_orientation_transform(orientation: int | None) -> QTransform:
    """Get the QTransform for applying an EXIF orientation.

    The transform should be applied to the pixmap/image to display it correctly.

    Args:
        orientation: EXIF orientation value (1-8) or None for default.

    Returns:
        QTransform to apply to the image.
    """
    if orientation is None or orientation == 1:
        return QTransform()  # Identity

    transform = QTransform()

    if orientation == 2:
        # Mirror horizontal
        transform.scale(-1, 1)
    elif orientation == 3:
        # Rotate 180
        transform.rotate(180)
    elif orientation == 4:
        # Mirror vertical
        transform.scale(1, -1)
    elif orientation == 5:
        # Mirror horizontal + rotate 270 CW (transpose)
        transform.scale(-1, 1)
        transform.rotate(270)
    elif orientation == 6:
        # Rotate 90 CW
        transform.rotate(90)
    elif orientation == 7:
        # Mirror horizontal + rotate 90 CW (transverse)
        transform.scale(-1, 1)
        transform.rotate(90)
    elif orientation == 8:
        # Rotate 270 CW (= 90 CCW)
        transform.rotate(270)

    return transform


def apply_orientation_to_pixmap(pixmap: QPixmap, orientation: int | None) -> QPixmap:
    """Apply EXIF orientation transform to a QPixmap.

    Args:
        pixmap: The source pixmap.
        orientation: EXIF orientation value (1-8) or None for default.

    Returns:
        Transformed pixmap (or original if no transform needed).
    """
    if orientation is None or orientation == 1 or pixmap.isNull():
        return pixmap

    transform = get_orientation_transform(orientation)
    return pixmap.transformed(transform)


def apply_orientation_to_image(image: QImage, orientation: int | None) -> QImage:
    """Apply EXIF orientation transform to a QImage.

    Args:
        image: The source image.
        orientation: EXIF orientation value (1-8) or None for default.

    Returns:
        Transformed image (or original if no transform needed).
    """
    if orientation is None or orientation == 1 or image.isNull():
        return image

    transform = get_orientation_transform(orientation)
    return image.transformed(transform)
