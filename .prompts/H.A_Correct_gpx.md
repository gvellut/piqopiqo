- Make the dialogs not resizable
- In Apply GPX... dialog : remove the GPX Group : put the controls now inside in the dialog without group
- In Apply GPX... dialog : Put GPX File aligned to left and Browse on the right With the text field taking the rest of the space
- In Apply GPX... dialog : Put the mode aligned to the left
- in src/piqopiqo/gpx2exif/__init__.py : do not reexport anything. Leave empty. Use the import from the files themselves outside
- remove  def get_time_shift(self) -> str | None:
        """Get the stored GPX time shift for this folder."""
        return self.get_folder_value(FOLDER_META_TIME_SHIFT)

    def set_time_shift(self, value: str | None) -> None:
        """Set the GPX time shift for this folder.

        Empty strings are treated as unset values.
        """
        normalized = "" if value is None else str(value).strip()
        self.set_folder_value(FOLDER_META_TIME_SHIFT, normalized or None)
from metadata db. It should know nothing about the time shift. 
- src/piqopiqo/gpx2exif/constants.py : 
APPLY_MODE_ONLY_KML = "ONLY_KML"
APPLY_MODE_UPDATE_DB = "UPDATE_DB"
Create an Enum iwth auto values. Define it where they are used (dialog)
- Right click cell : Extract GPS Time Shift. Put it in separate section in the menu NOT stuck with the Regenerates (their own section for both)