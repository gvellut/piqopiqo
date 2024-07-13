# piqopiqo

micromamba create -n piqopiqo_312 python~=3.12.0

PyExifTool ?

digikam
  Thumbs database https://www.digikam.org/about/features/
  map view
  Synchronized panning and zooming https://userbase.kde.org/Digikam/LightTable pour comparaison
  color space
Adobe Bridge


https://doc.qt.io/qtforpython-5/overviews/qtwidgets-widgets-imageviewer-example.html
https://github.com/shkolovy/simple-photo-editor
https://github.com/ap193uee/PyQt-Image-Viewer


https://stackoverflow.com/questions/42673010/how-to-correctly-load-images-asynchronously-in-pyqt5

Borders
https://doc.qt.io/qt-6/qml-qtquick-controls-frame.html

- load folder command line => Thumbnails
  - optimize : show only visible    
- View image Full Screen hi DPI support
  - shortcuts : using space
- thumbnail cache

- Read EXIF including XMP
    - start with the date original only
- write exif data in DB SQL lite outside
  - centralized location

- labels + display colors : assign labels
- shortcuts : use layout independent keys
https://stackoverflow.com/questions/76889721/how-can-i-get-the-key-without-modifiers-on-keypressevent-in-qt

EXIF:
- display in widget
- edit exif data
- write exif data in file (optional)
  - for the flicker upload tool to work
  - or update the tool to read inside SQL Liste DB outside photos

HiDPI
https://doc.qt.io/qt-6/highdpi.html
  https://doc.qt.io/qt-6/qpainter.html#drawing-high-resolution-versions-of-pixmaps-and-images

- test pyside6-deploy
 voir https://pypi.org/project/hatchling/
 set CFBundleName (or maybe as arg to BUNDLE) :
 app = BUNDLE(
    ...
    info_plist={
      "NSBluetoothAlwaysUsageDescription": "I want your bluetooth and I want it now",
   },
)

- zoom image until full resolution
  - shortcuts
- pan image
QGraphicsView ?
https://doc.qt.io/qt-6/examples-graphicsview.html
https://svenssonjoel.github.io/pages/qt_game_loadimage/index.html
- ou QScrollBar to start with

- size of thumbnails

- Docking dialogs
- navigate folders : show directories
- open menu
- favorites
- list of folders ; copy Adobe Bridge

- open Gimp
- Duplicate

- sorting (other than by date original)
- filtering

Keywords management:
- Tag tree
- Tag path edition
- tag replace batch

- configuration
  - keyboard shortcuts
  - list of labels
  - cache parameters : location, size, generation, parallel processes
  
  - zoom etapes > full ; cache config; clear cache ; size Thumbnails
  - config tag format : , or ;


- tool for comparing images  : Synchronized panning and zooming
- selection : different modes (keep selected)
- stacks


- autodetect changes to meta

- delta date

- GPX
- open KML or map / generate KML
- Virtual folder => multiple folders edit or specific photo files
- Simple editing : rotate, crop ?, contrast, exposure (gegl), brightness
- batch operations : + delete

- Link with Flickr:
- config ; API Key; login
- upload / creaste albums
- browse : photostream, albums, groups, tags, favorites ; see how it is done in Android App
- edit existing ; see what is done in Organizr : make better
- batch operations : replace title, tag, suppr, etc see scripts flickr-utils
- download bulk
- GPX
- download KML
- open KML or map

- Create slideshow :
- choose photos + reorder
- record audio : comment tied to each photo
- slice and create ALS file 
 - include empty clips ?
 - ajouter une track video avec la photo ? ou plusieurs clips : devront être bougés manuellement si audio track est modifiée ; check warp + leader
- dans ableton possibilité d'ajouter des videos
- export audio soundtrack : comment + music
- export to video : select the soundtrack + ALS + folder => video file


- generer Slideshow video avec images Flickr + transitions + carte avec Google Earth Video
- voir opensource video editor
- cf http://ffdiaporama.tuxfamily.org/
- voir si choix photo + video + enregistrement audio dans l'appli mais montage export vers Shortcut
- voir si utiliser Audacity pour l'enregistrement audio ou montage : ou pyaudio

- https://openclipart.org/
- videoporama : https://www.videoporama.tuxfamily.org/