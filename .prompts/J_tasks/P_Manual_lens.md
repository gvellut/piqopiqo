Add another tool. In package src/piqopiqo/tools :
manual_lens

In Tools menu: it will be called Set Lens Info ...
Dialog to choose a lens (created in settings) : combobox => not saved in State for last. Just settings and user has to choose every time. OK / cancel. Error if none is selected.
Then confim dialog : chosen lens, info of which information (exiftool tags) will be set + number of images : ok cancel
Set the lens info for all the selected in grid. 

In metadata DB (hidden) => create those fields in DB for folder like title or description. No need to precreate them : only when the Manuel lens tool is used.
then in save Exif + Flickr upload  : set only if those exists (ie non empty like it is now I think)

In User Settings : add List to add lens info : list the keys. add, delete, edit buttons.
Add + edit : form with the values to be filled by the user. Use standarad Qt placeholders (use Samyang below)

All the info : 
-lensmake=Samyang -lensmodel="Samyang 12mm f/2.0 NCS CS"  -focallength=12 -lens="12.0 mm"  -LensInfo="12mm f/?" -FocalLengthIn35mmFormat=18
Use as key : lensmodel in the settings list + in the Set Lens Info (for user to choose)
  -focallength=12 -lens="12.0 mm"  -LensInfo="12mm f/?" : set only once : the focal length (integer or float) : BUT in  save Exif + Flickr upload : need to save that single value in 3 exiftool tags with the formatting

  (the focallength + 35mm can be a float : with . or , as decimal separator ; when writing use the . form for all the values)
