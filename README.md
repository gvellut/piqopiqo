# PiqoPiqo

PiqoPiqo is a lightweight image viewer / metadata editor built with Python and PySide6. 

It is aimed at replacing the workflow I had with Adobe Bridge + custom command-line tools. In the current version, it is a relatively basic replacement and it is only for macOS but it is still convenient for me.

![GUI](https://cdn.vellut.com/other/piqopiqo.jpg)

Beyond image triaging and metadata editing, it also allows:

- copy from a SD card (by date, taking into account the last copied images)
- georeferencing from a GPX file (functionality of [gpx2exif](https://github.com/gvellut/gpx2exif))
- upload to [Flickr](https://www.flickr.com/photos/o_0/) (functionality of [Flick API Utils](https://github.com/gvellut/flickr_api_utils))
- setting the lens info for manual lenses
- saving to EXIF

## Limitations

It only works on macos (only tested there + some non-abastracted dependencies like `pyobjc`).

`exiftool` needs to be installed (used for all EXIF reading and writing + small thumbnail extraction). Homebrew (on macos) can be used to install it: `brew install exiftool`.

The EXIF is extracted to an external SQLLite DB for edition. However, it is possible to save the data back to EXIF explicitly (but not in the course of normal edition).

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
