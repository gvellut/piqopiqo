Create a separate interface for the watcher and interactiong with watchfiles
the  _begin_workspace_bulk_refresh _finish_workspace_bulk_refresh should not be in main_window
Pass the interface to copy sd

Also the target dirs of copy SD do not matter : always suspend the watcher when doing copy sd. and refresh at the end.
Also do not use load folder at the end : instead do both regenerate thumbnails + read exif If there is no function that does both, then add it (same as when new files are detected).