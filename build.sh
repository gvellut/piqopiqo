#!/bin/bash

# Exit immediately if a command exits with a non-zero status.
set -e

echo "--- Building CoreLib (Rust) ---"
# Build for release for performance
(cd CoreLib && cargo build --release)

echo "--- Building GuiApp (Swift) ---"
# Build for release and specify the build path
(cd GuiApp && swift build -c release)

# --- Create .app bundle ---
APP_NAME="Piqopiqo.app"
BUILD_DIR="GuiApp/.build/release"
SWIFT_EXE_NAME="GuiApp"
FINAL_EXE_NAME="Piqopiqo" # Conventionally, the executable matches the app name

# The final location of the app bundle will be in the root of the project
APP_PATH="./release/$APP_NAME"
TARGET_EXE_PATH="$APP_PATH/Contents/MacOS/$FINAL_EXE_NAME"

echo "--- Creating .app bundle structure for $APP_NAME ---"

# Clean up previous bundle if it exists
rm -rf "$APP_PATH"

# Create the required directory structure
mkdir -p "$APP_PATH/Contents/MacOS"
mkdir -p "$APP_PATH/Contents/Resources"

# Copy the compiled Swift executable and rename it
echo "Copying executable to $TARGET_EXE_PATH"
cp "$BUILD_DIR/$SWIFT_EXE_NAME" "$TARGET_EXE_PATH"

# Create a basic Info.plist
echo "Creating Info.plist"
PLIST_PATH="$APP_PATH/Contents/Info.plist"
cat > "$PLIST_PATH" <<EOL
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>CFBundleExecutable</key>
    <string>${FINAL_EXE_NAME}</string>
    <key>CFBundleIdentifier</key>
    <string>com.yourcompany.piqopiqo</string>
    <key>CFBundleName</key>
    <string>Piqopiqo</string>
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
    <string></string>
</dict>
</plist>
EOL

echo "--- Build complete. Application bundle created at: $APP_PATH ---"
