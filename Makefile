# Load configuration from file
CONFIG_FILE = app_config.env
include $(CONFIG_FILE)

APP_BUILD = .appBuild

# Build configuration (debug or release)
BUILD_MODE ?= release
ifeq ($(BUILD_MODE),debug)
    RUST_TARGET_DIR = debug
	RUST_BUILD_FLAG =
    APP_DIR = $(APP_BUILD)/debug
    APP_BUNDLE = $(APP_DIR)/$(APP_NAME).app
else
    RUST_TARGET_DIR = release
	RUST_BUILD_FLAG = --release
    APP_DIR = $(APP_BUILD)/release
    APP_BUNDLE = $(APP_DIR)/$(APP_NAME).app
endif

# Paths
CORE_LIB_DIR = CoreLib

# Rust build artifacts
RUST_EXE = $(CORE_LIB_DIR)/target/$(RUST_TARGET_DIR)/core_lib

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
.PHONY: all build build-default clean debug app app-debug release app certificate run

# --- Targets ---

# Default target
all: build

# Build the entire application in release mode (if BUILD_MODE not defined)
app: $(APP_BUNDLE)

app-debug:
	@$(MAKE) BUILD_MODE=debug app

build:
	@$(MAKE) BUILD_MODE=debug build-default

build-default: $(RUST_EXE)

run:
	@$(MAKE) BUILD_MODE=debug run-default

run-default: build-default
	@echo "--- Running Application ---"
	@$(RUST_EXE)

# Create the .app bundle
$(APP_BUNDLE): $(RUST_EXE) $(TEMP_PLIST) $(ICNS_ICON)
	@echo "--- Creating application bundle: $(APP_BUNDLE) ---"
	@rm -rf $(APP_BUNDLE)
	@mkdir -p $(BUNDLE_MACOS_DIR)
	@mkdir -p $(BUNDLE_RESOURCES_DIR)
	@cp $(RUST_EXE) $(BUNDLE_EXE)
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

$(RUST_EXE): $(shell find $(CORE_LIB_DIR)/src -name '*.rs')
	@echo "--- Building CoreLib (Rust) in $(BUILD_MODE) mode ---"
	(cd $(CORE_LIB_DIR) && cargo build $(RUST_BUILD_FLAG))

# Clean up all build artifacts
clean:
	@echo "--- Cleaning up build artifacts ---"
	(cd $(CORE_LIB_DIR) && cargo clean)
	@rm -rf $(APP_BUILD)
	@echo "--- Cleanup complete ---"
