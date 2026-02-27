The shortcuts are not segregated by view : For example "Select all" still works while in fullscreen eevn though it makes no sense outside the grid. It is visible : cmd a in fullscreen : when exiting : all the grid is selected : it is visible for a short time, then it goes back to original selection (the images in the fullscreen loop).
=> Fix this : disable the shortcuts for one view when the other is visible. In particular : the cmd a in fullscreen should have no effect but same thing for the settings shortcut or the Load folder.
Only apply the grid shortcut when it is visible.

2 views with different sets of shorcuts : 
- Grid (where the rest of the panels + menu are also visible + can be acted upon).  In grid view: the menu shortcuts like settings or quit (cmd q) other like load folder (could be other) are acctive
- Fullscreen (focused view : only quite specific shortcuts : no menubar menus : shortcuts include the labels + zoom in/out/reset ; there could be more in the future). 
Both have cmd-q. The settings menu or the load menu shorctuts + other menu shortcuts in the future should have no effect in fullscreen

Do not process the shortctus like ctrl a (select all) or the label shorcuts in main window (thy act up the grid cells or the current photo in fullscreen). But either in photo_grid or fullscreen_overlay. where the elements they act upon are located. Preferrably do not set up  application shortcuts for those : but set them up for the view (only active when the view is focused). For menu shortcuts like settings cmd , or Load folder : disable them in Fullscreen mode. 

Possibly setup a parent component for the grid and the panels (filter, metadata, exif) : the space or cmd a must work after a filter has been set or if an exif field is copied (it received focus).

Also 

Setup the list of shorcuts (non menu, non standard) for each view at one location : the src/piqopiqo/shortcuts.py could be it or split the shortcturs for each view or define them in a shorcuts module for each view (with the root shortcuts only utils) so easy to see what they are.

Clarify which shortcuts for which view.

