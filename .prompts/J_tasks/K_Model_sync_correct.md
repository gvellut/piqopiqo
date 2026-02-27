Model sync


- see if the sorting changes the model or applied on top

- if change metadata of photo : if not filtered in by filter : must disappear : this includes the label or the search field
metadata DB field update => reflected in filter result + sorting order (time taken)
done when exiting full screen not in full screen : when looping through the selected images or the currentlky filtered in images
BUT Add User Setting ; editable in  Labels + Shortcuts : checkbox ““Filter in fullscreen” :  to remove from the loop if not included in current filter after label change and to the list of looped images immediately. Do not exit fullscreen ! remove from the loop and move to the the next image. If no longer any image (all original images have been filtered out) => exit Fullscreen then

When apply GPX : date change + latitude longitude : refresh the sort. Check if already done

If adding new tool that changes the metadata in the future : document what must be called to sync everything in AGENTS.md

Adding new status label or changing the shortcut : should work right away when exiting the settings panel.
if deleted, pressing the previous shortcut becomes no color (since changing the label to some text with no defined color)  => should have no effect

the shortcuts need a name (label) : so settings panel can display the name instead of the constant upper case instead of the constant so add a field to the Shortcut enum  src/piqopiqo/shortcuts.py and use that field in the Settings panel

- When item selected : right click => move to trash : No other items is visibly selected after this : BUT the edit panel still shows some data so clearly something is selected
if cell no longer visible : should not be selected in model / its exif appearing in the exif panel / metadata in the metadata panel
- So add the visible feedback of which item is selected : in this case none : the previously selected items have moved to trash
