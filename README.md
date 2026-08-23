# PiqoPiqo

PiqoPiqo is a lightweight JPEG viewer / metadata editor built with Python and PySide6. 

It is aimed at replacing the workflow I had with Adobe Bridge for triaging JPEG + custom command-line tools. In the current version, it is a relatively basic replacement and it is only for macOS but it is still convenient for me.

![GUI](https://cdn.vellut.com/other/piqopiqo.jpg)

Beyond JEPG triaging and metadata editing, it also allows:

- copy from a SD card (by date, taking into account the last copied images)
- georeferencing from a GPX file (functionality of [gpx2exif](https://github.com/gvellut/gpx2exif))
- upload to [Flickr](https://www.flickr.com/photos/o_0/) (functionality of [Flick API Utils](https://github.com/gvellut/flickr_api_utils))
- setting the lens info for manual lenses
- saving to EXIF

## Limitations

- It only works on macOS (only tested there + some non-abstracted dependencies like `pyobjc`).
- It is limited to JPEG (no support for RAW).
- The EXIF is extracted to an external SQLite DB for edition. It is not possible to directly edit the EXIF but there is a command to save the SQLite data back to EXIF explicitly.
- `exiftool` needs to be installed (used for all EXIF reading and writing + small thumbnail extraction). Homebrew can be used to install it: `brew install exiftool`.
- The only view common with Adobe Bridge is the grid (*Essentials*). All the others (*Libraries*, *Filmstrip*, *Output*, *Metadata*, *Workflow*) are not available (I never used them).

## Usage

```sh
# Install dependencies
uv sync

# Run the application
uv run piqopiqo /path/to/your/images
```

## pyinstaller

It is possible to generate a `.app`. Run:

`uv run task build`

Copy the generated file in the build to your `/Applications` folder.
