Can you check if the images (either the fullscreen or the HQ thumbnails) are freed when not visible in the grid (plus the buffer GRID_THUMB_BUFFER_ROWS) ?
Currently the low res thumbnails should be loaded when the folder is loaded (and never evicted). Can you verify that ?

But I wonder if the HQ thumbnails (either after first loading of the folder ie the thumbnails are generated OR when loading preexisting thumbnails) are correctly evicted when not in the visible range.

The memory seems to grow by a lot while I scoll around : If the HQ thumbnails were evicted, the memory used should be constant ie the low res thumbnails loaded in memory at the beginning + the HQ while visible, but they would be evicted when not in view and replaced by the HQ thumbnails in view: the number of HQ thumbnails in memory would remain the same.

Also check if the fullscreen images are evicted when navigating + when exiting the fullscreen overlay. They should.

Here is the relevant doc in the agents MD : 

> Grid memory policy: embedded previews are kept in memory once loaded; HQ thumbnails are only kept for the visible range plus `Config.GRID_THUMB_BUFFER_ROWS`. If `Config.GRID_HQ_THUMB_DELAY_ENABLED` is true, embedded previews are displayed while navigating (scroll/row movement) and HQ is shown after `Config.GRID_HQ_THUMB_LOAD_DELAY_MS` of idle time; if false, HQ is preferred immediately in the buffered range. HQ eviction only happens outside that buffered range,