Add another tool. In package src/piqopiqo/tools :
manual_lens

In Tools menu: it will be called Set Lens Info ...
Dialog to choose a lens (created in settings) : combobox => not saved in State for last. Just settings and user has to choose every time. OK / cancel
Confim dialog : choose lens, info set + number of images : ok cancel
Set the lens info for all the selected in grid. Error if none is selected.

In metadata DB (hidden) => create those fields in DB for folder
then in save Exif + Flickr upload  : set only if those exists (ie non empty)

In User Settings : List to add lens info : list the keys. add, delete, edit buttons.
Add + edit : form 

All the info : 
-lensmake=Samyang -lensmodel="Samyang 12mm f/2.0 NCS CS"  -focallength=12 -lens="12.0 mm"  -LensInfo="12mm f/?" -FocalLengthIn35mmFormat="18"
Use as key : lensmodel in the settings list + in the Set Lens Info (for user to choose)
  -focallength=12 -lens="12.0 mm"  -LensInfo="12mm f/?" : set only once : the focal length (integer or float) : BUT in  save Exif + Flickr upload : need to save that single value in 3 exiftool tags
