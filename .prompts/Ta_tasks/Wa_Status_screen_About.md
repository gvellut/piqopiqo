Add  popup panel openable in File > Property : to see details of the current workspace (loaded folder, folders with photo ) + do some clean up action

- panel should :

- show the current folder (full path) + button Reveal in Finder / other wording  depending on OS
- + indicate number of photos (full number with no filtering)
- 2 Buttons to clear the thumbnail cache of for all folders + clear Metadata (show warning dialog only for metadata) for all folders. When a clear requested : make the button visibly inactive (standard qt). No action yet until the OK of the dialog

+ list all the folders (label is the path relative to the current folder) in the current folder that are considered (coherent with the folder filter ie those with a photo in them) 
The list may include . (photos in the current folder)
- presented as a list of names. The names can be selected (multi select not possible)
By folder : 
For the item selected : 
- display the cache location (name of folder inside the cache directory)
- number of photos in folder
- "Reveal in Finder" button to go the folder

Do not make the popup too big : if too many folders. Put in a scroll panel. Still at least 3 folders should fit without scroll

OK Cancel

- After exiting : on OK : after the dialog is closed : do the clear if needed : do it in the background so GUI is not blocked : the thumbnail or exif must be read back (like when Opening a new new folder) using the media_man I think. Confirm.
- if Cancel do not do the clear.


Also add an About Dialog ; version (from src/piqopiqo/__init__.py see src/piqopiqo/metadata/exif_write.py for example of use), current date, a link to Github project https://github.com/gvellut/piqopiqo 
- Standard location in macos : below the name of the program ie QAction::AboutRole; standard location for other OS : in a section below the File menu
- use a QMessageBox::about
