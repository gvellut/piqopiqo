Here is the fully updated, detailed implementation plan for the application **piqopiqo**.

**Target Agent Role:** Python/Qt Developer
**Project Name:** piqopiqo
**Dependencies:** Python 3, PySide6, Click, Pillow, ExifTool (System Dependency)

---

### Phase 1: Infrastructure & Core Logic
**Goal:** Establish the project skeleton, configuration, and file scanning capabilities using the new project name.

**Task 1.1: Directory Structure & Environment**
Create the following file structure.
```text
piqopiqo/
├── thumbnails/          # Local storage for generated cache
├── src/
│   ├── __init__.py
│   ├── config.py        # Configuration definitions
│   ├── scanner.py       # Recursive file finding
│   ├── thumb_proc.py    # Multiprocessing worker logic
│   ├── thumb_man.py     # Qt Manager for background jobs
│   ├── gui/
│   │   ├── __init__.py
│   │   ├── window.py    # Main Window
│   │   ├── grid.py      # The Grid View (QListView subclass)
│   │   └── items.py     # The Delegate and Model
│   └── main.py          # CLI Entry point
└── requirements.txt
```

**Task 1.2: Configuration (`src/config.py`)**
Create a static configuration class. Do not use JSON/YAML; keep it in memory.
```python
import os

class Config:
    # Application Settings
    APP_NAME = "PiqoPiqo"
    
    # Paths
    CACHE_DIR = os.path.join(os.getcwd(), "thumbnails") 
    EXIFTOOL_PATH = "exiftool"  # Assumes in PATH
    
    # Concurrency
    MAX_WORKERS = 4
    
    # Grid Layout Options
    NUM_COLUMNS = 5
    PADDING = 10          # Pixels between cells/edges
    METADATA_LINES = 2    # Rows of text below image
    FONT_SIZE = 12        # Approx pixel height of text
    
    # Image Specs
    THUMB_MAX_DIM = 1024  # Max width/height for high-res cache
```

**Task 1.3: File Scanner (`src/scanner.py`)**
Implement `scan_folder(root_path)`.
*   **Logic:**
    1.  Use `os.walk(root_path)`.
    2.  Iterate over files.
    3.  Check extensions: `.jpg`, `.jpeg`, `.png` (Case-insensitive).
    4.  **Exclude:** All other files (RAW, MP4, MOV, etc.).
    5.  Construct a data object (Dictionary) for valid files:
        *   `path`: Full absolute path.
        *   `name`: Filename.
        *   `created`: Format timestamp from `os.path.getctime`.
*   **Sort:** Return list sorted by `name` ascending.

**Task 1.4: CLI Entry Point (`src/main.py`)**
Implement the entry point using `click`.
```python
import click
import sys
from PySide6.QtWidgets import QApplication
from src.config import Config
from src.scanner import scan_folder
from src.gui.window import MainWindow

@click.command()
@click.argument('folder', type=click.Path(exists=True))
def run(folder):
    """PiqoPiqo Image Viewer"""
    # 1. Ensure Cache Dir Exists
    if not os.path.exists(Config.CACHE_DIR):
        os.makedirs(Config.CACHE_DIR)

    # 2. Scan Data
    print(f"Scanning {folder}...")
    images = scan_folder(folder)
    print(f"Found {len(images)} images.")

    # 3. Launch GUI
    app = QApplication(sys.argv)
    window = MainWindow(images)
    window.show()
    sys.exit(app.exec())

if __name__ == "__main__":
    run()
```

---

### Phase 2: The Grid View & Layout Engine
**Goal:** Implement the specific layout calculation where row heights are stretched to fill vertical space.

**Task 2.1: The Data Model (`src/gui/items.py`)**
Create `PhotoModel(QAbstractListModel)`.
*   **Storage:** `self.items = []` (The list of dicts from Scanner).
*   **Custom Roles:**
    *   `Role_Path = Qt.UserRole + 1`
    *   `Role_Date = Qt.UserRole + 2`
    *   `Role_State = Qt.UserRole + 3` (0=Pending, 1=Embedded/LowRes, 2=HighRes)
    *   `Role_Thumb = Qt.UserRole + 4` (The QPixmap)
*   **Method `update_thumbnail(index, pixmap, state)`:**
    *   Update the item at `index`.
    *   Emit `dataChanged(index, index)` so the view repaints only that cell.

**Task 2.2: The Grid View (`src/gui/grid.py`)**
Create `PhotoGrid(QListView)`.
*   **Setup:**
    *   `self.setViewMode(QListView.IconMode)`
    *   `self.setResizeMode(QListView.Adjust)`
    *   `self.setUniformItemSizes(False)` (Important for dynamic resizing)
*   **Layout Calculation (Override `resizeEvent`):**
    *   You must recalculate the grid size every time the window resizes.
    *   **Pseudo-Code:**
    ```python
    def resizeEvent(self, event):
        panel_w = event.size().width()
        panel_h = event.size().height()
        
        cfg = Config
        cols = cfg.NUM_COLUMNS
        pad = cfg.PADDING
        
        # Horizontal Calculation
        total_h_pad = (cols + 1) * pad
        avail_w = panel_w - total_h_pad
        img_box_side = avail_w / cols  # Width and Base Height of image box
        
        # Vertical Calculation (Base)
        meta_h = (cfg.METADATA_LINES * cfg.FONT_SIZE) + pad
        row_base_h = pad + img_box_side + meta_h + pad
        
        # Vertical Stretching (Fit to View)
        if row_base_h < 1: row_base_h = 1
        visible_rows = int(panel_h / row_base_h)
        if visible_rows < 1: visible_rows = 1
        
        used_h = visible_rows * row_base_h
        remaining = panel_h - used_h
        extra_per_row = remaining / visible_rows
        
        # Final Dimensions
        self.cell_w = int(img_box_side + (2 * pad))
        self.cell_h = int(row_base_h + extra_per_row)
        
        # Store calculated rects for the Delegate to use
        self.layout_info = {
            "img_rect_w": img_box_side,
            "img_rect_h": img_box_side + extra_per_row, # Image box takes the stretch
            "meta_h": meta_h,
            "pad": pad
        }
        
        self.setGridSize(QSize(self.cell_w, self.cell_h))
        super().resizeEvent(event)
    ```

**Task 2.3: The Delegate (`src/gui/items.py`)**
Create `PhotoDelegate(QStyledItemDelegate)`.
*   **Paint Method:**
    1.  Get `layout_info` from the parent View (`option.widget`).
    2.  **Selection:** If `option.state & State_Selected`, fill `option.rect` with selection color.
    3.  **Image Logic:**
        *   Retrieve `Status` and `Pixmap` from Model.
        *   Define target rect: X centered in cell, Top = `pad`. Size = `layout_info["img_rect_w"]` x `layout_info["img_rect_h"]`.
        *   If `Status == 0` (Pending): Draw **Black Rect**. Trigger lazy load (see Phase 4).
        *   If `Status > 0` (Loaded): Draw Pixmap centered in target rect (`Qt.KeepAspectRatio`).
    4.  **Text Logic:**
        *   Define target rect: Below image.
        *   Draw Filename (Top line). Use `QFontMetrics.elidedText` to handle overflow.
        *   Draw Date (Bottom line).

---

### Phase 3: Thumbnail Pipeline (Multiprocessing)
**Goal:** Generate thumbnails in background processes to keep UI smooth.

**Task 3.1: Worker Logic (`src/thumb_proc.py`)**
These must be standalone functions (not inside a class) for `multiprocessing` compatibility.
```python
import subprocess
from PIL import Image

def generate_embedded(source, dest_path):
    # Task: Fast extraction
    # Command: exiftool -b -ThumbnailImage "source" > "dest"
    try:
        cmd = [Config.EXIFTOOL_PATH, "-b", "-ThumbnailImage", source]
        with open(dest_path, "wb") as f:
            subprocess.run(cmd, stdout=f, stderr=subprocess.DEVNULL)
        return True if os.path.getsize(dest_path) > 0 else False
    except:
        return False

def generate_hq(source, dest_path, max_dim):
    # Task: High quality resize
    try:
        img = Image.open(source)
        # Convert to RGB if necessary (handle PNG alpha)
        if img.mode in ("RGBA", "P"): img = img.convert("RGB")
        img.thumbnail((max_dim, max_dim))
        img.save(dest_path, "JPEG", quality=80)
        return True
    except:
        return False
```

**Task 3.2: Manager (`src/thumb_man.py`)**
Create `ThumbnailManager(QObject)`.
*   **Attributes:**
    *   `pool`: `multiprocessing.Pool(Config.MAX_WORKERS)`
    *   `pending`: `set()` of file paths currently processing.
*   **Signals:**
    *   `thumb_ready(str file_path, str thumb_type, str cache_path)`
        *   `thumb_type` is "embedded" or "hq".
*   **Method `queue_image(file_path)`:**
    *   If `file_path` in `pending`, return.
    *   Add to `pending`.
    *   **Strategy:**
        1.  Define `cache_path_hq = .../filename_hq.jpg`.
        2.  If `cache_path_hq` exists -> Emit `thumb_ready(..., "hq", ...)` immediately. Remove from pending.
        3.  Else -> Submit async job to Pool to run extraction/generation logic.
            *   *Chain:* Try Embedded first. If success, emit "embedded", then run HQ generation. If Embedded fails, run HQ generation immediately.

---

### Phase 4: Integration & Lazy Loading
**Goal:** Connect the GUI to the Backend.

**Task 4.1: Main Window Wiring (`src/gui/window.py`)**
*   Init `ThumbnailManager`.
*   Connect `manager.thumb_ready` -> `model.on_thumb_ready`.
*   **Model Handler:**
    ```python
    def on_thumb_ready(self, file_path, type, cache_path):
        # 1. Find index for file_path
        # 2. Load QPixmap from cache_path
        # 3. If type == "embedded": state = 1
        # 4. If type == "hq": state = 2
        # 5. self.items[idx]['pixmap'] = pixmap
        # 6. emit dataChanged
        pass
    ```

**Task 4.2: Lazy Loading Implementation**
*   In `PhotoDelegate.paint()`:
    *   If `Status == 0` (Pending):
        *   **Do not** call generation directly here (painting happens 60fps).
        *   Instead, emit a custom signal from the View or call a method `view.request_thumb(index)`.
*   In `PhotoGrid` (View):
    *   Implement `request_thumb(index)`:
        *   Get file path from index.
        *   Call `manager.queue_image(file_path)`.
    *   *Optimization:* The Manager's `pending` set prevents duplicate work, so it's safe to call repeatedly, but cleaner to check status.

---

### Phase 5: Polish & Interaction
**Goal:** Finalize keyboard controls and startup.

**Task 5.1: Keyboard Navigation Overrides**
In `PhotoGrid(QListView)`:
*   Override `keyPressEvent(event)`.
*   **Calculate Index Steps:**
    *   `Up`: Move index `- Config.NUM_COLUMNS`.
    *   `Down`: Move index `+ Config.NUM_COLUMNS`.
    *   `Left/Right`: Standard behavior (`-1`, `+1`).
*   **Bounds Checking:** Ensure you don't select index `< 0` or `> rowCount`.
*   **Selection:** `self.setCurrentIndex(new_index)`.

**Task 5.2: Execution Plan**
1.  Run `python src/main.py /path/to/photos`.
2.  Verify Window Title is "PiqoPiqo".
3.  Verify Black Rectangles appear instantly.
4.  Verify Embedded thumbs appear shortly after (if `exiftool` is working).
5.  Verify High Res thumbs replace them eventually.
6.  Resize window: Verify vertical space distributes equally across rows (images get taller/shorter to fit exactly).