# PiqoPiqo Image Viewer

PiqoPiqo is a lightweight image viewer built with Python and PySide6. It's designed for speed and efficiency, with a focus on a smooth user experience.

## Features

*   **Fast Thumbnail Generation:** PiqoPiqo uses a multiprocessing pipeline to generate thumbnails in the background, so you can browse your images without any lag.
*   **Dynamic Grid View:** The grid view automatically adjusts to the size of the window, making the most of your screen real estate.
*   **Lazy Loading:** Thumbnails are loaded on demand, which means you can open large folders of images without waiting for everything to load.

## Usage

To run PiqoPiqo, you'll need Python 3 and the dependencies listed in `requirements.txt`. You'll also need to have `exiftool` installed on your system.

```bash
# Install dependencies
pip install -r requirements.txt

# Run the application
python src/main.py /path/to/your/images
```


## Exiftool

Export JSON for all files in DIR:

`exiftool -j -q dir > data.json`

Write keywords : 

`exiftool -sep "," -keywords+="september,2025,automney" -subject+="september,2025,automne" your_image.jpg`

=> standard IPTC Keywords tag + Subject

`-overwrite_original`

Preview image (640x480 in Fujifilm):

`exiftool -b -PreviewImage -w _preview.jpg dir`

`-g` or `-g1`

## gh

`gh pr ready`

`gh pr merge xx --merge --delete-branch`
`gh pr merge xx --rebase --delete-branch`
`--squash`

`gh pr checkout 4` or `co`

`git fetch --prune`