Check everywhere UpperStrEnum is used:
- class Shortcut(UpperStrEnum):
- class OnFullscreenExitMultipleSelected(UpperStrEnum):
- class ScreenColorProfileMode(UpperStrEnum):

See if, the way it is used (for display in Qt or logs or serializing / deserializing in QSettings or through envvar), it is useful to have the UpperStrEnum instead of a simple Enum (with some added access like .name or slightly different way to read from a string value).

If fine, remove the UpperStrEnum from the code + imports : definition + usage and replace where used with what is needed.