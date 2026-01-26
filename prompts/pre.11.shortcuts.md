- Add a param + ENV VAR to set initial resolution of the window. It is usefull for agent to setup the window size so screnshot grabs are not too big. Document in CLAUDE.md

- Add  application wide shortcut : physical key ie A in AZERTY or Q in QWWERTY keyboards should be the same shortcuts
- Need to so works in any layout : in the grid + in fullscreen
- keyboard shortcuts : 
    - zoom (in full screen) : qWERTY = to zoom int, QWERTY - to zoom out. Same effect as scroll wheel.
    - labels : update STATUS_LABELS in config.py. Add a keyboard shortcut : using the . Setup an attrs class using @define 


Here is some info about hardware keyboard key shortcuts :
(not the example uses PyQt6 imports : I use Pyside 6 => so adapt)


In Qt and PyQt6, the standard shortcut system (`QShortcut` and `QKeySequence`) is designed to be **logical** and **layout-dependent**. When you define a shortcut for `Qt.Key.Key_Q`, Qt looks for the key that currently produces the character 'Q' in the active keyboard layout.

To achieve **layout-independent** (hardware position-based) shortcuts, you cannot use the standard `setShortcut` method. Instead, you must intercept the raw key events and check the **native scan code**.

### The Solution: Using `nativeScanCode()`
The `nativeScanCode()` method in a `QKeyEvent` returns a platform-specific integer that represents the physical key's position on the keyboard matrix, regardless of what the OS layout says that key is.

#### 1. Hardware Scancode Mapping
Because scancodes are provided by the operating system, they differ between Windows, Linux, and macOS. For the physical key that is "Q" on a US QWERTY keyboard (the first letter on the third row from the bottom), the codes are:

*   **Windows**: `16`
*   **Linux (X11)**: `24`
*   **macOS**: `12`

#### 2. Implementation in PyQt6
You can implement this by using an **Event Filter** on your main window or application. This allows you to catch the key press before it's processed by the normal shortcut system.

```python
import sys
from PyQt6.QtWidgets import QApplication, QMainWindow, QLabel
from PyQt6.QtCore import Qt, QEvent

class HardwareShortcutFilter(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Hardware Key Shortcut")
        self.label = QLabel("Press the 'Q' position key (A on AZERTY)", self)
        self.setCentralWidget(self.label)
        
        # Determine the scancode for the "Q" position based on OS
        if sys.platform == "win32":
            self.Q_POSITION_SCANCODE = 16
        elif sys.platform == "darwin":  # macOS
            self.Q_POSITION_SCANCODE = 12
        else:  # Linux / X11
            self.Q_POSITION_SCANCODE = 24

    def eventFilter(self, obj, event):
        if event.type() == QEvent.Type.KeyPress:
            # Check the physical hardware key position
            if event.nativeScanCode() == self.Q_POSITION_SCANCODE:
                # You can also check for modifiers (e.g., Ctrl)
                if event.modifiers() & Qt.KeyboardModifier.ControlModifier:
                    self.trigger_action("Ctrl + Physical Q")
                    return True  # Consume the event
                
                self.trigger_action("Physical Q")
                return True # Consume the event
                
        return super().eventFilter(obj, event)

    def trigger_action(self, source):
        self.label.setText(f"Action triggered by: {source}")
        print(f"Action triggered by physical key position!")

if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = HardwareShortcutFilter()
    
    # Install the event filter on the application to catch all key presses
    app.installEventFilter(window)
    
    window.show()
    sys.exit(app.exec())
```

### Important Considerations

1.  **Non-Standard Layouts**: While this works for the QWERTY/AZERTY/QWERTZ swap, it might behave unexpectedly on non-standard ergonomic keyboards or specialty hardware where scancodes are remapped at the driver level.
2.  **Displaying the Shortcut**: Since the shortcut is now "hidden" from Qt's standard system, it won't automatically show up in menu hints (e.g., `File -> Save  Ctrl+Q`). You would need to manually set the text of the menu action to reflect what you want the user to see.
3.  **Keyboard Remapping**: If a user has remapped their keys at the OS level (using tools like SharpKeys on Windows), the `nativeScanCode` will typically reflect the *new* mapping.
4.  **Wayland vs X11**: On Linux, the behavior can occasionally vary between X11 and Wayland depending on the specific compositor, though `24` is the standard for the Q position in most XKB-based systems.

### Summary of the "WASD" approach
This technique is common in game development (often called "WASD support") where you care about the physical geometry of the keys rather than the character labels. For productivity software, it is usually recommended to let the user **rebind** shortcuts in a settings menu, where you "record" their preferred `nativeScanCode` and save it to a config file.