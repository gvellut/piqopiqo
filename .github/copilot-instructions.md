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
    -   XCode will not be used for development: only command-line or VS Code.

5.  **Key Dependencies:**
    -   **Rust:** `image`, `rayon` (for parallelism), `serde` and `toml` (for configuration), `walkdir`.
    -   **Swift:** `SwiftUI`. Target macOS v14 or later.

6.  **Error Handling:**
    -   Rust functions exposed via FFI should return nullable pointers or status codes to indicate failure.
    -   The Swift FFI bridge layer is responsible for checking for these null pointers and translating them into Swift errors or optional types.

7.  **Coding Style:**
    -   Follow standard `rustfmt` for Rust and `swift-format` for Swift.
    -   Write clear comments, especially for `unsafe` blocks in Rust and Swift that deal with the FFI boundary.

8. **Ignore and don't**
    -   Completely disregard the py_test folder, prompts folder and the NOTES.md file
    -   don't use node or npx ever

9. **Versions**
    -   Use Rust 2024 (do not change to Rust 2021)
    -   Use Swift 6.2
