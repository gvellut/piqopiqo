Problems on quit :

- If use the set label shortcut in grid view :

If I quit, I get this error in the terminal :

Exception ignored in: <function _DeleteDummyThreadOnDel.__del__ at 0x104c00900>
Traceback (most recent call last):
  File "/Users/guilhem/.local/share/uv/python/cpython-3.13.5-macos-aarch64-none/lib/python3.13/threading.py", line 1385, in __del__
TypeError: 'NoneType' object does not support the context manager protocol

If I launch then quit without doing anything, nothing is displayed


- When I quit : if I do a Cmd-Tab while the window is still there (app not yet terminated). The app switcher does not show right away. Then the app really quits but the app switcher shows up again and goes through mutliple apps as if I had ket cmd and press tab multiple times