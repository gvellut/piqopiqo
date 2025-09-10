import AppKit
import UniffiBindings

class MainViewController: NSViewController {
    // MARK: - Properties for state storage
    private var core: Core!
    private var panelWidth: CGFloat = 0
    private var panelHeight: CGFloat = 0
    private var numColumns: UInt32 = 0
    private var itemWidth: CGFloat = 0
    private var itemHeight: CGFloat = 0
    private var visibleRows: Int = 0

    // MARK: - UI Components
    private var mainView: MainView!

    override func loadView() {
        mainView = MainView()
        view = mainView
    }

    override func viewDidLoad() {
        super.viewDidLoad()

        // Initialize the Rust core object
        core = coreNew()

        // Fetch the initial configuration
        let config = core.getConfig()
        numColumns = config.numColumns

        print("📋 Core initialized with \(numColumns) columns")

        // Set up view layout observation
        setupLayoutObservation()
    }

    override func viewDidLayout() {
        super.viewDidLayout()

        // Update panel dimensions from view bounds
        panelWidth = view.bounds.width
        panelHeight = view.bounds.height

        // Calculate and update grid layout
        calculateGridLayout()
    }

    // MARK: - Layout Calculation
    private func calculateGridLayout() {
        // Ensure we have valid dimensions
        guard panelWidth > 0 && panelHeight > 0 && numColumns > 0 else {
            print(
                "⚠️ Invalid dimensions: width=\(panelWidth), height=\(panelHeight), columns=\(numColumns)"
            )
            return
        }

        // Grid layout algorithm implementation
        // Based on the typical photo grid layout with square-ish items

        // Calculate item width based on available width and number of columns
        let padding: CGFloat = 16  // Total horizontal padding
        let itemSpacing: CGFloat = 8  // Space between items
        let totalSpacing = itemSpacing * CGFloat(numColumns - 1)  // Space between columns
        let availableWidth = panelWidth - padding - totalSpacing
        itemWidth = availableWidth / CGFloat(numColumns)

        // For photo grids, maintain approximately square aspect ratio
        // Add a bit of height for potential caption/metadata area
        itemHeight = itemWidth * 1.1

        // Calculate how many rows can fit in the visible area
        let headerHeight: CGFloat = 40  // Space for potential header
        let footerHeight: CGFloat = 30  // Space for status bar
        let verticalPadding: CGFloat = 16
        let rowSpacing: CGFloat = 8

        let availableHeight = panelHeight - headerHeight - footerHeight - verticalPadding

        // Calculate number of visible rows
        if itemHeight > 0 {
            let totalRowHeight = itemHeight + rowSpacing
            visibleRows = max(1, Int(availableHeight / totalRowHeight))
        } else {
            visibleRows = 1
        }

        // Log calculated values for verification
        print("🔢 Layout calculated:")
        print("   Panel: \(Int(panelWidth))×\(Int(panelHeight))")
        print("   Columns: \(numColumns)")
        print("   Item size: \(Int(itemWidth))×\(Int(itemHeight))")
        print("   Visible rows: \(visibleRows)")
        print("   Total visible items: \(Int(numColumns) * visibleRows)")
    }

    // MARK: - Private Methods
    private func setupLayoutObservation() {
        // Additional setup for layout observation if needed
        // The viewDidLayout method will be called automatically when the view's frame changes
    }
}
