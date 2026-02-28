Mandatory settings : cache dir (for thumbnails + db) and exiftool path. 
Make it generic : add a new structure to list the the mandatory settings + ref to function to check validity and return a default value (if the original value was empty / None) to present to the user as a possiblity on its machine => ie so one click to accept the proposed settings. If the original setting value was not valid / or empty : the dialog must come up and the settings set explicitly by the user.
Indicate the type of the setings  (dir, path, other value like text : similar to / can reuse structures in schema in src/piqopiqo/settings_panel/schema.py) => used to generate the dialog to set those mandatory settings at launch

Currently, only one dir (that can be created by Piqopiqo ; but if it does not exist yet : still considered invalid and location must be confirmed by the user) and one path to executable file (that must exist)
For those settings : Need to check at startup : the config paths are valid (exists) and not None (the value set as the default value in User Settings in src/piqopiqo/settings_state.py)

If some mandatory settings not there, you will need to display a dialog that allows to set the settings (that presents only those with missing values, including with determined defaults if empty). For example, if path : can have a Browse button to navigate. If not empty but the value is invalid.
If it is a directory that can be created : indicate underline the text field with the path that it will be created (so the user does not have to create it himself).
If the value is not empty : this must be the value in the text field. Add a line underneath that will show the determined default value + button : Set to recommended. So the user still has its value to edit if needed.
If empty : the text field is filled with the determined default value already amd the there is no line underneath.
Fill the paths with the default values that were determined or empty if no default value.

Buttons OK / Cancel. 
On Cancel, quit the application (mandatory settings invalud). 
On OK : check the settings if they are valid now. If not : show the dialog again with an error message. If some settings are valid for that second time : do not show them in the dialog. If valid : save in QSettings and launch the real Main Window.

If exiftool paht is None : 
Check in PATH if exiftool is there +  get the absolute path
on macos : check also
"/opt/homebrew/bin/exiftool" if there

cache :
Application Support / cache (on macos)
(application support dir for any platforms) / cache
=> creatable if does not exist

For the cache dir : if the proposed default does not exist : can be created by piqopiqo on user confirmation



 UserSettingKey.CACHE_BASE_DIR: SettingDef(
        # FIXME set default to the support dir / cache
        # (Library / Application Support / cache on macos)
        # FIXME add a check at laucnh : it must be valid. If None or not exists / not valid : ask to reset to
        # default or enter new path before any scanning or folder loading is done
        default=None,
        read_type=str,
    ),
    # FIXME default : depends on the platform. Check in PATH The default for macos
    # + check at launch that it exists (thumbnails lowres + metadata depend on it)
    UserSettingKey.EXIFTOOL_PATH: SettingDef(
        default=None,
        read_type=str,
    ),
