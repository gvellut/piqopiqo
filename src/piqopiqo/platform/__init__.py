# ruff: noqa: F403
import sys

if sys.platform == "darwin":
    from .macos import *

# elif sys.platform == "win32":
#     from .win32 import *
# elif sys.platform.startswith("linux"):
#     from .linux import *
