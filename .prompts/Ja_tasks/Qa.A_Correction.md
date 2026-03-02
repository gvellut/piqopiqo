@2026-03-01 at 23.12.14.png The PRE_SCALE_DOWN  : QT_SMOOTH and PILLOW_LANCZOS : both display this when the fullscreen view opens. The image should have taken the whole screen and been scaled down from the 100% image to fit in. When zooming in : the 100% is displayed correctly


The arrows in fullscreen no longer work. (including with PRE_SCALE_DOWN NONE). The next image is non longer displayed. Error on the terminal is 
Error calling Python override of QWidget::keyPressEvent(): Traceback (most recent call last):
  File "/Users/guilhem/Documents/projects/github/piqopiqo/src/piqopiqo/fullscreen/overlay.py", line 974, in keyPressEvent
    self._navigate_to_preserve_zoom(self.current_visible_idx - 1)
    ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
  File "/Users/guilhem/Documents/projects/github/piqopiqo/src/piqopiqo/fullscreen/overlay.py", line 530, in _navigate_to_preserve_zoom
    if self._is_image_completely_offscreen():
       ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~^^
  File "/Users/guilhem/Documents/projects/github/piqopiqo/src/piqopiqo/fullscreen/overlay.py", line 642, in _is_image_completely_offscreen
    return not view_rect.intersects(img_rect)
               ~~~~~~~~~~~~~~~~~~~~^^^^^^^^^^
TypeError: 'PySide6.QtCore.QRect.intersects' called with wrong argument types:
  PySide6.QtCore.QRect.intersects(QRectF)
Supported signatures:
  PySide6.QtCore.QRect.intersects(r: PySide6.QtCore.QRect,


  Are you sure the  100% (and prescaled if not the first displayed) is kept in cache : when PRE_100P is false : there is a small delay to go to 100% from base view : the first time would be understandable, but not after if kept in cache


  The PRE_SCALE_DOWN images must use color management


  this is not sufficient : look at this. There are addition parameters + the color space of the screen