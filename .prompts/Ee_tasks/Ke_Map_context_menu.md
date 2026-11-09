Add a right click "Map" menu item to the images in the grid. In a separate section from the other. Same rules for activatation as the Map button in metadata (inactive if no position). If issue : display the issue in the metadata panel same as a click on the Map button (not a popup). Call the same code (not duplicate).

Move the Regenerate Thumbnail , Reload Exif, Duplicate, and Move to Trash as submenus to a "Other commands" menu item of the context menu. Keep the separate sections.

Also for the Map functionality (called either from context menu or button in the metadata panel) : if zero selection : instead of aborting and error message : use the move to lat lon (always there since condition for being active) with a z = 17. Display a warning (image not found. Zoomed to position) in yellow. In the logs, show the move call with params as debug level (same as the other socket calls) + warning message at warning level.

Also not sure if the case already : if the metadata panel moves to another image becuase another image was selected in the grid (or multiple images selected) => clear the message next to Map. Do not maintain it even if going back to the image. Just temporary message on action, not aimed at being kept.

Also Extract GPS Time shift : if multiple selected : make it inactive. Active only when single image.