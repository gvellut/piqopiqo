Here is the revised specification, configuration summary, layout logic, and execution plan.

### 1. Revised Application Specification

**Project Name:** MacPhotoGrid (Internal Title)
**Target Platform:** macOS (Running locally)
**Tech Stack:** Python 3, PySide6 (Qt), Click (CLI), ExifTool (External).

**Core Functionality:**
The application is a standalone photo viewer designed to replace specific functionalities of Adobe Bridge. It launches via CLI, accepts a root directory, and displays a flattened, recursive view of all images (JPEG, PNG) found within that hierarchy. RAW files and videos are ignored.

**User Interface:**
*   **Main Window:** A single-panel GUI containing a scrollable "Grid View" of thumbnails.
*   **Grid Layout:**
    *   Columns are fixed count (configurable).
    *   Thumbnails are square (aspect ratio 1:1 container), with the image centered inside (preserving aspect ratio).
    *   Metadata (Filename, Creation Date) is displayed in a fixed-height area below the image. Text is truncated with ellipses if too long.
    *   **Padding & Sizing:** Cell dimensions are computed dynamically based on the panel width, column count, and vertical space availability (see layout logic).
*   **Interaction:**
    *   Mouse click selects a cell.
    *   Keyboard arrow keys (Up, Down, Left, Right) navigate the selection.
    *   Scrolling is optimized for large datasets (1000+ images) using lazy loading/virtualization (e.g., `QAbstractItemModel`).

**Image Processing & Caching:**
*   **Pipeline:**
    1.  **Placeholder:** Immediate rendering of a black rectangle.
    2.  **Preview:** Quick extraction of embedded JPEGs using `exiftool` (CLI wrapper).
    3.  **High-Quality:** Generation of a high-res thumbnail (max 1024px) using Python image libraries.
*   **Concurrency:** Heavy lifting (thumbnail generation) is offloaded to a configurable number of background processes to prevent UI freezing.
*   **Storage:** Generated thumbnails are cached in a configurable folder.

**Configuration:**
*   Configuration is held in an in-memory structure (initialized via code defaults, not a UI settings menu).

---

### 2. Configuration Options Summary

The following values must be defined in a central `Config` class or dictionary:

*   **System Paths:**
    *   `CACHE_DIR`: Path to store generated thumbnails.
    *   `EXIFTOOL_PATH`: Path to the external exiftool executable.
*   **Concurrency:**
    *   `MAX_WORKERS`: Integer (Number of background processes for thumbnail generation).
*   **Grid Layout:**
    *   `NUM_COLUMNS`: Integer (Number of columns in the grid).
    *   `PADDING`: Integer (Pixels for horizontal and vertical padding between cells/edges).
    *   `METADATA_LINES`: Integer (Number of lines of text below image).
    *   `FONT_SIZE`: Integer (approximate height in pixels for a line of text).
*   **Image Specs:**
    *   `THUMB_MAX_DIM`: Integer (1024 - Maximum width/height for cached thumbnails).

---

### 3. Pseudo-Code: Dynamic Grid Layout Logic

**Note on Redundancy/Divergence:** The requirement to "increase space equally for all rows" based on available height conflicts slightly with a standard "scrollable" view (where content simply overflows).
*Interpretation:* The logic below assumes you want the row height to snap perfectly to the window height so no partial rows are cut off at the bottom.

```python
def compute_cell_dimensions(panel_width, panel_height, config):
    """
    Computes the geometry for a single cell in the grid.
    """
    
    # 1. Calculate Horizontal Dimensions
    # Assumption: Padding is applied to the left/right of every cell 
    # plus the outer edges.
    # Space used by padding = (columns + 1) * padding
    
    total_horizontal_padding = (config.NUM_COLUMNS + 1) * config.PADDING
    available_width_for_images = panel_width - total_horizontal_padding
    
    # Width of the actual image container (and the cell content width)
    img_box_width = available_width_for_images / config.NUM_COLUMNS
    
    # 2. Calculate Vertical Dimensions (Preliminary)
    # The image box is square.
    img_box_height = img_box_width 
    
    # Calculate fixed metadata height
    # (lines * font_size) + spacing between image and text
    meta_height = (config.METADATA_LINES * config.FONT_SIZE) + config.PADDING
    
    # Base height of one row (without extra vertical stretching)
    # Top Padding + Image + Meta + Bottom Padding
    base_row_height = config.PADDING + img_box_height + meta_height + config.PADDING
    
    # 3. Vertical Stretching Logic (The "Fit to View" requirement)
    # How many full rows fit in the current view height?
    visible_rows_count = floor(panel_height / base_row_height)
    
    if visible_rows_count < 1:
        visible_rows_count = 1
        
    # Calculate remaining vertical space
    used_height = visible_rows_count * base_row_height
    remaining_space = panel_height - used_height
    
    # Distribute remaining space equally to each row
    extra_height_per_row = remaining_space / visible_rows_count
    
    # 4. Final Dimensions
    # We add the extra height to the image container so the text remains anchored
    final_img_box_height = img_box_height + extra_height_per_row
    final_row_height = base_row_height + extra_height_per_row
    
    return {
        "cell_width": img_box_width + (2 * config.PADDING), # Total cell footprint
        "cell_height": final_row_height,
        "image_area_width": img_box_width,
        "image_area_height": final_img_box_height,
        "meta_area_height": meta_height
    }
```

---

### 4. Implementation Plan (Task List for Agent)

You (the Agent) will execute the following plan. Stop after each phase to verify functionality.

#### Phase 1: Core Structure & Data Layer
1.  **Project Setup:** Initialize a Python project structure. Create a `requirements.txt` (Click, PySide6, Pillow).
2.  **Configuration Module:** Create a `config.py` class containing the options listed in the summary above.
3.  **File Scanner:** Create a generic function that accepts a root path, recursively scans for `.jpg`, `.jpeg`, `.png`, and returns a flat list of file objects (Path, Filename, Date Created).
4.  **CLI Entry Point:** Use `Click` to create `main.py`. It should accept the folder path argument, initialize the Config, run the File Scanner, and print the list of found files to stdout (sanity check).

#### Phase 2: Basic GUI Implementation
5.  **Main Window:** Create a PySide6 `QMainWindow`.
6.  **Model/View Setup:** Implement a `QAbstractListModel` (or `QAbstractTableModel`) to hold the list of files. Connect it to a `QListView` (or `QTableView`).
7.  **Custom Delegate (Skeleton):** Create a `QStyledItemDelegate`. For now, just draw a simple rectangle and the filename text.
8.  **Integration:** Update `main.py` to launch the GUI instead of printing text. Ensure the list populates with the file names found in Phase 1.

#### Phase 3: Advanced Layout & Rendering
9.  **Grid Layout Logic:** Port the "Pseudo-Code" logic into the Delegate or View's resize event. Ensure that resizing the window adjusts the number of visible items and their sizes according to the padding/column rules.
10. **Delegate Rendering:** Update the `paint` method of the Delegate:
    *   Draw the image placeholder (black rect).
    *   Draw the Metadata (Filename, Date) in the specified area.
    *   Implement the Ellipsis logic (`elidedText`) for long filenames.
    *   Ensure vertical/horizontal centering of the image area.

#### Phase 4: Thumbnail Pipeline (Multiprocessing)
11. **Thumbnail Manager:** Create a class that manages a `multiprocessing.Pool`.
12. **Job 1 - ExifTool:** Implement the worker function to call `exiftool -b -ThumbnailImage src > dest`.
13. **Job 2 - High Res:** Implement the worker function using Pillow (`PIL`) to generate the 1024px thumbnail if ExifTool fails or as a second pass.
14. **Async Signal/Slot:** Connect the Thumbnail Manager to the GUI. When a thumbnail is ready, it should emit a signal to update the specific index in the Model.

#### Phase 5: Optimization & Interaction
15. **Three-Stage Loading:** Modify the Delegate to request the image from the Manager.
    *   If missing: Draw Black. Trigger ExifTool job.
    *   If ExifTool ready: Draw Low-Res. Trigger High-Res job.
    *   If High-Res ready: Draw High-Res.
16. **Input Handling:** Verify `QListView` default selection works. Override `keyPressEvent` if necessary to ensure Arrow Keys navigate the grid naturally (Up/Down jumps by column count).
17. **Final Polish:** Check for memory leaks (ensure images are not kept in memory unnecessarily) and verify "Lazy" behavior (ensure the view only requests thumbnails for items currently on screen).