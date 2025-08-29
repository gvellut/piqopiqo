# Makefile for Piqopiqo

# --- Variables ---
APP_NAME = Piqopiqo
FINAL_EXE_NAME = Piqopiqo
RELEASE_DIR = release
APP_BUNDLE = $(RELEASE_DIR)/$(APP_NAME).app

# Build configuration (debug or release)
BUILD_MODE ?= release
ifeq ($(BUILD_MODE),debug)
    RUST_TARGET_DIR = debug
    SWIFT_BUILD_FLAGS = 
    SWIFT_BUILD_DIR = $(GUI_APP_DIR)/.build/debug
else
    RUST_TARGET_DIR = release
    SWIFT_BUILD_FLAGS = -c release
    SWIFT_BUILD_DIR = $(GUI_APP_DIR)/.build/release
endif

# Paths
GUI_APP_DIR = GuiApp
CORE_LIB_DIR = CoreLib

# Swift build artifacts
SWIFT_EXE = $(SWIFT_BUILD_DIR)/GuiApp

# Rust build artifacts
RUST_LIB = $(CORE_LIB_DIR)/target/$(RUST_TARGET_DIR)/libcore_lib.a

# FFI artifacts
# written directly by build.rs to dst_c_HEADER
# Destination path for the header required by the Swift project
DST_C_HEADER = $(GUI_APP_DIR)/Sources/CBindings/core_lib.h

# Bundle paths
BUNDLE_MACOS_DIR = $(APP_BUNDLE)/Contents/MacOS
BUNDLE_RESOURCES_DIR = $(APP_BUNDLE)/Contents/Resources
BUNDLE_EXE = $(BUNDLE_MACOS_DIR)/$(FINAL_EXE_NAME)
BUNDLE_PLIST = $(APP_BUNDLE)/Contents/Info.plist

# Phony targets are not files
.PHONY: all build build-default lib lib-default clean debug release app

# --- Targets ---

# Default target
all: build

# Build the entire application in release mode (if BUILD+MODE not defined)
app: $(APP_BUNDLE)

# Build rust library only
lib:
	@$(MAKE) BUILD_MODE=debug lib-default

lib-default: $(RUST_LIB)

build:
	@$(MAKE) BUILD_MODE=debug build-default

build-default: $(SWIFT_EXE)


# Create the .app bundle
$(APP_BUNDLE): $(SWIFT_EXE)
	@echo "--- Creating application bundle: $(APP_BUNDLE) ---"
	@rm -rf $(APP_BUNDLE)
	@mkdir -p $(BUNDLE_MACOS_DIR)
	@mkdir -p $(BUNDLE_RESOURCES_DIR)
	@cp $(SWIFT_EXE) $(BUNDLE_EXE)
	@echo '<?xml version="1.0" encoding="UTF-8"?>' > $(BUNDLE_PLIST)
	@echo '<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">' >> $(BUNDLE_PLIST)
	@echo '<plist version="1.0">' >> $(BUNDLE_PLIST)
	@echo '<dict>' >> $(BUNDLE_PLIST)
	@echo '    <key>CFBundleExecutable</key>' >> $(BUNDLE_PLIST)
	@echo '    <string>$(FINAL_EXE_NAME)</string>' >> $(BUNDLE_PLIST)
	@echo '    <key>CFBundleIdentifier</key>' >> $(BUNDLE_PLIST)
	@echo '    <string>com.yourcompany.piqopiqo</string>' >> $(BUNDLE_PLIST)
	@echo '    <key>CFBundleName</key>' >> $(BUNDLE_PLIST)
	@echo '    <string>$(APP_NAME)</string>' >> $(BUNDLE_PLIST)
	@echo '    <key>CFBundlePackageType</key>' >> $(BUNDLE_PLIST)
	@echo '    <string>APPL</string>' >> $(BUNDLE_PLIST)
	@echo '    <key>CFBundleShortVersionString</key>' >> $(BUNDLE_PLIST)
	@echo '    <string>1.0</string>' >> $(BUNDLE_PLIST)
	@echo '    <key>CFBundleVersion</key>' >> $(BUNDLE_PLIST)
	@echo '    <string>1</string>' >> $(BUNDLE_PLIST)
	@echo '    <key>LSMinimumSystemVersion</key>' >> $(BUNDLE_PLIST)
	@echo '    <string>14.0</string>' >> $(BUNDLE_PLIST)
	@echo '    <key>NSPrincipalClass</key>' >> $(BUNDLE_PLIST)
	@echo '    <string>NSApplication</string>' >> $(BUNDLE_PLIST)
	@echo '    <key>NSMainNibFile</key>' >> $(BUNDLE_PLIST)
	@echo '    <string></string>' >> $(BUNDLE_PLIST)
	@echo '</dict>' >> $(BUNDLE_PLIST)
	@echo '</plist>' >> $(BUNDLE_PLIST)
	@echo "--- Build complete. Application bundle created at: ./$(APP_BUNDLE) ---"

# Build the Swift executable, which depends on the C header being in the correct location.
$(SWIFT_EXE): $(RUST_LIB)
	@echo "--- Building GuiApp (Swift) in $(BUILD_MODE) mode ---"
	(cd $(GUI_APP_DIR) && swift build $(SWIFT_BUILD_FLAGS))

# Build the Rust static library. The build.rs script handles C header generation.
$(RUST_LIB):
	@echo "--- Building CoreLib (Rust) in $(BUILD_MODE) mode ---"
ifeq ($(BUILD_MODE),debug)
	(cd $(CORE_LIB_DIR) && cargo build)
else
	(cd $(CORE_LIB_DIR) && cargo build --release)
endif

# Clean up all build artifacts
clean:
	@echo "--- Cleaning up build artifacts ---"
	(cd $(CORE_LIB_DIR) && cargo clean)
	(cd $(GUI_APP_DIR) && swift package clean)
	@rm -rf $(APP_BUNDLE)
	@rm -f $(DST_C_HEADER)
	@echo "--- Cleanup complete ---"
