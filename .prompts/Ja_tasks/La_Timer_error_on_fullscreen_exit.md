When returning from full screen : I saw once 

Traceback (most recent call last):
  File "/Users/guilhem/Documents/projects/github/piqopiqo/src/piqopiqo/fullscreen/info_panel.py", line 181, in _on_timer_expired
    self._overlay.hide()
    ~~~~~~~~~~~~~~~~~~^^
RuntimeError: Internal C++ object (PySide6.QtWidgets.QLabel) already deleted.

Probably : need to stop timers when exiting fullscreen. Check.
Does not happen often (with the way I use)
