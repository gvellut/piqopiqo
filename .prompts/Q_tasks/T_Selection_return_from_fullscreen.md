When I mention the photo list : it means the list of photos sorted (so there is a specific order that can be different from alphabetical) and with filters applied. That list of photos would be the one that would be browsable in the grid.

Correct some issues with selection and filtering in grid view and fullscreen view :

- In grid view :
    - when changing sort : scroll to keep selected in visible range. If multiple selected, keep visible the first selected item that was visible in the grid in the original sort (so not necessarily the first in order in the original sort).
    - If no selected visible in the original sort (either out of view or no selected) : keep visible the first (in the original sort) visible item => it remains visible in the new sort (visibility does not change so this should be possible).
    - Same thing with filter : the selection must remain visible (keep visible the first selected item that was visible before the change in filter)
    - if no selected visible in the original filter : keep visible the first (in the original filter) visible item that is also visible in the new filter.
        - If no previously visible item is also visible in the new filter : take as target the item closest (in distance in the model list) to the previously visible items (in any direction) : separate that rule into a function so I can modify it easily or remove it if needs be.
    - in both cases use the minimum scroll (up or down) possible. If the target item was in first row (in the viewport), it could be in the last row after the scroll if this is the minimum (it can change relative position in the viewport).

    - when selecting multiple images with the mouse : you must keep track of the last (in time) image selected. Then using arrows on the grid will move the selection (single) relative to the last selected. Currently : it seems to always be relative to the last image in the order of the sorted image list (so the order in time not taken into account).
        - this should be the only case where the time is take into account. In the rest of the prompt : when I mention the next selected or the next image : it is in the order of the image list (with sort) and the time shjould not matter.

- in Fullscreen :
    - when the loop goes through all the items selected in the grid : changing the label when one of the items is visible should ONLY change the label of that single item, not of all the selected items (in the grid)
    - With regard to the previous issue :
        -  the shortcut for labels is currently a global QT Application shortcut. The processings should be separate for each type of view. It should be separated for the different views : the effect in fullscreen is different than on the Grid, : so they should be installed separately on both, Not as global QApplication shortcuts. Since the fullscreen is a view on top (visually) of the grid : it should take precedence when activated. Then when the fullscreen is no longer active, the same shortcut keys are active on the grid. So either remove the shortcut from one when the other is visible OR make the fullscreen have priority for the same shortcuts when it is active. 
        - When the grid view is active, other views can be interacted with : filter, metadata edit panel, exif panel. Make sure after interaction on those other views is over (text edit, combobx choosing, button click, checkbox click), the focus comes back to the grid. So that : for example : I can click on a checkbox filter : the item on the grid is still selected and I can use a shortcut to change its label or press space to enter full screen. Sameehing with text fields (on filter or metadata edit) : when Enter is pressed, focus (and shortcuts) should go back to the grid.
        - possibly, it would help to make the set of photos that are part of the loop in fullscreen disctinct from the original list (use references though) or the list of selected items in the list. The shortctuts act differently, they can be ejected differently and with a different lifetime. When entering or exiting fullscreen, there can be a merge.

    - when exiting fullscreen : the last visible photo in the fullscreen view should be visible in the grid and selected (by itself or along with other photos, depending on the status when the fullscreen was started ; see below).

    - When Filter in fullscreen set to true: 
        - Ejection while in fullscreen : if the current photo is ejected because its label was changed (with keyboard shortcut):
            - if loop with all the photos : the next photo in the list of all photos (with filter and sort applied) should become visible (currently done with issue described below)
                - when exiting : that next photo is selected (since it was the current one in fullscreen)
                - if no photo possible (the list of photos is empty after the ejection) : exit : the grid will be empty (no longer any photo in the list)
            - if loop with multiple selected photos: the next photo in the list of selected photos is displayed.
                - when exiting : depending on the value of Fullscreen Exit Behaviour : if KEEP_SELECTION,  the items still in the loop are selected in the grid. If false, only the last visible image is selected in the grid. In both cases, the last visible image is made visible in the grid. use minimum scroll amount (up or down) to make that happen 
                - when no possible photo in the list of selected photos : exit the fullscreen. the photo right after (in the photo list ; sort + filter applied) the last selected one (that was filtered out) is selected and made visible.

            - Current issue : if use shortcut to set label to value not in filter : the next photo is displayed (last photo was ejected). But it is not selected : the Label shortcut does not work on it. It must work both when images selected => Full screen : if change label but not  filtered in => ejected (from the selected + from the Fullscreen loop) : fullscreen view displays the next item. Same thing if only one selected when starting Full screen (full image list loop) : if change label but not  filtered in : the next image become fullscreen (OK) : must become able to use label shortcur on it in fullscreen too. When exiting shortcut, it must be selected and visible

    - When Filter in fullscreen set to false :
        - when exiting fullscreen and going back to grid : 
            - After return from fullscreen : make visible and selected the last image that was in fullscreen (before exiting)
                use minimum scroll amount (up or down) to make that happen : if looping through all the images (single selection), the new image will be selected.
            - the last visible image must be selected. If the fullscreen was a loop of selected image : that image will still be selected. depending on the value of Fullscreen Exit Behaviour : if KEEP_SELECTON,  the items still in the loop are selected in the grid. If it was full image loop (starting from a single selected image) : the selection has changed to the last visible one.
            - the exception is when the current image has been filtered out while fullscreen: on return to the grid, it will be hidden. In a full image loop : The next photo in the list of all the images should become selected and  visible in the grid. With a selected images loop : the next image in the list of selected images should be made visible (depending on the value of  Fullscreen Exit Behaviour it will be the only one selected or the others will also be selected)


- Also remmember : once an image disappears from the grid (because it was filtered out) : it is no longer selected in the grid when exiting. But in fullscreen the list of images in the loop is different (it could be a different data structure) : the image can still be part of the loop (if Filter in fullscreen option set to False) so even after a change of label and it is filtered out, another change of label for the same image can be performed so that it will make it filtered in. If exiting from fullscreen on it : the image is still in the grid AND is selected (if loop with selected photos : it is still part of the selected photos ; if loop with all the photos : the photo on exit from fullscreen is selected => check if is implemented like that).


- When doing Edit in ... (EXTERNAL_EDITOR processing cf config.py ; _edit_in_external_app in src/piqopiqo/main_window.py) : change selected item in grid to the newly duplicated files.

- The Undo Label menu will not work in fullscreen (if changing label using the shorcut) : that menu cannot be accessed anyway. But if a shorctu were to be assigned to it : it should only work on the grid view.

Highlight if goals are conflicted but try to resolve them in the simplest way. Go trough the tree of cases (with settings values and how the fullscreen loop was started and the situation of the last image before exiting)  with regards to visibility, ejection and selection status. And see if you have covered them all. Do not overcomplicate things : try to use the same functions (for example for making the image selected in the grid visible).

Also make sure the update to the selection when filtering or returning to grid view from fullscreen is reflected on other panels that take selection as input (exif panael / metadata edit panel).