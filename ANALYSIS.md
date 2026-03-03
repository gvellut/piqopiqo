# PiqoPiqo — Architecture Analysis

## 1. Overview

PiqoPiqo is a macOS photo viewer and metadata editor built with **PySide6** (Qt6 for Python). It targets photographers who need to triage, geotag, and publish images — a workflow previously handled by Adobe Bridge. The application runs as a single-window desktop app with a grid view, metadata panels, fullscreen viewer, and integration with external tools (exiftool, Flickr, GPX tracks).

**Tech stack:** Python 3.14+, PySide6 6.10+, Pillow, pyexiftool, flickrapi, gpxpy, SQLite, pyobjc.

---

## 2. Module Map

```
src/piqopiqo/
├── __main__.py                 # Entry point, CLI (click), app bootstrap
├── main_window.py              # MainWindow — 2 362 lines, central coordinator
├── model.py                    # ImageItem, FilterCriteria, StatusLabel, LabelUndoEntry
├── photo_model.py              # PhotoListModel — filtering, sorting, selection
│
├── grid/                       # Grid view
│   ├── photo_grid.py           #   PhotoGrid widget (custom QWidget, not QListView)
│   ├── photo_cell.py           #   PhotoCell — single thumbnail cell
│   └── context_menu.py         #   Right-click context menu builder
│
├── panels/                     # Right sidebar panels
│   ├── edit_panel.py           #   EditPanel — editable metadata (title, keywords…)
│   ├── edit_widgets.py         #   Custom editors (TitleEdit, KeywordsEdit, CoordinateEdit…)
│   ├── exif_panel.py           #   ExifPanel — read-only EXIF fields
│   ├── filter_panel.py         #   FilterPanel — folder / label / search filtering
│   └── keyword/                #   Keyword tree hierarchy picker
│
├── fullscreen/                 # Fullscreen image viewer
│   ├── overlay.py              #   FullscreenOverlay — full-res display + navigation
│   ├── zoom.py                 #   Zoom state machine (fit, 100 %, 200 %…)
│   ├── pan.py                  #   Pan / drag calculations
│   └── info_panel.py           #   Transient info overlay (zoom %, coordinates)
│
├── metadata/                   # Persistent metadata layer
│   ├── metadata_db.py          #   MetadataDBManager — per-folder SQLite
│   ├── db_fields.py            #   Field enums, EXIF ↔ DB mappings
│   ├── exif_write.py           #   Write edited metadata back to image files
│   └── save_workers.py         #   QRunnable workers for async DB + EXIF saves
│
├── background/                 # Background processing
│   ├── media_man.py            #   MediaManager — orchestrates workers, priority queues
│   └── media_worker.py         #   Multiprocessing worker (EXIF extraction, thumb gen)
│
├── tools/                      # Feature tools
│   ├── copy_sd.py              #   Copy from SD card with date-folder structure
│   ├── save_exif.py            #   Batch EXIF save to files
│   ├── manual_lens.py          #   Manual lens metadata assignment
│   ├── flickr_upload/          #   Flickr upload pipeline (auth, service, workers, albums, dialogs)
│   └── gpx2exif/               #   GPX georeferencing (parsing, time shift, OCR, dialogs)
│
├── components/                 # Reusable UI widgets
│   ├── status_bar.py           #   LoadingStatusBar (progress, error button, counts)
│   ├── column_number_selector.py  # Grid column ± selector
│   ├── ellided_label.py        #   Text-eliding QLabel
│   └── scrollable_strip.py     #   Horizontal scrollable container
│
├── settings_panel/             # Settings dialog
│   ├── dialog.py               #   SettingsDialog (tabbed)
│   ├── schema.py               #   Schema definitions for settings fields
│   ├── editors.py              #   Field editors (path picker, checkbox, enum…)
│   ├── manual_lenses_editor.py #   Lens preset table editor
│   ├── shortcuts_editor.py     #   Keyboard shortcut configuration
│   └── status_labels_editor.py #   Label name/color editor
│
├── ssf/                        # Settings–State Framework
│   └── settings_state.py       #   UserSettingKey, RuntimeSettingKey, StateKey + QSettings wrappers
│
├── platform/
│   └── macos.py                # macOS-specific integration (permissions, menus)
│
├── cache_paths.py              # Cache directory layout (thumb/, db/, per-folder hash)
├── color_management.py         # ICC profile handling, screen color space
├── orientation.py              # EXIF orientation ↔ QTransform mapping
├── keyword_utils.py            # Keyword parsing / formatting
├── label_utils.py              # Label color helpers
├── external_apps.py            # Launch external viewer / editor / Finder
├── folder_scan.py              # Recursive image file discovery
├── folder_watcher.py           # Real-time folder monitoring (watchfiles)
├── shortcuts.py                # Shortcut enum, matching, scope binding
├── startup_mandatory_settings.py  # First-run validation (cache dir, exiftool)
└── utils.py                    # Logging setup, UpperStrEnum
```

---

## 3. Views and Dialogs

### 3.1 Main Window Layout

```
┌─────────────────────────────────────────────────────────┐
│  Menu Bar (File, Edit, Image, View, Tools, Help)        │
├─────────────────────────────────────────────────────────┤
│  FilterPanel   [folder ▾] [■ Red ■ Green …] [search…]  │
├───────────────────────────────────────┬─────────────────┤
│                                       │  EditPanel      │
│                                       │  (title, desc,  │
│         PhotoGrid                     │   keywords,     │
│         (thumbnail cells)             │   coords, time) │
│                                       ├─────────────────┤
│                                       │  ExifPanel      │
│                                       │  (read-only)    │
│                                       ├─────────────────┤
│                                       │  [− N +] cols   │
├───────────────────────────────────────┴─────────────────┤
│  StatusBar   150 of 200 photos  ████░░ 75 %   [Errors] │
└─────────────────────────────────────────────────────────┘
```

- **PhotoGrid** — custom `QWidget` using `QGridLayout` of `PhotoCell` widgets with a manual `QScrollBar`. Not a `QListView` or `QTableView`.
- **EditPanel / ExifPanel** — stacked vertically in a `QSplitter` in the right sidebar. Sidebar is collapsible.
- **FilterPanel** — horizontal strip at top. Folder dropdown, label checkboxes with color swatches, text search.
- **FullscreenOverlay** — separate `QWidget` shown on a dedicated screen, with zoom/pan, keyboard nav, and label shortcuts.

### 3.2 Dialogs

| Dialog | Module | Purpose |
|--------|--------|---------|
| AboutDialog | `dialogs/about_dialog.py` | Version, build info, GitHub link |
| ErrorListDialog | `dialogs/error_list_dialog.py` | Thumbnail/EXIF loading errors |
| MandatorySettingsDialog | `dialogs/mandatory_settings_dialog.py` | First-run: cache dir + exiftool path |
| WorkspacePropertiesDialog | `dialogs/workspace_properties_dialog.py` | Folder summaries, cache cleanup |
| SettingsDialog | `settings_panel/dialog.py` | Tabbed preferences |
| Flickr upload dialogs | `tools/flickr_upload/dialogs.py` | Upload progress, album selection |
| GPX dialogs | `tools/gpx2exif/dialogs.py` | GPX file picker, time shift, preview |

---

## 4. Data Model

### 4.1 Core Classes

```
ImageItem (attrs)
├── path, name, created, source_folder   # Identity
├── is_selected                          # Selection state (mutable)
├── embedded_pixmap / hq_pixmap / pixmap # Three-tier display cache
├── state (0→loading, 1→embedded, 2→HQ) # Loading progress
├── _cache_state_dirty                   # Disk-cache invalidation hint
├── _global_index                        # Position in unfiltered list
├── exif_data: dict                      # Raw EXIF from exiftool
└── db_metadata: dict                    # Editable fields from SQLite

PhotoListModel
├── _all_photos: list[ImageItem]         # Complete set
├── _filtered_photos: list[ImageItem]    # After filter + sort
├── sort_order: SortOrder                # TIME_TAKEN | FILE_NAME | FILE_NAME_BY_FOLDER
└── filter_criteria: FilterCriteria      # folder, labels, search_text

FilterCriteria (attrs)
├── folder: str | None
├── labels: set[str]
├── include_no_label: bool
└── search_text: str
```

### 4.2 Metadata Schema (SQLite)

Each source folder gets its own `metadata.db`:

```
photo_metadata
  id | file_path (UNIQUE) | file_name
  title | description | keywords | latitude | longitude
  time_taken | label | orientation
  manual_lens_make | manual_lens_model
  manual_focal_length | manual_focal_length_35mm
  created_at | updated_at

photo_exif_fields
  file_path | field_key → field_value | updated_at

folder_metadata
  data (PK) → value
```

---

## 5. Data Flows

### 5.1 Image Loading — From Disk to Grid

```
User opens folder
    │
    ▼
folder_scan.scan_folder(path)
    │  Recursively finds .jpg/.jpeg/.png
    │  Returns (list[ImageItem], list[source_folders])
    ▼
MainWindow.__init__
    │  Creates PhotoListModel with ImageItem list
    │  Creates MetadataDBManager (one SQLite per source folder)
    │  Creates MediaManager (multiprocessing worker pool)
    ▼
MediaManager.reset_for_folder(items)
    │  Queues all items for background processing
    │  Priority: visible items first, off-screen later
    │
    ├──▶ Worker: extract embedded JPEG thumbnail from EXIF
    │       → cache to {cache}/thumb/embedded/{name}.jpg
    │       → emit thumb_ready(path, QPixmap)
    │
    ├──▶ Worker: generate HQ thumbnail via Pillow
    │       → Image.thumbnail(max_dim) at JPEG quality 80
    │       → preserve ICC profile
    │       → cache to {cache}/thumb/hq/{name}.jpg
    │       → emit thumb_ready(path, QPixmap)
    │
    └──▶ Worker: extract EXIF via exiftool (batch)
            → parse editable fields (title, keywords, GPS, time…)
            → store in MetadataDBManager (SQLite)
            → emit editable_ready(path, metadata_dict)
            → emit panel_fields_ready(path, exif_fields_dict)
```

### 5.2 Thumbnail Pipeline — Three Tiers

```
                    ┌──────────────┐
                    │  Source File  │
                    └──────┬───────┘
                           │
              ┌────────────┼────────────┐
              ▼                         ▼
    Embedded JPEG                 HQ Thumbnail
    (from EXIF tag)              (Pillow resize)
    ~160×120 px                  configurable max_dim
    instant extraction           slower, higher quality
              │                         │
              ▼                         ▼
         embedded_pixmap           hq_pixmap
              │                         │
              └──────────┬──────────────┘
                         ▼
              apply_orientation_to_pixmap()
                         │
                         ▼
                    item.pixmap
                    (displayed in grid)
```

**Memory management:** Pixmaps outside a configurable buffer window (rows above/below viewport) are evicted to `None` to prevent unbounded memory growth.

### 5.3 Metadata Editing — Edit Panel to EXIF

```
User edits field in EditPanel
    │
    ▼
EditPanel emits metadata_saved(field_name)
    │
    ▼
MainWindow handler
    ├── Update ImageItem.db_metadata in memory
    ├── MetadataDBManager.update_field() → SQLite
    ├── Refresh grid cell display (keywords, label…)
    └── Refresh ExifPanel if selection matches
    │
    ▼ (later, on "Save EXIF" action)
MetadataSaveWorker (QRunnable)
    │
    ▼
exif_write.py → exiftool -overwrite_original
    │  Uses MWG (Metadata Working Group) tags
    │  for cross-standard compatibility
    └── Title → XMP:Title + IPTC:ObjectName
        Description → MWG:Description
        Keywords → MWG:Keywords
        GPS → EXIF:GPSLatitude/Longitude
        Time → EXIF:DateTimeOriginal
```

### 5.4 GPX Georeferencing Flow

```
User: Tools → Apply GPX
    │
    ▼
GPX dialog → select .gpx file
    │
    ▼
gpx_processing.py
    │  Parse track segments via gpxpy
    │  Extract GpxPoint(time, lat, lon) list
    │  Normalize to UTC
    │
    ▼
Time Shift determination
    ├── Manual: user enters offset
    └── OCR: Google Cloud Vision reads clock from photo
    │
    ▼
compute_position(image_time + shift, segments, tolerance)
    │  Linear interpolation between nearest track points
    │
    ▼
Write lat/lon to ImageItem.db_metadata
    │
    ▼
Optional: generate KML file with placemarks
```

### 5.5 Flickr Upload Flow

```
User: Tools → Upload to Flickr
    │
    ▼
Flickr auth (OAuth2, token cached in SQLite)
    │
    ▼
Validate selected photos
    │  Check: title present? keywords present? (configurable)
    │
    ▼
Upload pipeline (multiprocessing workers):
    Stage 1: Upload binary         → flickr.upload()
    Stage 2: Poll ticket status    → flickr.photos.upload.checkTickets()
    Stage 3: Reset date            → flickr.photos.setDates()
    Stage 4: Make public           → flickr.photos.setPerms()
    Stage 5: Check/create album    → flickr.photosets.create()
    Stage 6: Add to album          → flickr.photosets.addPhoto()
    │
    └── Retry logic: 6 attempts, 5 s delay
```

### 5.6 View Synchronisation — Signal Graph

```
PhotoListModel
    │
    │ photos_changed ──────────▶ MainWindow._on_model_changed()
    │                                ├── grid.set_data(filtered)
    │                                ├── status_bar.set_photo_count()
    │                                └── reconcile panels
    │
    │ photo_added/removed ─────▶ MainWindow._on_photo_added/removed()
    │                                ├── update media_manager
    │                                ├── update filter_panel folders
    │                                └── grid.set_data()
    │
PhotoGrid
    │
    │ selection_changed(set) ──▶ MainWindow.on_selection_changed()
    │                                ├── update photo_model selection
    │                                ├── defer panel refresh (120 ms debounce)
    │                                └── update edit_panel + exif_panel
    │
    │ visible_paths_changed ───▶ MainWindow → media_manager.set_visible()
    │                                (prioritize loading for visible items)
    │
    │ context_menu_requested ──▶ show context menu
    │
    │ fullscreen_requested ────▶ FullscreenOverlay.show()
    │
FilterPanel
    │
    │ filter_changed(criteria) ▶ MainWindow._on_filter_changed()
    │                                └── photo_model.set_filter()
    │
EditPanel
    │
    │ metadata_saved(field) ───▶ MainWindow → DB save + grid refresh
    │
MediaManager
    │
    │ thumb_ready(path, px) ───▶ MainWindow.on_thumb_ready()
    │                                └── item.pixmap = px → grid refresh cell
    │
    │ editable_ready(path, d) ─▶ MainWindow._on_editable_ready()
    │                                └── item.db_metadata = d → panel refresh
    │
    │ exif_progress_updated ───▶ StatusBar progress bar
    │
FolderWatcher
    │
    │ changes_detected ────────▶ MainWindow → add/remove ImageItems
```

---

## 6. Cache Architecture

### 6.1 Disk Layout

```
{cache_base}/                           # ~/Library/Application Support/PiqoPiqo/cache
  {md5(folder_path)}/                   # Per-folder hash directory
    thumb/
      embedded/{basename}.jpg           # Low-res EXIF preview
      hq/{basename}.jpg                 # Pillow-generated thumbnail
    db/
      metadata.db                       # SQLite — editable fields + EXIF panel fields
```

### 6.2 Memory Cache

| Layer | Stored on | Eviction |
|-------|-----------|----------|
| `embedded_pixmap` | `ImageItem` | Outside `GRID_EMBEDDED_BUFFER_ROWS` of viewport |
| `hq_pixmap` | `ImageItem` | Outside `GRID_THUMB_BUFFER_ROWS` of viewport |
| `pixmap` | `ImageItem` | Rebuilt from above on orientation change |
| `db_metadata` | `ImageItem` | Never evicted (small dict per image) |
| `exif_data` | `ImageItem` | Never evicted (raw EXIF dict) |

### 6.3 Settings Persistence

- **QSettings** (macOS plist): window geometry, last folder, sort order, user preferences, keyboard shortcuts, API keys.
- **SQLite** (per folder): editable photo metadata, EXIF panel field cache, folder-level metadata (e.g. Flickr album ID).
- **SQLite** (Flickr): OAuth tokens at `{cache}/flickr/oauth-tokens.sqlite`.

---

## 7. Background Processing Model

```
MainWindow (main thread, Qt event loop)
    │
    │ owns
    ▼
MediaManager
    │
    ├── Priority queue (3 levels):
    │     1. EXIF write ops (user-initiated, highest)
    │     2. Visible file processing (currently on screen)
    │     3. Off-screen file processing (prefetch)
    │
    ├── Multiprocessing workers (spawn context):
    │     • Separate processes to avoid GIL
    │     • Each runs exiftool + Pillow
    │     • Configurable pool size (MIN_IDLE_WORKERS … MAX_WORKERS)
    │     • Batch EXIF: multiple files per exiftool invocation
    │
    └── QThreadPool (metadata saves):
          • MetadataSaveWorker (QRunnable)
          • DB writes + EXIF file writes
          • drain_qthread_pool() on shutdown
```

---

## 8. Key Architectural Patterns

| Pattern | Where Used |
|---------|------------|
| **Qt Signals/Slots** | All inter-component communication |
| **Model–View** | `PhotoListModel` → `PhotoGrid` (but not Qt's `QAbstractItemModel`) |
| **Multiprocessing** | EXIF extraction, thumbnail generation (avoids GIL) |
| **Thread pool** | Metadata saves, workspace cleanup |
| **Debouncing** | Panel refresh on large selections (120 ms) |
| **Lazy loading** | HQ thumbnails loaded on-demand as viewport scrolls |
| **Memory eviction** | Pixmaps outside buffer window set to `None` |
| **Per-folder isolation** | Each source folder gets its own SQLite DB and cache subtree |
| **Schema migration** | Lazy column addition and format migration in `MetadataDBManager` |
| **Observer** | Folder watcher detects file system changes → signal → model update |

---

## 9. External Tool Dependencies

| Tool | Role | Binding |
|------|------|---------|
| **exiftool** | EXIF read/write | `pyexiftool` (subprocess wrapper) |
| **Pillow** | Thumbnail generation, image conversion | Direct Python API |
| **Google Cloud Vision** | OCR for time-shift detection | `google-cloud-vision` |
| **Flickr API** | Photo upload, album management | `flickrapi` |
| **gpxpy** | GPX track parsing | Direct Python API |
| **fastkml / lxml** | KML generation | Direct Python API |
| **watchfiles** | File system monitoring | Rust-backed, daemon thread |
| **send2trash** | Safe file deletion | Platform-native trash |
| **show-in-file-manager** | Reveal in Finder | Platform-native |
| **pyobjc** | macOS menu suppression, permissions | Cocoa/Quartz bridges |
