Add a user setting : GPX_CHECK_OUTPUT_FORMAT
It will be an enum with 2 values : KML and GPKG. That value will be saved in settings
By default it will be KML (like now).
Replace the name of the ApplyGpxMode.ONLY_KML to ONLY_CHECK (it is the default same as ONLY_KML now). In the dialog Apply GPX : Replace Only generate KML with Only generate <OUTPUT_FORMAT> (so KML or GPKG) depending on the GPX_CHECK_OUTPUT_FORMAT option.

When exporting the check output : with KML.
Add a style="transform: rotate(90deg); transform-origin: center;" to the img : only if the rotation in the metadadb for the photo in question needs it (if no rotation needed do not output it). Replace the 90deg by the determined angle according to the roation. 

With GPKG :
use fiona library
Export a GPKG with a layer for each the folders inside (the same way there is a KML file different for each folder).
there will be 2 fields (apart from the ID and geometry) : photo_path (absolute photo path for the image) + angle in deg for the rotation (if no rotation needed : output 0 as the value)
Use EPSG:4326 as the CRS