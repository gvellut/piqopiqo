Create a QSettings on each use session. Not a single one set in store at application launch.
Synchronize backing memory store (for multiple threads)
=> Check if QThread is used

What of python values (list, dict ...) : would need to reparse ? or like now in memory cache


Dynamic default values (user path or depending on system with initialization) or test for the existence of a path

Mandatory options
Need to check for exiftool => need for lowres tb + metadata extraction
Check if exiftool exists.
Test /opt/homebrew/bin/exiftool => set this in settings if OK
Settings panel opens with path to set exiftool
https://aistudio.google.com/prompts/1pFRjspBffvNCBOxSF3IqySH-oPOCx2hQ

if not there : dialog
Do both at the same time
    # Add verification for existence of cache dir : + dialog to set at startup
    # mode : dyn (no saved settings => read from here) nocheck (no dialog => crash if issue)
    # kw (for keywords saved) + state (for reading / persisting state)

    # exiftool : add verification + dialog to set at startup


1. macOS Native Integration (cfprefsd)

On macOS, QSettings does not manually open, parse, and close the .plist file every time you create an instance. Instead, it uses the Apple CFPreferences API.

    macOS manages preferences through a system daemon called cfprefsd.

    This daemon keeps the settings in memory. When you create a QSettings object, you are essentially just connecting to this system-level cache.

    The actual writing to the physical .plist file on disk is managed by macOS, which often batches writes to avoid wearing out your SSD.

2. Qt's Internal Caching

Even if you weren't on macOS, QSettings maintains an internal, process-wide cache.

    When Instance A writes a value, it updates a shared internal state.

    When Instance B is created, it looks at that same shared state/cache.

    Constructing the Python object is just creating a "handle" or a pointer to that data; it is not a "cold start" for the data itself.

3. The "Sync" Logic

QSettings has an internal timer. When you call setValue(), it doesn't usually force a disk write immediately (unless you call sync() manually). It waits for a brief moment of inactivity or until the event loop cycles to flush the changes. This prevents "disk thrashing" if you update several settings in a row.
4. Performance Comparison

In PySide6:

    Cost of creating a QSettings() object: Microseconds.

    Cost of one disk seek/read: Milliseconds (1000x slower).

If QSettings actually re-read the file every time, the UI would stutter. Because it uses the OS cache and internal pointers, it is practically "free" to create.
When should you actually reuse an instance?

The only time you should keep a single instance around is for convenience within a single scope.


clean up settings