In grid : 
- I have set the filter to a single label
- I change the label of the last photo in the grid
- so that photo disappears (not in filter)
- I do Undo Label
- the image does not reappaer and I get:

2026-03-22 14:28:22 piqopiqo.metadata.metadata_db DEBUG    Saved metadata for: /Volumes/CrucialX8/photos/20260221_epagny_metz_tessy/tz95/P1434699.JPG
Traceback (most recent call last):
  File "/Users/guilhem/Documents/projects/github/piqopiqo/src/piqopiqo/main_window.py", line 725, in _on_undo_redo_label
    self.grid.refresh_item(item._global_index)
    ~~~~~~~~~~~~~~~~~~~~~~^^^^^^^^^^^^^^^^^^^^
  File "/Users/guilhem/Documents/projects/github/piqopiqo/src/piqopiqo/grid/photo_grid.py", line 1079, in refresh_item
    item = self.items_data[global_index]
           ~~~~~~~~~~~~~~~^^^^^^^^^^^^^^
IndexError: list index out of range
2026-03-22 14:28:25 piqopiqo.metadata.metadata_db DEBUG    Saved metadata for: /Volumes/CrucialX8/photos/20260221_epagny_metz_tessy/tz95/P1434699.JPG
2026-03-22 14:28:26 piqopiqo.shortcuts DEBUG    Ctrl+Control

- however If i change the filter manually : I can see the image has its label undone.

Fix

Possibly related to d28c9528e58b6455340e938c4859625659879885