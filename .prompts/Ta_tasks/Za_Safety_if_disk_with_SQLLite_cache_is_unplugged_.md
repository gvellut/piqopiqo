Disk where cache + SQLLite DB for folders was disconnected : error in writing / reading. Then error in reading. 

=> Detect and reload DB + redo DB write : no need to show warning dialog if no data loss (just connection to SQLLite was lost : reconnect to the .db file). If data loss (ie the user has to redo its action : show warning)
Or if not recoverable : show warning and relaunch the application. Make sure to clean everything and sync the qSettings like when quitting (done currentky ?)

Detection whent it happens ? checkfiles test on the disk where the DB is located. Or detection when readf / write is attempted

List the cases and your choice.


2026-03-01 22:56:22 piqopiqo.metadata.save_workers ERROR    Failed to save metadata for /Volumes/CrucialX8/photos/20260209_thorens_aviernoz/tz95/P1423896.JPG: database disk image is malformed
Traceback (most recent call last):
  File "/Users/guilhem/Documents/projects/github/piqopiqo/src/piqopiqo/main_window.py", line 263, in _apply_label_to_grid_selection
    self._apply_label_to_items(
    ~~~~~~~~~~~~~~~~~~~~~~~~~~^
        selected_items,
        ^^^^^^^^^^^^^^^
    ...<2 lines>...
        sync_source="apply_label_shortcut_grid",
        ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
    )
    ^
  File "/Users/guilhem/Documents/projects/github/piqopiqo/src/piqopiqo/main_window.py", line 353, in _apply_label_to_items
    self.edit_panel.update_for_selection(selected_items)
    ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~^^^^^^^^^^^^^^^^
  File "/Users/guilhem/Documents/projects/github/piqopiqo/src/piqopiqo/panels/edit_panel.py", line 294, in update_for_selection
    self._has_missing_data = any(
                             ^^^
  File "/Users/guilhem/Documents/projects/github/piqopiqo/src/piqopiqo/panels/edit_panel.py", line 295, in <genexpr>
    not self.db_manager.get_db_for_image(item.path).has_metadata(item.path)
        ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~^^^^^^^^^^^
  File "/Users/guilhem/Documents/projects/github/piqopiqo/src/piqopiqo/metadata/metadata_db.py", line 570, in has_metadata
    cursor = conn.execute(
        "SELECT 1 FROM photo_metadata WHERE file_path = ? LIMIT 1", (file_path,)
    )
sqlite3.DatabaseError: database disk image is malformed
Traceback (most recent call last):
  File "/Users/guilhem/Documents/projects/github/piqopiqo/src/piqopiqo/main_window.py", line 1587, in on_selection_changed
    self._apply_or_defer_panel_refresh(selected_items=selected_items)
    ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
  File "/Users/guilhem/Documents/projects/github/piqopiqo/src/piqopiqo/main_window.py", line 585, in _apply_or_defer_panel_refresh
    self._update_panels_for_selection(selected_items)
    ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~^^^^^^^^^^^^^^^^
  File "/Users/guilhem/Documents/projects/github/piqopiqo/src/piqopiqo/main_window.py", line 1601, in _update_panels_for_selection
    self.edit_panel.update_for_selection(items)
    ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~^^^^^^^
  File "/Users/guilhem/Documents/projects/github/piqopiqo/src/piqopiqo/panels/edit_panel.py", line 294, in update_for_selection
    self._has_missing_data = any(
                             ^^^
  File "/Users/guilhem/Documents/projects/github/piqopiqo/src/piqopiqo/panels/edit_panel.py", line 295, in <genexpr>
    not self.db_manager.get_db_for_image(item.path).has_metadata(item.path)
        ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~^^^^^^^^^^^
  File "/Users/guilhem/Documents/projects/github/piqopiqo/src/piqopiqo/metadata/metadata_db.py", line 570, in has_metadata
    cursor = conn.execute(
        "SELECT 1 FROM photo_metadata WHERE file_path = ? LIMIT 1", (file_path,)
    ) 
