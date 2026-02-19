Model sync

Make sure photo list model is center of everything : list of photos, filtered, selected => should update the panels
Or have a central controller that manages the sync

Make the loading of folder initial currently in __main__.py dealt with in controller or model. The scan folder should not be part of the main

all syncs : folder selection sort filtered settings panels grid cells shortcuts status_bar
must be coherent between them (except possibly temporarily when acting on the sync)

main_window (Pyside Window)  should not be the central hub for the model

_update_status_bar_count
_on_photo_removed
_on_photo_added
_on_clear_all_data
_on_model_changedon_thumb_ready
on_selection_changed
_load_folder
_stop_folder_watcher
_start_folder_watcher
_suppress_watcher_paths
_on_setting_saved
_apply_settings_changes

=> in more specific settings or the controller
