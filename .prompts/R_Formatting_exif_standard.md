
Exif fields : add a formatting string : used to set the value displayed to the user
Create formatter for the shutter speed : currently with -n format (keep that) it is a float instead of a 1 / value (need to round the value) + focal length (=> rounded to one decimal + no decimal if integer + mm instead of just number). For focal : make it generic so I can apply to the 35 mm equivalent

process the Custom Exif fields CUSTOM_EXIF_FIELDS src/piqopiqo/settings_state.py set in Settings panel by user (currently does not seem to have an effect in the EXIF panel) : add to the exif panel those listed. Depending on runtime setting EXIF_AUTO_FORMAT : format the name (custom name not settable by user like the base exif fields  in RuntimeSettingKey.EXIF_FIELDS) + no custom formatting either.

Test if the custom Exif fields are taken into account when update in settings : if new added : need to scan the photos and extract the exif again.  Or check if all the exif fields are extracted the first time anyway (so no need to rescan). Report.
