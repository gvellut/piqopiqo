
- When doing Edit in ... (EXTERNAL_EDITOR processing cf config.py ; _edit_in_external_app in src/piqopiqo/main_window.py) : change selected item in grid to the newly duplicated files.
- Add a Search button in filter panel next to search field : it will submit the current search (same as enter while the search text field is active)

- After filter interaction : return focus to grid.  Clicking on a checkbox for filters should return focus to the grid. The workflow : select an item in the grid, click on filter, space to open fullscreen does not work since the focus is not back to the grid after the click on filter

- Search field in filter panel : Enter should return focus to photo grid. do not keep current field active. If an item is selected and is filtered in with the search term : a space bar after the search is submitted should allow the photogrid keypress handler to run and the fullscreen overlay to open.


- Move shortcuts for grid (numbers for labels + No label) to the photo_grid : should not be application wide shortcuts. Use some simlar shortcut system as src/piqopiqo/fullscreen/overlay.py
- Move the shorcuts for fullscreen overlay (numbers for labels + No label) to the overlay : they should work there too. But be setup separately from the grid


- reduce the vertical size of Dialog in src/piqopiqo/panels/save_exif_dialog.py : Make it as big as needed for the components inside  but no more.