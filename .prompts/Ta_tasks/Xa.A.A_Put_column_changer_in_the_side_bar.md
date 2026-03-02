Create a separate component for the column number selector (not independant buttons and labels)

Instead of being in the status bar : 

Move the column number selector to the right side bar : add a third item at the botom above the status bar. Put the column number selector inside it.
Do not use an horizontal QSplitter for that component : make its heigth constant.
Make the column number selector aligned to the left (with some padding from the left border)
Make it so it does not block collapse (see below)


Add a grid shortcut : ctrl ] by default. This will collapse the right sidebar to its minimimum width (should be completely collapsed : this is the case with the Edit panal + EXIF panel in the sidebar currently). Another press will restore the sidebar to its previous size. That state of collapse still makes available the qsplitter mouse action to set the width of the panel (as it is now when the collapse has been done manually)