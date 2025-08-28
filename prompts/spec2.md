Excellent. This is the ideal way to build a complex application with an agent. By breaking the problem down into verifiable, sequential steps, you ensure the project stays on track.

First, here is the `copilot-instructions.md` file to be placed in the `.github` directory of your repository. This will provide the agent with the high-level architectural and stylistic guidance it needs for all subsequent tasks.

---

### **`/.github/copilot-instructions.md`**

```markdown
## About This Repository

This repository contains the source code for "Piqopiqo", a native macOS photo browser. The goal is to create a high-performance application with a clean, responsive user interface.

## Core Architecture Principles

1.  **Strict UI/Logic Separation:** The application is composed of two main parts:
    -   **`GuiApp` (Swift/SwiftUI):** This is responsible ONLY for the user interface, user interactions, and view state management. It should contain no file system access or image processing logic.
    -   **`CoreLib` (Rust):** This is the backend engine. It handles all file operations, thumbnail generation, metadata parsing, and configuration management. It is a completely self-contained library with no knowledge of the UI.

2.  **Swift-Rust Interoperability:**
    -   Communication between Swift and Rust is handled exclusively through a C Foreign Function Interface (FFI).
    -   The public API of the `CoreLib` Rust library must be exposed as `#[no_mangle] extern "C"` functions.
    -   `cbindgen` will be used to automatically generate the C header file (`core_lib.h`) from the Rust source.
    -   **Memory Management is Critical:** Any memory allocated by Rust and passed to Swift (e.g., strings, structs) MUST have a corresponding Rust `free_...` function. The Swift wrapper (`RustBridge.swift`) is responsible for calling this `free` function to prevent memory leaks. Do not use Swift's memory management for pointers coming from Rust.

3.  **User Interface:**
    -   The UI must be built using SwiftUI. Do not use AppKit or Storyboards.
    -   Define all UI programmatically in `.swift` files.
    -   Prioritize performance for the image grid. Use `LazyVGrid` to ensure only visible cells are rendered.

4.  **Build System:**
    -   The entire project must be buildable from the command line.
    -   Use Swift Package Manager (SwiftPM) for the Swift application and Cargo for the Rust library.
    -   A master `build.sh` script will be used to coordinate the build process (compiling Rust, generating the C header, and compiling Swift). Do not rely on Xcode's build system (`.xcodeproj`).

5.  **Key Dependencies:**
    -   **Rust:** `image`, `rayon` (for parallelism), `serde` and `toml` (for configuration), `walkdir`.
    -   **Swift:** `SwiftUI`. Target macOS v14 or later.

6.  **Error Handling:**
    -   Rust functions exposed via FFI should return nullable pointers or status codes to indicate failure.
    -   The Swift FFI bridge layer is responsible for checking for these null pointers and translating them into Swift errors or optional types.

7.  **Coding Style:**
    -   Follow standard `rustfmt` for Rust and `swift-format` for Swift.
    -   Write clear comments, especially for `unsafe` blocks in Rust and Swift that deal with the FFI boundary.
```

---

### **Suite of Prompts for the Agent**

Here are the step-by-step prompts. Give these to your agent one at a time.

---

### **Prompt 1: Project Scaffolding and Initialization**

**Instructions:**
1.  Inside this directory (`piqopiqo` folder), create the directory structure as specified below.
2.  Initialize a Swift executable package named `GuiApp` inside the `GuiApp` folder.
3.  Initialize a Rust library package named `core_lib` inside the `CoreLib` folder.

```
piqopiqo-browser/
├── GuiApp/
└── CoreLib/
```

**Success Condition:**
The directories `GuiApp` and `CoreLib` exist. `GuiApp` contains a `Package.swift` file. `CoreLib` contains a `Cargo.toml` file.

---

### **Prompt 2: Minimal Rust Library and C-Bridge**

**Instructions:**
1.  In `CoreLib/Cargo.toml`, add the `[lib]` section to define the `crate-type` as `staticlib`.
2.  In `CoreLib/src/lib.rs`, replace the existing code with a single function named `hello_from_rust` that returns a C-style string (`*const c_char`). This function should return the static string "Hello from Rust!". Remember to use `#[no_mangle] extern "C"`.
3.  Add the `cbindgen` crate as a build dependency to `CoreLib/Cargo.toml`.
4.  Create a `CoreLib/cbindgen.toml` file to configure C header generation.
5.  Generate the C header file `core_lib.h`.

**Success Condition:**
1.  Running `cargo build` inside the `CoreLib` directory successfully creates a `libcore_lib.a` file in `CoreLib/target/debug/`.
2.  You can manually generate a `core_lib.h` file that contains the C function signature for `hello_from_rust`.

---

### **Prompt 3: Minimal SwiftUI App and Bridge Setup**

**Instructions:**
1.  Create the directory `GuiApp/Sources/GuiApp/RustBridge`.
2.  Create a `module.modulemap` file inside that directory to define the `RustBridge` module.
3.  Modify `GuiApp/Package.swift` to add a `.systemLibrary` target named `RustBridge`.
4.  Modify the `GuiApp` executable target in `Package.swift` to depend on `RustBridge`.
5.  In `GuiApp/Sources/GuiApp/Main.swift`, create a minimal SwiftUI `ContentView` that displays the static text "Hello from Swift".

**Success Condition:**
The Swift project now has the necessary structure to find the C header and link against the library. A `swift build` command run from the `GuiApp` directory should compile but will fail at the *linking* stage with an error like "ld: library not found for -lcore_lib", which is expected for now.

---

### **Prompt 4: End-to-End Build and First Interop Call**

**Instructions:**
1.  In the project root, create an executable shell script `build.sh`.
2.  The script must perform these steps in order:
    a. Build the Rust library using `cargo build`.
    b. Generate the C header using `cbindgen` and place it in `GuiApp/Sources/GuiApp/RustBridge/core_lib.h`.
    c. Build the Swift app using `swift build`, passing the necessary `-Xlinker` flags to link against the `libcore_lib.a` file.
3.  Create `GuiApp/Sources/GuiApp/RustBridge/RustBridge.swift` to wrap the unsafe C function call. It should call `hello_from_rust` and convert the result into a Swift `String`.
4.  Modify `GuiApp/Sources/GuiApp/Main.swift` to call this wrapper and display the string returned from Rust instead of the static text.

**Success Condition:**
1.  Running `./build.sh` from the root directory completes without errors.
2.  Running the compiled executable at `.build/debug/GuiApp` opens a window that displays the text "Hello from Rust!".

---

### **Prompt 5: VSCode Build & Debug Configuration**

**Instructions:**
1.  Create the `.vscode` directory in the project root.
2.  Create a `tasks.json` file that defines a "Build Piqopiqo" task which executes the `./build.sh` script. Make this the default build task.
3.  Create a `launch.json` file that defines a "Debug Piqopiqo" configuration. This configuration should run the build task before launching the compiled executable (`${workspaceFolder}/.build/debug/GuiApp`) with the debugger.

**Success Condition:**
1.  Pressing `Cmd+Shift+B` in VSCode successfully runs the `build.sh` script.
2.  Pressing `F5` starts a debugging session, launching the application window.

---

### **Prompt 6: Implement Basic SwiftUI Layout**

**Instructions:**
1.  In `GuiApp/Sources/GuiApp/Views/ContentView.swift`, replace the current `Text` view.
2.  Implement a two-panel layout using `HSplitView`.
3.  The left panel should be a placeholder for the grid view. Give it a `minWidth` of 300. For now, it can just contain `Text("Grid Panel")`.
4.  The right panel will be for details. Give it a `minWidth` of 200 and a `maxWidth` of 400. It can contain `Text("Detail Panel")`.

**Success Condition:**
The application launches showing a window with two horizontally arranged panels separated by a draggable divider.

---

### **Prompt 7: Application Menu and About Box**

**Instructions:**
1.  Modify `GuiApp/Sources/GuiApp/Main.swift` to use `@main struct PiqopiqoApp: App`.
2.  Use the `.commands` modifier to customize the application menu.
3.  Add a "Quit Piqopiqo" command to the "File" menu with the keyboard shortcut `Cmd+Q`.
4.  Replace the default "About" menu item with one named "About Piqopiqo".
5.  Create a new SwiftUI file `GuiApp/Sources/GuiApp/Views/AboutView.swift`. This view should display the application name and a version number.
6.  Wire up the "About Piqopiqo" menu button to present the `AboutView` as a sheet (pop-up panel).

**Success Condition:**
1.  The application menu bar shows "Piqopiqo" instead of "GuiApp".
2.  The "File" menu contains a working "Quit Piqopiqo" item.
3.  Selecting "About Piqopiqo" from the application menu opens a pop-up panel displaying the about information.