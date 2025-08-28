#!/bin/bash

# Exit immediately if a command exits with a non-zero status.
set -e

# Get the directory of the script to run this from anywhere
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" &> /dev/null && pwd )"

# --- Configuration ---
RUST_LIB_NAME="core_lib"
RUST_CRATE_DIR="$SCRIPT_DIR/CoreLib"
SWIFT_APP_DIR="$SCRIPT_DIR/GuiApp"
BRIDGE_DIR="$SWIFT_APP_DIR/Sources/GuiApp/RustBridge"
BUILT_RUST_LIB_DIR="$RUST_CRATE_DIR/target/debug"

echo "--- Building Rust Library: $RUST_LIB_NAME ---"
# Build the Rust static library
(cd "$RUST_CRATE_DIR" && cargo build)

echo "--- Copying C Header ---"
# The build.rs script in CoreLib now handles generation automatically.
# We just need to copy the generated header to the bridge directory.
cp "$RUST_CRATE_DIR/core_lib.h" "$BRIDGE_DIR/core_lib.h"
echo "Header copied to $BRIDGE_DIR/core_lib.h"

echo "--- Building Swift App: $SWIFT_APP_DIR ---"
# Build the Swift app, telling the linker where to find our Rust library.
# The path to the library must be relative to the Swift App's root directory.
(cd "$SWIFT_APP_DIR" && swift build -Xlinker -L"../CoreLib/target/debug" -Xlinker -l"$RUST_LIB_NAME")

echo "--- Build Complete ---"
echo "Executable available at $SWIFT_APP_DIR/.build/debug/GuiApp"
echo "To run, execute: $SWIFT_APP_DIR/.build/debug/GuiApp"
