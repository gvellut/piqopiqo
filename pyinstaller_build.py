from datetime import datetime
import os
import subprocess

import PyInstaller.__main__

from piqopiqo import __version__ as piqopiqoversion
from piqopiqo.ssf.settings_state import APP_NAME

# info for the about of the built .app
try:
    git_sha = (
        subprocess.check_output(["git", "rev-parse", "--short", "HEAD"])
        .decode("ascii")
        .strip()
    )
except Exception:
    git_sha = "unknown"

build_date = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

# Write info to a python file in the src => will be read by the app
with open("src/piqopiqo/_build_info.py", "w") as f:
    f.write(f"VERSION = '{piqopiqoversion}'\n")
    f.write(f"GIT_SHA = '{git_sha}'\n")
    f.write(f"BUILD_DATE = '{build_date}'\n")


# It is a good idea to handle the path separator for --add-data
# (it's ":" on Mac/Linux and ";" on Windows)
pro_sep = os.pathsep

PyInstaller.__main__.run(
    [
        "pyinstaller_main.py",  # The script to bundle
        f"--name={APP_NAME}",  # App Name
        "--windowed",  # No console
        "--noconfirm",  # Replace output folder without asking
        "--clean",  # Clean cache
        "--icon=app.icns",  # Icon file
        "--exclude-module=pyqtauto",  # Exclude specific module
        "--paths=src",  # Additional import paths
        f"--add-data=app.icns{pro_sep}.",  # Add data file
    ]
)
