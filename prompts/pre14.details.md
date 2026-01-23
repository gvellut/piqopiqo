config popup
database of setting
clear cache
set options
remove config.py except as initial : never used beyond default / first launch
except with flag

make it possible to switch app (for exemple with cmd-tab) => currently, the menubar for the other app is displayed but not its windows
cmd-q when fullscreen : not exiting. Need first to exit the full-screen (escape), then the app quits by itself.

ctrl c in debug terminal : 
  File "/Users/guilhem/.local/share/uv/python/cpython-3.13.5-macos-aarch64-none/lib/python3.13/multiprocessing/connection.py", line 395, in _recv
    chunk = read(handle, remaining)
KeyboardInterrupt
  File "/Users/guilhem/.local/share/uv/python/cpython-3.13.5-macos-aarch64-none/lib/python3.13/multiprocessing/process.py", line 313, in _bootstrap
    self.run()
    ~~~~~~~~^^
  File "/Users/guilhem/.local/share/uv/python/cpython-3.13.5-macos-aarch64-none/lib/python3.13/multiprocessing/process.py", line 108, in run
    self._target(*self._args, **self._kwargs)
    ~~~~~~~~~~~~^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
  File "/Users/guilhem/.local/share/uv/python/cpython-3.13.5-macos-aarch64-none/lib/python3.13/multiprocessing/pool.py", line 114, in worker
    task = get()
  File "/Users/guilhem/.local/share/uv/python/cpython-3.13.5-macos-aarch64-none/lib/python3.13/multiprocessing/queues.py", line 384, in get
    with self._rlock:
         ^^^^^^^^^^^
  File "/Users/guilhem/.local/share/uv/python/cpython-3.13.5-macos-aarch64-none/lib/python3.13/multiprocessing/synchronize.py", line 95, in __enter__
    return self._semlock.__enter__()
           ~~~~~~~~~~~~~~~~~~~~~~~^^
KeyboardInterrupt
Error calling Python override of QFrame::paintEvent(): Traceback (most recent call last):
  File "/Users/guilhem/Documents/projects/github/piqopiqo/src/piqopiqo/photo_grid.py", line 573, in paintEvent
    def paintEvent(self, event: QPaintEvent):
    
KeyboardInterrupt
=> correct


to .app for redistribution


burn exif


gpx2exif : not as a lib : itegrate code => same as gpx2exif : will be : georef + burn
Open QGIS folder : preconfigured