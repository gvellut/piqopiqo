_extract_embedded_previews in src/piqopiqo/background/media_worker.py
"-ThumbnailImage" is used : images are 160x120. This is fine (no change there).

However, when displayed on the cell : they are smaller than the space available.

src/piqopiqo/grid/photo_cell.py

For lowres thumbnails, make sure they are scaled up (or down : like the hq thumbnails) : they must fit the available space
Or there is a popup when replaced by the HQ thumbnail.
Keep their centering.

You can use PyqtAuto for testing.
You can add a config.py option to only load the lowres thumbnails (no HQ thumbnails laoded) so easy to see if the change you made is fine