# PiqoPiqo Image Viewer

PiqoPiqo is a lightweight image viewer built with Python and PySide6. It also allows georeferencing from a GPX file + upload to Flickr. 

It is aimed at replacing the workflow I have with Adobe Bridge + custom command-line tools.


## Limitations

Currently, it only works on macos (only tested there + some non-abastracted dependencies like `pyobjc`).

You'll also need to have `exiftool` installed on your system. Homebrew can be used to install it: `brew install exiftool`

## Usage

```bash
# Install dependencies
uv sync

# Run the application
uv run piqopiqo /path/to/your/images
```
