in src/piqopiqo/tools/gpx2exif

Add the path to the GPX to folder data (like the Flickr album) for all the folders in the currently opened folders.
It will be saved when doing Apply GPX... in all modes (including Only Generate KML) (when clicking OK ; before applying)
When opening the Apply GPX ... dialog : it will be read from the folder data (just the first one found among all folders) and the text field will be filled with the value.
If the value changes after already exists : overwrite the value in the folder data

see Flickr album : _get_first_folder_album_id _set_album_for_folders src/piqopiqo/tools/flickr_upload/dialogs.py