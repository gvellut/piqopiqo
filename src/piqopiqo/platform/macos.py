from PySide6.QtGui import QScreen
import Quartz

PLATFORM = "darwin"


def get_screen_true_resolution(qt_screen: QScreen) -> tuple[int, int]:
    max_displays = 32
    (err, ids, _) = Quartz.CGGetActiveDisplayList(max_displays, None, None)

    if err:
        return None, None

    q_x = int(qt_screen.geometry().x())

    display_id = None
    for d_id in ids:
        # Match based on X position (simplest reliable method for multi-monitor)
        if int(Quartz.CGDisplayBounds(d_id).origin.x) == q_x:
            display_id = d_id
            break

    if display_id is None:
        return None, None

    # iterate ALL modes to find the 'Native' flag
    kDisplayModeNativeFlag = 0x02000000

    # Get all modes (including those not currently active)
    modes = Quartz.CGDisplayCopyAllDisplayModes(display_id, None)

    if not modes:
        return None, None

    for mode in modes:
        flags = Quartz.CGDisplayModeGetIOFlags(mode)

        # Check if this mode is the hardware native resolution
        if flags & kDisplayModeNativeFlag:
            width = Quartz.CGDisplayModeGetPixelWidth(mode)
            height = Quartz.CGDisplayModeGetPixelHeight(mode)
            return width, height

    return None, None
