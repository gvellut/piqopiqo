The Cmd-Tab  thing is fine. 

However, I sill have Exception ignored in: <function _DeleteDummyThreadOnDel.__del__ at 0x100e40900>
Traceback (most recent call last):
  File "/Users/guilhem/.local/share/uv/python/cpython-3.13.5-macos-aarch64-none/lib/python3.13/threading.py", line 1385, in __del__
TypeError: 'NoneType' object does not support the context manager protocol

When I change the status with the shorcut or if update a field in the metadata edit panel src/piqopiqo/panels/edit_panel.py I get that error on exit