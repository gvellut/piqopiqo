Of course. Moving from a SwiftUI declarative approach to the imperative, delegate-based approach of AppKit requires a different breakdown. Here is the revised list of work items, tailored specifically for a macOS AppKit implementation.

### Project Overview

**Goal:** Build the core functionality for a macOS media browser application.
**Architecture:** An AppKit Swift GUI for macOS that communicates with a Rust library (`CoreLib`) for all state management and data processing. Communication is handled by `uniffi-rs`.
**Initial State:** A project is already set up with an AppKit app, a Rust library, and a working `uniffi-rs` bridge connecting them.

---

### Work Item 1: Define Core Data Structures and State in Rust

**Description:**
Establish the fundamental data structures and the main state container in the Rust Core library. This involves creating the `Item` and `Config` structs, and a central `Core` struct to manage the application's state. This state will be held in memory.

**Tasks:**
1.  **In `lib.rs` (or a new `models.rs` module):**
    *   Define a public struct `Item` with two public fields: `id` (u32) and `text` (String). Use `#[derive(uniffi::Record)]` to expose it.
    *   Define a public struct `Config` with one public field: `num_columns` (u32). Use `#[derive(uniffi::Record)]`.
2.  **In `lib.rs`:**
    *   Define a main struct `Core`.
    *   It should contain two fields: `items` (a `Vec<Item>`) and `config` (a `Config`).
    *   Implement a `new()` function for `Core`.
    *   Inside `new()`, initialize the `config` with `num_columns` set to 5.
    *   Inside `new()`, populate the `items` vector with 100 `Item` instances. The `id` should range from 1 to 100, and the `text` should be formatted as `"Item #N"`, where N is the `id`.
    *   Use `std::sync::Arc` to wrap the `Core` struct to make it thread-safe for `uniffi`. Create a `new_core()` constructor function that returns an `Arc<Core>`. Expose this constructor using `#[uniffi::constructor]`.

**Success Criteria:**
1.  **Unit Tests in Rust:**
    *   Create a test `test_core_initialization()` that calls `Core::new()`.
    *   Assert that `core.config.num_columns` is equal to 5.
    *   Assert that `core.items.len()` is equal to 100.
    *   Assert that `core.items[0].id` is 1 and `core.items[0].text` is "Item #1".
    *   Assert that `core.items[99].id` is 100 and `core.items[99].text` is "Item #100".
2.  **Code Compiles:** The Rust project must compile successfully after these changes.

---

### Work Item 2: Expose State Accessors via UniFFI

**Description:**
Create functions to allow the Swift GUI to read the application state from the Rust `Core` instance. These functions will provide the total number of items, the current configuration, and a subset of items by index.

**Tasks:**
1.  **In `lib.rs`:**
    *   Implement a method on `Arc<Core>` named `get_total_item_count()` that returns a `u32`.
    *   Implement a method `get_config()` that returns the `Config` struct.
    *   Implement a method `get_items(start: u32, count: u32)` which returns a `Vec<Item>`. This function should return a slice of the `items` vector. Include robust handling for out-of-bounds requests (return a smaller or empty vector).
2.  **Update `corelib.udl`:**
    *   Add definitions for the `Item` and `Config` records.
    *   Add the method signatures for `get_total_item_count`, `get_config`, and `get_items` to the `Core` object interface.
3.  **Generate Bindings:** Run the `uniffi-bindgen` command to generate the Swift bridging code.

**Success Criteria:**
1.  **Unit Tests in Rust:**
    *   Create a test `test_get_items()` that creates a `Core` instance.
    *   Call `core.get_items(0, 10)` and assert the returned vector has a length of 10.
    *   Call `core.get_items(95, 10)` and assert the returned vector has a length of 5.
2.  **Builds Successfully:** The Rust and Swift projects must both compile successfully.

---

### Work Item 3: Initial AppKit ViewController and Layout Calculation

**Description:**
Set up the main `NSViewController` for the grid. In this controller, fetch the initial state from Rust and implement the layout calculation logic. The logic will be triggered when the view loads and whenever its size changes. The calculated values will be stored as properties on the controller.

**Tasks:**
1.  **In the Swift Project:**
    *   Ensure you have a `MainViewController.swift` file controlling your main view.
    *   Add properties to `MainViewController` to store the state:
        ```swift
        private var core: Core!
        private var panelWidth: CGFloat = 0
        private var panelHeight: CGFloat = 0
        private var numColumns: UInt32 = 0
        private var itemWidth: CGFloat = 0
        private var itemHeight: CGFloat = 0
        private var visibleRows: Int = 0
        ```
2.  **In `viewDidLoad()`:**
    *   Initialize the Rust core object: `core = newCore()`.
    *   Fetch the initial configuration: `numColumns = core.getConfig().numColumns`.
3.  **In `viewDidLayout()`:**
    *   This method is called automatically when the view's frame changes.
    *   Update `panelWidth` and `panelHeight` from `self.view.bounds.width` and `self.view.bounds.height`.
    *   Call a new function `calculateGridLayout()`.
4.  **Create `calculateGridLayout()` function:**
    *   Implement the layout math from the algorithm inside this function, updating the controller's properties (`itemWidth`, `itemHeight`, `visibleRows`).
    *   Log the calculated values (`itemWidth`, `itemHeight`, `visibleRows`) to the console for verification.

**Success Criteria:**
1.  **App Runs:** The Swift application compiles and runs without crashing.
2.  **Console Output:** When the app starts, the console must show the correctly calculated layout values. When the window is resized, a stream of new calculated values should appear in the console.

---

### Work Item 4: Implement NSCollectionView for Static Grid Display

**Description:**
Use an `NSCollectionView` to display the initial, non-scrollable grid of items. This involves setting up the collection view, its data source, and a custom `NSCollectionViewItem` to represent each cell.

**Tasks:**
1.  **Interface Builder (XIB/Storyboard):**
    *   Drag an `NSCollectionView` onto your `MainViewController`'s view. Add constraints to pin it to the edges of its superview.
    *   Connect the `dataSource` of the collection view to the `MainViewController`.
    *   Create a new XIB file for the collection view item, named `GridItem.xib`. Design the item's view with an `NSBox` for the gray background, an `NSTextField` for the number, and another `NSTextField` for the text.
2.  **Create `GridItem.swift`:**
    *   This class will be a subclass of `NSCollectionViewItem`.
    *   Create `@IBOutlets` connecting to the box and text fields from the XIB.
    *   Add a method `configure(with item: Item)` to set the content of the outlets. Set the number field's font to be larger and the text field to truncate with an ellipsis.
3.  **In `MainViewController.swift`:**
    *   Create an `@IBOutlet` for the `NSCollectionView`.
    *   Add a property `private var displayedItems: [Item] = []`.
    *   In `viewDidLoad()`:
        *   Configure the collection view's layout: `let layout = NSCollectionViewGridLayout(); collectionView.collectionViewLayout = layout`.
        *   Register the `GridItem` XIB: `collectionView.register(NSNib(nibNamed: "GridItem", bundle: nil), forItemWithIdentifier: NSUserInterfaceItemIdentifier("GridItem"))`.
        *   After calculating the initial layout, fetch the first page of items from Rust: `displayedItems = core.getItems(start: 0, count: UInt32(visibleRows * Int(numColumns)))`.
    *   In `calculateGridLayout()`, after calculating `itemWidth` and `itemHeight`, update the layout: `(collectionView.collectionViewLayout as? NSCollectionViewGridLayout)?.itemSize = NSSize(width: itemWidth, height: itemHeight)`.
    *   After fetching data or recalculating layout, call `collectionView.reloadData()`.
4.  **Implement `NSCollectionViewDataSource`:**
    *   Make `MainViewController` conform to `NSCollectionViewDataSource`.
    *   `numberOfItems(in:section:)`: return `displayedItems.count`.
    *   `itemForRepresentedObject(at:)`: Dequeue a `GridItem`, get the data from `displayedItems` at the given `indexPath.item`, and call the item's `configure()` method.

**Success Criteria:**
1.  **Visual Verification:** The app window must display a grid of 5 columns, filling the available space. Each cell must contain the designed gray box, number, and text.
2.  **Correct Layout:** Resizing the window should cause the cells to grow or shrink, but the number of columns and visible rows remains fixed until the column count is explicitly changed.
3.  **Partial Row:** Test by temporarily reducing the item count in Rust to 12. The grid should render two full rows and a third row with only two items, with the rest of the space being empty.

---

### Work Item 5: Expose Configuration Mutators in Rust

**(This work item is identical to the previous version.)**

**Description:**
Add the ability for the Swift client to modify the number of columns stored in the Rust `Core`'s configuration. The operations will be simple increments and decrements, with sensible bounds.

**Tasks:**
1.  **In `lib.rs`:**
    *   Wrap the `Core`'s `config` field in a `Mutex` or `RwLock` to ensure thread-safe mutations: `config: Mutex<Config>`.
    *   Implement a method on `Arc<Core>` named `increase_columns()` that increments `config.num_columns` by 1 (up to a max of 20).
    *   Implement `decrease_columns()` that decrements by 1 (down to a min of 1).
2.  **Update `corelib.udl` and Regenerate:** Add the new methods and run `uniffi-bindgen`.

**Success Criteria:**
1.  **Unit Tests in Rust:**
    *   Write a test `test_column_modification()` to verify the increment, decrement, and boundary logic.
2.  **Builds Successfully:** The Swift and Rust projects must compile.

---

### Work Item 6: Implement Dynamic Column Changes and Scrolling Logic

**Description:**
Connect UI elements (menu items) to modify the number of columns and implement the logic for row-by-row scrolling. A column change must trigger a full layout and data refresh.

**Tasks:**
1.  **Add Menu Items:**
    *   In `MainMenu.xib`, add "Increase Columns" and "Decrease Columns" menu items.
    *   Connect these menu items to new `@IBAction` functions in `MainViewController`: `increaseColumns(_:)` and `decreaseColumns(_:)`.
2.  **Implement Column Change Actions:**
    *   Inside `increaseColumns(_:)`:
        *   Call `core.increaseColumns()`.
        *   Update the local state: `numColumns = core.getConfig().numColumns`.
        *   Call `calculateGridLayout()`.
        *   Re-fetch the visible data and reload: `fetchAndReloadVisibleData()`.
    *   Implement `decreaseColumns(_:)` similarly.
3.  **Scrolling State and Logic:**
    *   Add state properties to `MainViewController`: `private var currentRow: Int = 0`, `private var totalRows: Int = 0`, `private var maxScrollRow: Int = 0`.
    *   Update these values inside `calculateGridLayout()`.
    *   **For now, use menu items for scrolling.** Add "Scroll Up" and "Scroll Down" menu items and connect them to `@IBAction` functions.
    *   Inside the `scrollDown(_:)` action: `if currentRow < maxScrollRow { currentRow += 1; fetchAndReloadVisibleData() }`. Implement `scrollUp` similarly.
4.  **Create `fetchAndReloadVisibleData()`:**
    *   Create a central function to handle data fetching.
    *   Calculate the start index: `let startIndex = UInt32(currentRow * Int(numColumns))`.
    *   Calculate the item count: `let count = UInt32(visibleRows * Int(numColumns))`.
    *   **Perform fetch on a background thread and update UI on main:**
        ```swift
        DispatchQueue.global().async {
            let items = self.core.getItems(start: startIndex, count: count)
            DispatchQueue.main.async {
                self.displayedItems = items
                self.collectionView.reloadData()
            }
        }
        ```

**Success Criteria:**
1.  **Column Change Works:** Choosing "Increase Columns" from the menu must immediately re-render the grid with 6 columns. The item heights should adjust to fill the vertical space. The grid should attempt to keep the previously top-visible items in view.
2.  **Scrolling Works:** Choosing "Scroll Down" from the menu must replace the content of the `NSCollectionView` with the next page of items fetched from the Rust library.
3.  **Thread Safety:** The app must remain responsive, and UI updates must not cause crashes, proving the main-thread dispatch is correct.