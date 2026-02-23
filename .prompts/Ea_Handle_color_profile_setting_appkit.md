handle the color profile better src/piqopiqo/fullscreen/overlay.py
There are functions in there between # BEGIN COLOR PROFILE and # END
The  _get_monitor_icc_profile and _load_color_managed_pixmap work but you will clean up and add more / rename

First you will add 2 user settings in Interface tab add a group Color
- first a checkbox that is "Force sRGB" : this will make it so no attempt will be made to read the profile of the images : when true it will be set hardcoded to QColorSpace(QColorSpace.NamedColorSpace.SRgb)
- second : a combobox to define the Screen Color Profile : a combobox that will list : From main screen  => default, sRGB, Display P3, Bt2020, No conversion (this for not doing convertToColorSpace ) => set to a a constant (Enum)

defaults are False (profile read from the image) and From main screen (read from the screen with pyobjc)

- also add runtime settings : Color manage embedded thumbnails and Color managed HQ thumbnails => default true + bool : Pillow for Extract image color profile => default false (you will use pyobjc as default)

Add a module below piqopiqo package to put the color related functions. it will be macos only but it is fine 

Then make use of it : 
- when laucnhing read the color profile of the screen (either read from mainscreen with pyobjc) : this will be used later. Read it even when hardcoded or no conversion (so that if the setting changed) : you will still have it.
=> for the main screen see the code in overlay.py . 
- If runtime runtime settings allow : when getting the QPixmap of the thumbnails for display set the color profile and convert (if setting allows). Otherwise : no color management (like now : it is the raw pixels)
- for fullscreen : do the same. For the color profile of the image if not hardcoded to sRGB from settings : try with QPixmap at first : if not valid, try the Extract image color profile either pillow or pyobjc according to runtime setting. 
