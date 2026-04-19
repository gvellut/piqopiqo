In File add an entry "Open Recent" with an arrow (submenu that opens on the right ; standard stuff) : it should list the x most recent folders : the last open folder must be at the top and the second to last in second position etc except do not display the currently opened folder (so the first one). The number of recent folders to display should be a runtime setting : set to 10 (so maybe max 11 to keep including the current one that should not be displayed)
The recent folders should be displayed with no slash / at the end
The displayed folder paths should be processed : 
- if Favorite Folder is defined : and the recent folder is below Favorite : only display the part of the path beyond the favorite part (do not use / at the beginning of what is displayed)
- if recent folder is below the home folder for current user : it should be displayed with a ~/.... 
- otherwise : display the full path

If a recent folder is reopened, it should _move_ to the top of the recent folder list (and not be displayed twice)
Save the recent folders when opening a folder. Put it into the application State see  src/piqopiqo/ssf/settings_state.py
If a folder is archived : (using the Archive Tool), remove it from the list of recent folders.
If a recent folder cannot be found (because it was moved), display an error dialog and keep the currently opened folder (if there is one) in the interface ie no change beyond the dialog. Also remove that folder from the list of recent folders.