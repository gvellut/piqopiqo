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

### Work Item 6: Implement Dynamic Column Changes and Scrolling Logic Programmatically

**Description:**
This work item focuses on bringing the grid to life. All UI components for interaction—menus and the scrollable collection view—will be created in code. You will implement the logic to handle dynamic column changes triggered by menu items. Crucially, you will also implement the custom row-by-row scrolling behavior by intercepting scroll wheel events, updating the application's state, and fetching the corresponding data from the Rust core.

**Tasks:**

1.  **Programmatically Create Menus in `AppDelegate` or `MainViewController`:**
    *   In your application setup (likely the `AppDelegate`'s `applicationDidFinishLaunching` or within the `MainViewController`'s initialization), create the main menu bar.
    *   Create a "View" menu (`NSMenu`).
    *   Create three menu items: "Increase Columns", "Decrease Columns", and a separator.
    *   Assign an `action` selector to each item (e.g., `#selector(MainViewController.increaseColumns)`). The `target` for these actions will be your `MainViewController` instance. You may need to route this through the responder chain or set the target explicitly.
    *   Add this "View" menu to the application's main menu bar.

2.  **Create a Custom `NSScrollView` for Row-by-Row Scrolling:**
    *   Create a new Swift file for a class named `RowBasedScrollView`, subclassing `NSScrollView`.
    *   Define a delegate protocol for this class:
        ```swift
        protocol RowBasedScrollViewDelegate: AnyObject {
            func scrollViewDidScroll(direction: ScrollDirection)
        }
        enum ScrollDirection {
            case up, down
        }
        ```
    *   Add a `weak var rowScrollDelegate: RowBasedScrollViewDelegate?` property to your `RowBasedScrollView` class.
    *   Add a property to prevent rapid-fire events, e.g., `private var lastScrollEventTimestamp: TimeInterval = 0`.
    *   Override the `scrollWheel(with event: NSEvent)` method.
        *   Inside, check if the event is a scrolling event (`event.phase == .changed`).
        *   Check the vertical delta: `event.scrollingDeltaY`.
        *   Implement a debounce/throttling mechanism. For example, if less than 0.3 seconds have passed since the last processed scroll event, `return`.
        *   If `scrollingDeltaY` is significantly negative (e.g., `< -0.5`), call `rowScrollDelegate?.scrollViewDidScroll(direction: .down)` and update `lastScrollEventTimestamp`.
        *   If `scrollingDeltaY` is significantly positive (e.g., `> 0.5`), call `rowScrollDelegate?.scrollViewDidScroll(direction: .up)` and update `lastScrollEventTimestamp`.
        *   **Do not call `super.scrollWheel(with: event)`** to prevent the default pixel-based scrolling.

3.  **Integrate the Custom Scroll View in `MainViewController`:**
    *   In `MainViewController`'s `loadView()` method, where you programmatically create your views:
        *   Instantiate your `RowBasedScrollView` instead of a standard `NSScrollView`.
        *   Instantiate the `NSCollectionView`.
        *   Set the `collectionView` as the `documentView` of your `RowBasedScrollView` instance.
        *   Set the controller as the delegate: `scrollView.rowScrollDelegate = self`.
        *   Add the scroll view to the controller's main view and set up its Auto Layout constraints to fill the view.

4.  **Implement Action and Delegate Methods in `MainViewController`:**
    *   Make `MainViewController` conform to the `RowBasedScrollViewDelegate` protocol.
    *   Create the `@objc func increaseColumns()` method:
        *   Call `core.increaseColumns()`.
        *   Update state: `numColumns = core.getConfig().numColumns`.
        *   To keep the top item in view, calculate the index of the top-left item *before* the layout change: `let firstVisibleIndex = currentRow * Int(numColumnsBeforeChange)`.
        *   Recalculate the layout: `calculateGridLayout()`.
        *   Adjust `currentRow` to show the `firstVisibleIndex`: `currentRow = firstVisibleIndex / Int(numColumns)`.
        *   Fetch and reload data: `fetchAndReloadVisibleData()`.
    *   Implement `@objc func decreaseColumns()` similarly.
    *   Implement the delegate method `scrollViewDidScroll(direction: ScrollDirection)`:
        *   Use a `switch` on the `direction`.
        *   For `.down`: `if currentRow < maxScrollRow { currentRow += 1; fetchAndReloadVisibleData() }`.
        *   For `.up`: `if currentRow > 0 { currentRow -= 1; fetchAndReloadVisibleData() }`.

5.  **Centralize Data Fetching and Reloading:**
    *   Ensure the `fetchAndReloadVisibleData()` function from Work Item 4 is robust. It should be the single source of truth for loading data into the collection view based on the current state (`currentRow`, `numColumns`, `visibleRows`).
    *   This function must perform the Rust call on a background thread and update the `displayedItems` property and call `collectionView.reloadData()` on the main thread to prevent UI freezing.

**Success Criteria:**

1.  **Programmatic UI Verified:** The application launches and displays the grid and menus correctly without relying on any XIB or Storyboard files. There are no `@IBOutlet` or `@IBAction` keywords in the `MainViewController`.
2.  **Menu Actions Work:** Clicking "Increase Columns" or "Decrease Columns" in the "View" menu correctly changes the number of columns in the grid, recalculates the layout, and reloads the appropriate items.
3.  **Row-by-Row Scrolling:** Using the mouse scroll wheel or a two-finger trackpad gesture triggers discrete, row-by-row scrolling. One "tick" or "flick" of the scroll gesture moves the grid up or down by exactly one full row. There is no smooth, pixel-based scrolling.
4.  **State Integrity:** Scrolling and column changes are correctly bounded. The user cannot scroll past the beginning or end of the item list. The number of columns is kept within the limits defined in Rust.
5.  **Responsiveness:** The application UI remains responsive and does not stutter or freeze, even during fast scrolling or column changes, validating the background data fetching pattern.