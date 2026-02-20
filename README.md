# PiqoPiqo

PiqoPiqo is a lightweight image viewer / metadata editor built with Python and PySide6. Beyond image triaging and metadata editing, it also allows georeferencing from a GPX file + upload to Flickr. 

It is aimed at replacing the workflow I had with Adobe Bridge + custom command-line tools. In the current version, it is a relatively basic replacement but I am planning some enhancements in the future.

## Limitations

Currently, it only works on macos (only tested there + some non-abastracted dependencies like `pyobjc`).

You'll also need to have `exiftool` installed on your system. Homebrew (on macos) can be used to install it: `brew install exiftool`.

## Usage

```bash
# Install dependencies
uv sync

# Run the application
uv run piqopiqo /path/to/your/images
```

## pyinstaller

You can generate a `.app`. Run:

`uv run task build`

Copy the generated file in build to your `/Applications` folder.

## icns converter

https://cloudconvert.com/png-to-icns