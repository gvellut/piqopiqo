### **Project Goal: macOS Photo Browser**

The objective is to create a native macOS application, a lightweight replacement for Adobe Bridge, using a Swift/SwiftUI front-end and a Rust core library for all backend processing. The entire development workflow will be centered around VSCode and command-line tools.

### **Core Technologies**

*   **GUI:** Swift with the SwiftUI framework. The UI will be defined programmatically.
*   **Backend Logic:** A Rust library (`.a` static library) containing all file processing, thumbnail generation, and metadata extraction logic.
*   **Build System:** Swift Package Manager (SwiftPM) for the Swift app and Cargo for the Rust library. A shell script will coordinate the build process.
*   **Interop:** A C-style Foreign Function Interface (FFI) will be created for Swift to call the Rust library. `cbindgen` will be used to generate the C header file.
*   **Editor:** VSCode, with launch and task configurations for building and debugging.

---

### **Part 1: Project Structure**

Create the following directory structure. This keeps the GUI and core logic separate but contained within a single project folder.

```
mac-photo-browser/
├── .vscode/
│   ├── launch.json
│   └── tasks.json
├── GuiApp/              (SwiftPM Package)
│   ├── Package.swift
│   └── Sources/
│       └── GuiApp/
│           ├── Main.swift
│           ├── Views/
│           │   ├── ContentView.swift
│           │   ├── GridView.swift
│           │   └── DetailView.swift
│           └── RustBridge/
│               ├── RustBridge.swift
│               ├── module.modulemap
│               └── core_lib.h  (This will be generated)
├── CoreLib/             (Cargo Package)
│   ├── Cargo.toml
│   ├── cbindgen.toml
│   └── src/
│       ├── lib.rs
│       ├── config.rs
│       └── processing.rs
└── build.sh             (Master build script)
```

---

### **Part 2: The Rust Core Library (`CoreLib`)**

This library is the engine. It must not contain any UI code.

#### **1. Setup**

Navigate into the `CoreLib` directory and run:
`cargo new --lib .`

Modify `CoreLib/Cargo.toml` to specify the crate type for a static library and add dependencies:

```toml
[package]
name = "core_lib"
version = "0.1.0"
edition = "2021"

[lib]
crate-type = ["staticlib"] # Generates a .a file

[dependencies]
image = "0.25"             # For thumbnail generation
rayon = "1.10"             # For parallel processing
serde = { version = "1.0", features = ["derive"] }
toml = "0.8"               # For parsing configuration
walkdir = "2.5"            # For iterating through directories
```

#### **2. Configuration (`src/config.rs`)**

Define the application's configuration. This struct will be loaded from a `config.toml` file.

```rust
use serde::Deserialize;

#[derive(Deserialize)]
pub struct Config {
    pub thumbnail_cache_path: String,
    pub thumbnail_size: u32,
    pub processing_threads: usize,
    pub metadata_fields: Vec<MetadataField>,
    pub date_format: String,
}

#[derive(Deserialize)]
pub enum MetadataField {
    Filename,
    DateCreated,
    DateModified,
}
```

#### **3. Image Processing (`src/processing.rs`)**

Implement the logic for creating thumbnails.

```rust
use image::{imageops::FilterType, DynamicImage};
use std::path::Path;

pub fn create_thumbnail(image_path: &Path, max_dimension: u32) -> Option<Vec<u8>> {
    if let Ok(img) = image::open(image_path) {
        let thumbnail = img.resize(max_dimension, max_dimension, FilterType::Lanczos3);
        // In-memory buffer to hold the PNG-encoded thumbnail
        let mut buffer = std::io::Cursor::new(Vec::new());
        if thumbnail.write_to(&mut buffer, image::ImageOutputFormat::Png).is_ok() {
            return Some(buffer.into_inner());
        }
    }
    None
}
```

#### **4. C API Layer (`src/lib.rs`)**

This is the bridge to Swift. Expose functions using a C-compatible interface.

```rust
use std::ffi::{c_char, CStr, CString};
use std::os::raw::c_void;

// Define a C-compatible struct for file metadata
#[repr(C)]
pub struct FileMetadata {
    pub filename: *mut c_char,
    pub created_date: *mut c_char,
    pub modified_date: *mut c_char,
}

// Function to get metadata for a file
#[no_mangle]
pub extern "C" fn get_file_metadata(path: *const c_char) -> *mut FileMetadata {
    // ... (Implementation to read filesystem data) ...
    // ... (Allocate memory for FileMetadata and its fields with CString) ...
    // ... (Use Box::into_raw to return a pointer) ...
    std::ptr::null_mut() // Placeholder
}

// Function to free the memory for the metadata struct
#[no_mangle]
pub extern "C" fn free_file_metadata(ptr: *mut FileMetadata) {
    if !ptr.is_null() {
        unsafe {
            // Free the strings inside the struct
            if !(*ptr).filename.is_null() {
                drop(CString::from_raw((*ptr).filename));
            }
            // ... (free other strings) ...
            
            // Free the struct itself
            drop(Box::from_raw(ptr));
        }
    }
}
```
***Note:*** *Implement similar create/free functions for any data passed from Rust to Swift.*

#### **5. C Header Generation**

Create `CoreLib/cbindgen.toml`:

```toml
language = "C"
include_guard = "CORE_LIB_H"
```

Install `cbindgen` (`cargo install cbindgen`) and run it to generate the header file that Swift will use:
`cbindgen --config cbindgen.toml --crate core_lib --output ../GuiApp/Sources/GuiApp/RustBridge/core_lib.h`

#### **6. Testing**

Add unit tests inside `src/processing.rs` (or other modules) to validate the core logic.

```rust
#[cfg(test)]
mod tests {
    #[test]
    fn test_thumbnail_creation() {
        // ... your test logic here ...
    }
}
```
Run tests with `cargo test`.

---

### **Part 3: The Swift GUI Application (`GuiApp`)**

#### **1. Setup**

Navigate into the `GuiApp` directory and run:
`swift package init --type executable`

#### **2. Bridging Configuration**

**a. Module Map:** Create `GuiApp/Sources/GuiApp/RustBridge/module.modulemap`:

```c
module RustBridge {
    header "core_lib.h"
    export *
}
```

**b. SwiftPM Manifest:** Modify `GuiApp/Package.swift` to link against the Rust library.

```swift
// swift-tools-version:5.9
import PackageDescription

let package = Package(
    name: "GuiApp",
    platforms: [.macOS(.v14)], // Specify a recent macOS version
    targets: [
        .executableTarget(
            name: "GuiApp",
            dependencies: ["RustBridge"]
        ),
        .systemLibrary(
            name: "RustBridge",
            pkgConfig: "RustBridge",
            providers: [
                .brew(["core_lib"]) // Placeholder - we are providing it manually
            ]
        )
    ]
)
```
***Note:*** *The `systemLibrary` target is a way to tell SwiftPM about pre-compiled libraries. We will provide the path during the build step.*

#### **3. SwiftUI Application Structure**

**a. App Entry Point (`Sources/GuiApp/Main.swift`):**
Define the main window and application commands (menus).

```swift
import SwiftUI

@main
struct GuiApp: App {
    var body: some Scene {
        WindowGroup {
            ContentView()
        }
        .commands {
            CommandMenu("File") {
                Button("Open...") { /* ... action ... */ }.keyboardShortcut("o")
            }
            CommandMenu("Help") {
                Button("About GuiApp") { /* ... show about sheet ... */ }
            }
        }
    }
}
```

**b. Main View (`Sources/GuiApp/Views/ContentView.swift`):**
This view contains the main layout with resizable panels. The UI pattern for this is `HSplitView`.

```swift
import SwiftUI

struct ContentView: View {
    var body: some View {
        HSplitView {
            GridView()
                .frame(minWidth: 300) // Minimum width for the grid panel
            DetailView()
                .frame(minWidth: 200, maxWidth: 400) // Sizing for the details panel
        }
        .frame(minWidth: 700, minHeight: 500)
    }
}
```

**c. Grid View (`Sources/GuiApp/Views/GridView.swift`):**
Use a `LazyVGrid` inside a `ScrollView` for efficient rendering of thousands of items.

```swift
import SwiftUI

struct GridView: View {
    // Number of columns for the grid
    private let columns = [GridItem(.adaptive(minimum: 150))]
    
    // Placeholder for image file paths
    private let imagePaths = (1...1000).map { "image_\($0)" }

    var body: some View {
        ScrollView {
            LazyVGrid(columns: columns, spacing: 20) {
                ForEach(imagePaths, id: \.self) { path in
                    VStack {
                        Image(systemName: "photo") // Placeholder thumbnail
                            .resizable()
                            .aspectRatio(contentMode: .fit)
                            .frame(height: 120)
                        
                        Text(path)
                            .lineLimit(1)
                            .truncationMode(.middle)
                    }
                }
            }
            .padding()
        }
    }
}
```

**d. Grid Layout Calculation (Pseudo-code as requested):**
This logic should be implemented inside `GridView` to determine cell sizes dynamically.

```python
# This is a conceptual guide. Implement this logic in Swift using GeometryReader.

def calculate_cell_dimensions(panel_width, num_columns, padding):
    total_padding_space = padding * (num_columns + 1)
    available_width_for_cells = panel_width - total_padding_space
    
    thumbnail_width = available_width_for_cells / num_columns
    thumbnail_height = thumbnail_width # For a square aspect ratio
    
    # Example for metadata height
    metadata_lines = 2
    line_height = 16
    metadata_block_height = metadata_lines * line_height
    
    vertical_padding = padding
    
    cell_height = vertical_padding (top) + thumbnail_height + metadata_block_height + vertical_padding (bottom)
    
    return { "width": thumbnail_width, "height": cell_height }
```

**e. Rust Bridge Wrapper (`Sources/GuiApp/RustBridge/RustBridge.swift`):**
Create a safe Swift wrapper around the unsafe C functions from Rust. This class will handle memory management and type conversions.

```swift
import Foundation
import RustBridge // The name from your module.modulemap

class RustAPI {
    static func getMetadata(for path: String) -> FileMetadata? {
        let cPath = path.cString(using: .utf8)
        
        guard let metadataPtr = get_file_metadata(cPath) else {
            return nil
        }
        
        // Convert the C struct to a Swift-friendly type
        // ... handle CString conversions ...
        
        // IMPORTANT: Free the memory allocated by Rust
        free_file_metadata(metadataPtr)
        
        // Return the Swift object
        return nil // Placeholder
    }
}
```

---

### **Part 4: Build System & VSCode Integration**

#### **1. Master Build Script (`build.sh`)**

This script orchestrates the entire build process.

```bash
#!/bin/bash
set -e # Exit on error

echo "Building Rust Core Library..."
(cd CoreLib && cargo build)

echo "Generating C Header File..."
(cd CoreLib && cargo run -p cbindgen -- --config cbindgen.toml --crate core_lib --output ../GuiApp/Sources/GuiApp/RustBridge/core_lib.h)

echo "Building Swift GUI Application..."
# Pass linker flags to tell SwiftPM where to find the Rust static library
swift build \
    -Xlinker "-L$(pwd)/CoreLib/target/debug" \
    -Xlinker "-lcore_lib"

echo "Build complete. Executable is at .build/debug/GuiApp"
```
*Make the script executable: `chmod +x build.sh`*

#### **2. VSCode Tasks (`.vscode/tasks.json`)**

This allows you to run the build script directly from VSCode (Cmd+Shift+B).

```json
{
    "version": "2.0.0",
    "tasks": [
        {
            "label": "Build Project",
            "type": "shell",
            "command": "./build.sh",
            "group": {
                "kind": "build",
                "isDefault": true
            },
            "problemMatcher": []
        }
    ]
}
```

#### **3. VSCode Launch Configuration (`.vscode/launch.json`)**

This configures the debugger to launch your app (F5).

```json
{
    "version": "0.2.0",
    "configurations": [
        {
            "type": "lldb",
            "request": "launch",
            "name": "Debug GuiApp",
            "program": "${workspaceFolder}/.build/debug/GuiApp",
            "args": ["/Users/yourname/path/to/photos"], // Pass initial folder here
            "cwd": "${workspaceFolder}",
            "preLaunchTask": "Build Project" // Runs the build task before launching
        }
    ]
}
```

This comprehensive plan provides all the necessary instructions to build the application as specified.