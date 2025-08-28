#!/bin/bash

# Exit immediately if a command exits with a non-zero status.
set -e

# Get the directory of the script to run this from anywhere
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" &> /dev/null && pwd )"

# --- Configuration ---
RUST_LIB_NAME="core_lib"
RUST_CRATE_DIR="$SCRIPT_DIR/CoreLib"
SWIFT_APP_DIR="$SCRIPT_DIR/GuiApp"
APP_NAME="GuiApp"

# Build paths for release configuration
RUST_BUILD_DIR="$RUST_CRATE_DIR/target/release"
SWIFT_BUILD_DIR="$SWIFT_APP_DIR/.build/release"

# Final .app bundle path
APP_BUNDLE_PATH="$SWIFT_BUILD_DIR/$APP_NAME.app"

echo "--- Cleaning previous builds ---"
rm -rf "$SWIFT_BUILD_DIR"
rm -rf "$RUST_BUILD_DIR"

echo "--- Building Rust Library (Release): $RUST_LIB_NAME ---"
(cd "$RUST_CRATE_DIR" && cargo build --release)

echo "--- Building Swift App (Release): $APP_NAME ---"
# The linker settings in Package.swift should handle linking now
(cd "$SWIFT_APP_DIR" && swift build -c release)

echo "--- Assembling .app Bundle ---"

# Create the directory structure
mkdir -p "$APP_BUNDLE_PATH/Contents/MacOS"
mkdir -p "$APP_BUNDLE_PATH/Contents/Resources"

# Copy the executable
cp "$SWIFT_BUILD_DIR/$APP_NAME" "$APP_BUNDLE_PATH/Contents/MacOS/$APP_NAME"

# Create a minimal Info.plist
cat > "$APP_BUNDLE_PATH/Contents/Info.plist" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>CFBundleExecutable</key>
    <string>$APP_NAME</string>
    <key>CFBundleIdentifier</key>
    <string>com.yourcompany.$APP_NAME</string>
    <key>CFBundleName</key>
    <string>$APP_NAME</string>
    <key>CFBundlePackageType</key>
    <string>APPL</string>
    <key>CFBundleShortVersionString</key>
    <string>1.0</string>
    <key>CFBundleVersion</key>
    <string>1</string>
    <key>LSMinimumSystemVersion</key>
    <string>14.0</string>
    <key>NSPrincipalClass</key>
    <string>NSApplication</string>
    <key>NSMainNibFile</key>
    <string>MainMenu</string>
</dict>
</plist>
EOF

# The static library is already linked by SwiftPM, so we don't need to copy it manually
# or use install_name_tool. The linker settings in Package.swift handle this.

echo "--- Build Complete ---"
echo "App bundle available at: $APP_BUNDLE_PATH"
echo "To run, execute:"
echo "open \"$APP_BUNDLE_PATH\""
