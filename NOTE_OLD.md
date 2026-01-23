=== Trello doc

Voir sur Project  Current plutôt. Laissé ici pour backup


make it impossible to resize the full screen when dragging borders => OK
make it possible to switch app (for exemple with cmd-tab) => currently, the menubar for the other app is displayed but not its windows
cmd-q when fullscreen : not exiting. Need first to exit the full-screen (escape), then the app quits by itself.
=> see Programming Notes current

OK:
multiselect :  in the grid, multiple selections
fullscreen with space : handle cycle through them with fullscreen. Go back to first one.
config : mode : when exiting, they are all selected or just the last one


exif panel : read every time ? for now. Launch batch process

db for photo : for some fields only
label

reorder the queue for thumbnails : if scrolling
double queues for preview + gen
refresh photos
add photos to folder

handle single mouse click to 1x : if already 1x : no effect
like single wheel : zoom on clicked pixel
other single click : go back
verify pixel of image is physical pixels and not logical

filter : folder for now
order : by some exid attribute (DTO)

number of columns

edit data : title description GPS
burn exif

changer le empty space : constant pixel in screen space. Think about it when image has diff ratio as screen. => or make it no discontinuity but if empty space goes out of screen, it becomes a max size so zoom in zoom out have no discontinuity but max

config to keep zoom factor when changing photos
config for zoom : below pointer, keep currently view center at the center

keyboard shortcuts : zoom, grid only, labels
mouse zoom : when clicking => to real size

gpx2exif
upload to flickr

config panel
clear cache
to .app for redistribution

================

Bridge :

preview is 2048
also has preview 256

reject ? + hides by default + show rejected

rename special import for macos
make it work on other than macos





=== EXIF db


- create db of EXIF tags of photos when loading the folder : cache the exif tags defined in the config per photo
- use sqllite db
- exif db in the background
- when displaying the value : read from the db instead of reading from the exif from the file
- if exif tags changed between runs of piqopiqo (in the config.py file) : if new tag added, will need to detect and recache the exif in the db when loading; if only removed : not need to delete
- create subfolder for the db
- when read, if not all the configured tags are present for a photo (because reloaded in the background) : it is fine to not display them as empty (or not present) in the GUI for the time being : the user will have to refresh the panel
- add a button to refresh the EXIF panel (read the photos from db )


==== Programs Doc


Tasks


test with very large number of photos

cache by origin folder
thumbs + db => by folder

db for photo : for the title + keyword only + label
label : right click +  swatch below photo
panel form data : title kw



application wide shortcut : physical key : so works in any layout
Grid only withouth the columns

keyword panel : tree : from serialized file for now


open folder

record if exif was set already by piqopiqo : using Datetime Original ; check before uploading to flickr => copy image, update exif (only if exif not updated), upload, delete copy ; OR upload image + set datetime with API instead after the fact ; same for location
https://aistudio.google.com/prompts/1dz6eKtA_qz3ORYYfYuSJssX21dVxp66u
Interactive :
filter : folder for now => so no need for exif for all the photos
order : by some exid attribute (DTO)
number of columns


free qpixmap that have disappeared 
or with a margin

launch batch image + exiftool : keep exitool process around
priority exiftool PreviewImage for all + exif ; full preview for visble priority : if not visible => after the PreviewImages
batch exiftool : lokky  https://aistudio.google.com/prompts/1p47fLri2-PzLeFtFmXrFaTw6R-DmCLKE 
reorder queues (see last)
drop idle processes
exiftool : external process so threads : QThreadPool currently : see manage both



edit data : title description
changer le empty space : constant pixel in screen space. Think about it when image has diff ratio as screen. => or make it no discontinuity but if empty space goes out of screen, it becomes a max size so zoom in zoom out have no discontinuity but max




reorder the queue for thumbnails : if scrolling
double queues for preview + gen
refresh photos
add photos to folder

Later implement issues with current changes :
config to keep zoom factor when changing photos
config for zoom : below pointer, keep currently view center at the center

check if the photos are kept in memory : pas tres grave si le cas => oui les photo resized
charge si devient visible
jamais decharge
=> garder un maximum en mémoire : décharger ensuite si plus grand , recharger depuis le disque si visible

config popup
database of setting
clear cache
set options
remove config.py except as initial : never used beyond default / first launch
except with flag
