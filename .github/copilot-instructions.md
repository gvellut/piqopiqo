## About This Repository

This repository contains the source code for "Piqopiqo", a macOS photo browser and metadata viewer and filler, that could act as a replacement for Adobe Bridge for a subset of functionalities.

The goal is to create a high-performance application with a clean, streamlined user interface.

## Core Architecture Principles

0.  **Python**
    -   uv as the dependency manager
    -   Python 3.13 as the python version

1.  **User Interface:**
    -   Prioritize performance for the image grid. Use a lazy grid to ensure only visible cells are rendered.

2.  **Key Dependencies:**
    -   JPEG and PNG are the only image formats targetted (no RAW or video files).
    -   Use pyexiftool for exif reading
    -   pyside6 as the GUI libary

7.  **Coding Style:**
    -   no async

8. **Ignore and don't**
    -   Completely disregard the pprevious_py_test folder, prompts folder and the NOTES.md file
    -   don't use node or npx ever


11. **Initial State**
    -   A project is already set up with a python project
