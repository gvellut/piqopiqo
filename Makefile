# Load configuration from file
CONFIG_FILE = app_config.env
include $(CONFIG_FILE)

APP_BUILD = .appBuild

# Build configuration (debug or release)
BUILD_MODE ?= release
ifeq ($(BUILD_MODE),debug)
    RUST_TARGET_DIR = debug
	RUST_BUILD_FLAG = 
    SWIFT_BUILD_FLAGS = 
    SWIFT_BUILD_DIR = $(GUI_APP_DIR)/.build/debug
    APP_DIR = $(APP_BUILD)/debug
    APP_BUNDLE = $(APP_DIR)/$(APP_NAME).app
else
    RUST_TARGET_DIR = release
	RUST_BUILD_FLAG = --release
    SWIFT_BUILD_FLAGS = -c release
    SWIFT_BUILD_DIR = $(GUI_APP_DIR)/.build/release
    APP_DIR = $(APP_BUILD)/release
    APP_BUNDLE = $(APP_DIR)/$(APP_NAME).app
endif

# Paths
GUI_APP_DIR = GuiApp
CORE_LIB_DIR = CoreLib

# Swift build artifacts
SWIFT_EXE = $(SWIFT_BUILD_DIR)/GuiApp

# Rust build artifacts
RUST_LIB = $(CORE_LIB_DIR)/target/$(RUST_TARGET_DIR)/libcore_lib.dylib

UNIFFI_BINDING = $(GUI_APP_DIR)/Sources/UniffiBindings/*

# Bundle paths
BUNDLE_MACOS_DIR = $(APP_BUNDLE)/Contents/MacOS
BUNDLE_RESOURCES_DIR = $(APP_BUNDLE)/Contents/Resources
BUNDLE_EXE = $(BUNDLE_MACOS_DIR)/$(FINAL_EXE_NAME)
BUNDLE_PLIST = $(APP_BUNDLE)/Contents/Info.plist
BUNDLE_PLIST_TEMPLATE = Info.plist.template
TEMP_PLIST = $(APP_DIR)/Info.plist.tmp

SVG_ICON=AppIcon.svg
ICNS_ICON=$(APP_BUILD)/icons/AppIcon.icns

# Phony targets are not files
.PHONY: all build build-default lib lib-default clean debug app app-debug release app certificate

# --- Targets ---

# Default target
all: build

# Build the entire application in release mode (if BUILD_MODE not defined)
app: $(APP_BUNDLE)

app-debug:
	@$(MAKE) BUILD_MODE=debug app

# Build rust library only
lib:
	@$(MAKE) BUILD_MODE=debug lib-default

lib-default: $(RUST_LIB)

build:
	@$(MAKE) BUILD_MODE=debug build-default

build-default: $(SWIFT_EXE)


# Create the .app bundle
$(APP_BUNDLE): $(SWIFT_EXE) $(TEMP_PLIST) $(ICNS_ICON)
	@echo "--- Creating application bundle: $(APP_BUNDLE) ---"
	@rm -rf $(APP_BUNDLE)
	@mkdir -p $(BUNDLE_MACOS_DIR)
	@mkdir -p $(BUNDLE_RESOURCES_DIR)
	@cp $(SWIFT_EXE) $(BUNDLE_EXE)
	@cp $(ICNS_ICON) $(BUNDLE_RESOURCES_DIR)/
	@cp $(TEMP_PLIST) $(BUNDLE_PLIST)
	@echo "--- Signing application bundle (ad-hoc) ---"
	@codesign --force --deep --sign "My Swift Dev Cert" $(APP_BUNDLE)
	@echo "--- Build complete. Application bundle created at: ./$(APP_BUNDLE) ---"

$(TEMP_PLIST): $(BUNDLE_PLIST_TEMPLATE) $(CONFIG_FILE)
	@mkdir -p $(APP_DIR)
	@sed -e 's/__APP_NAME__/$(APP_NAME)/g' \
	     -e 's/__FINAL_EXE_NAME__/$(FINAL_EXE_NAME)/g' \
	     -e 's/__BUNDLE_ID__/$(BUNDLE_ID)/g' \
	     -e 's/__APP_VERSION__/$(APP_VERSION)/g' \
	     $(BUNDLE_PLIST_TEMPLATE) > $(TEMP_PLIST)

$(ICNS_ICON): $(SVG_ICON)
	@mkdir -p $(APP_DIR)
	@./svg2icns.sh $(SVG_ICON)

# Build the Swift executable, which depends on the C header being in the correct location.
$(SWIFT_EXE): $(UNIFFI_BINDING) $(shell find $(GUI_APP_DIR)/Sources -name '*.swift')
	@echo "--- Building GuiApp (Swift) in $(BUILD_MODE) mode ---"
	(cd $(GUI_APP_DIR) && swift build $(SWIFT_BUILD_FLAGS))

$(UNIFFI_BINDING): $(RUST_LIB)
	(cd $(CORE_LIB_DIR) && cargo run -p uniffi-bindgen -- target/$(BUILD_MODE)/libcore_lib.dylib ../GuiApp/Sources/UniffiBindings --swift-sources --headers --modulemap --modulemap-filename module.modulemap  --module-name core_libFFI)

$(RUST_LIB): $(shell find $(CORE_LIB_DIR)/src -name '*.rs')
	@echo "--- Building CoreLib (Rust) in $(BUILD_MODE) mode ---"
	(cd $(CORE_LIB_DIR) && cargo build $(RUST_BUILD_FLAG))

# Clean up all build artifacts
clean:
	@echo "--- Cleaning up build artifacts ---"
	(cd $(CORE_LIB_DIR) && cargo clean)
	(cd $(GUI_APP_DIR) && swift package clean)
	@rm -rf $(APP_BUILD)
	@rm -f $(UNIFFI_BINDING)
	@echo "--- Cleanup complete ---"
