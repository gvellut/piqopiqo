Filtering

when changing label in fullscreen and with the new label the image would be filtered out  : remove from the grid / model while in fullscreen. Currently, done when exiting fullscreen : the cells visibly move. It should be they move while fullscreen (invisible from the user : he comes back to the grid without the filtered out cells and without seeing the grid move to eject the cells).
Beware that with Filter in fullscreen set to false : the label for a photo can be changed so the photo is filtered out. However, the image is still in the fullscreen loop with that setting. So the user can go back to that iamge while in fullscreen and change the label again to something that is filtered in. The image must not be gone from the grid when exiting fullscreen.

Selection

In grid view :
- when changing sort : scroll to keep selected in visible range. If multiple selected, keep visible the first selected item that was visible in the grid in the original sort (so not necessarily the first in order in the original sort).
- If no selected visible in the original sort (either out of view or no selected) : keep visible the first (in the original sort) visible item => it remains visible in the new sort (visibility does not change so this should be possible).
- Same thing with filter : the selection must remain visible (keep visible the first selected item that was visible before the change in filter)
- if no selected visible in the original filter : keep visible the first (in the original filter) visible item that is also visible in the new filter.
    - If no previously visible item is also visible in the new filter : take as target the item closest (in distance in the model list) to the previously visible items (in any direction) : separate that rule into a function so I can modify it easily or remove it if needs be.
- in both cases use the minimum scroll (up or down) possible. If the target item was in first row (in the viewport), it could be in the last row after the scroll if this is the minimum (it can change relative position in the viewport).


- when fullscreen : going back to grid : 
    - After return from fullscreen : make visible the last image that was in fullscreen (before exiting)
        use minimum scroll amount (up or down) to make that happen : if looping through all the images (single selection), the new image will be selected so this is part of the 

- Ejection : if the current photo is ejected because its label was changed :
    if loop with all the photos : the next photo should be selected 
    if loop with selected photos: when going back if at least one is still filtered in : keep those selected. If none is selected, select the one after the one that was visible when exiting fullscreen



- When Filter in fullscreen set to true: if use shortcut to set label to value not in filter : the next photo is displayed. But it is not selected : the Label shortcut does not work on it. It must work both when images selected => Full screen : if change label but not in filtered => ejected (from the selected + from the Fullscreen loop) : the next item becomes fullscreen. Same thing if only one selected : Full screen : : if change label but not in filtered : the next image become fullscreen (OK) : must become selected too and the label shortcut must work on it. When exiting shortcut, it must be selected.
ou bien qqch diff si pas sélectionnées ? non faire qqch de plus cohérent pour les 2
+ shortcut pour remettre dans la liste si ejecté en fullscreen ?


- Also remmember : once an image disappears from the grid (because it was filtered out) : it is no longer selected. The only exception is when fullscreen : the image can still be part of the loop (if Filter in fullscreen option set to False) so even after a change of status when it is filtered out, another change of status can be performed so that it will make it filtered in. If exiting from fullscreen on it : the image is still in the grid AND is selected (if loop with selected photos : it is still part of the selected photos ; if loop with all the photos : the photo on exit from fullscreen is selected => check if is implemented like that)


- When doing Edit in ... (EXTERNAL_EDITOR processing cf config.py ; _edit_in_external_app in src/piqopiqo/main_window.py) : change selected item in grid to the newly duplicated files.
