import AppKit
import UniffiBindings

class MainViewController: NSViewController, NSCollectionViewDataSource, RowBasedScrollViewDelegate {
    // MARK: - Properties for state storage
    private var core: Core!
    private var panelWidth: CGFloat = 0
    private var panelHeight: CGFloat = 0
    private var numColumns: UInt32 = 0
    private var itemWidth: CGFloat = 0
    private var itemHeight: CGFloat = 0
    private var visibleRows: Int = 0
    private var currentRow: Int = 0
    private var maxScrollRow: Int = 0

    // MARK: - Data
    private var displayedItems: [Item] = []

    // MARK: - UI Components
    private var mainView: MainView!
    private var collectionView: NSCollectionView!
    private var scrollView: RowBasedScrollView!

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

        // Set up collection view
        setupCollectionView()

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

    // MARK: - Collection View Setup
    private func setupCollectionView() {
        // Create custom scroll view
        scrollView = RowBasedScrollView()
        scrollView.translatesAutoresizingMaskIntoConstraints = false
        scrollView.rowScrollDelegate = self

        // Create collection view
        collectionView = NSCollectionView()
        collectionView.translatesAutoresizingMaskIntoConstraints = false

        // Configure the grid layout
        let layout = NSCollectionViewGridLayout()
        collectionView.collectionViewLayout = layout

        // Register the GridItem class for the collection view
        collectionView.register(
            GridItem.self, forItemWithIdentifier: NSUserInterfaceItemIdentifier("GridItem"))

        // Set data source
        collectionView.dataSource = self

        // Set collection view as document view of scroll view
        scrollView.documentView = collectionView

        // Add scroll view to left panel
        mainView.leftPanel.addSubview(scrollView)

        // Set up constraints
        NSLayoutConstraint.activate([
            scrollView.topAnchor.constraint(equalTo: mainView.leftPanel.topAnchor, constant: 8),
            scrollView.leadingAnchor.constraint(
                equalTo: mainView.leftPanel.leadingAnchor, constant: 8),
            scrollView.trailingAnchor.constraint(
                equalTo: mainView.leftPanel.trailingAnchor, constant: -8),
            scrollView.bottomAnchor.constraint(
                equalTo: mainView.leftPanel.bottomAnchor, constant: -8),
        ])
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

        // Update collection view layout if it exists
        if let gridLayout = collectionView?.collectionViewLayout as? NSCollectionViewGridLayout {
            gridLayout.minimumItemSize = NSSize(width: itemWidth, height: itemHeight)
            gridLayout.maximumItemSize = NSSize(width: itemWidth, height: itemHeight)
            gridLayout.minimumLineSpacing = 8
            gridLayout.minimumInteritemSpacing = 8
            gridLayout.maximumNumberOfColumns = Int(numColumns)
        }

        // Calculate max scroll row based on total items
        let totalItems = Int(core.getTotalItemCount())
        let totalRows = (totalItems + Int(numColumns) - 1) / Int(numColumns)  // Ceiling division
        maxScrollRow = max(0, totalRows - visibleRows)

        // Ensure currentRow is within bounds
        currentRow = min(currentRow, maxScrollRow)

        // Fetch and reload visible data
        fetchAndReloadVisibleData()
    }

    // MARK: - Data Fetching
    private func fetchAndReloadVisibleData() {
        let totalVisibleItems = Int(numColumns) * visibleRows
        let startIndex = currentRow * Int(numColumns)

        // Perform Rust call on background thread
        DispatchQueue.global(qos: .userInitiated).async { [weak self] in
            guard let self = self else { return }

            let items = self.core.getItems(
                start: UInt32(startIndex), count: UInt32(totalVisibleItems))

            // Update UI on main thread
            DispatchQueue.main.async {
                self.displayedItems = items
                self.collectionView?.reloadData()

                print(
                    "📦 Fetched \(items.count) items from Rust core (row \(self.currentRow)/\(self.maxScrollRow))"
                )
                if !items.isEmpty {
                    print("   First item: id=\(items[0].id), text='\(items[0].text)'")
                }
            }
        }
    }

    // MARK: - Private Methods
    private func setupLayoutObservation() {
        // Additional setup for layout observation if needed
        // The viewDidLayout method will be called automatically when the view's frame changes
    }

    // MARK: - Menu Actions
    @objc func increaseColumns() {
        let numColumnsBeforeChange = numColumns

        // Call Rust core to increase columns
        core.increaseColumns()

        // Update state
        numColumns = core.getConfig().numColumns

        // Calculate the index of the top-left item before layout change
        let firstVisibleIndex = currentRow * Int(numColumnsBeforeChange)

        // Recalculate layout
        calculateGridLayout()

        // Adjust currentRow to show the firstVisibleIndex
        currentRow = firstVisibleIndex / Int(numColumns)
        currentRow = min(currentRow, maxScrollRow)

        // Fetch and reload data
        fetchAndReloadVisibleData()
    }

    @objc func decreaseColumns() {
        let numColumnsBeforeChange = numColumns

        // Call Rust core to decrease columns
        core.decreaseColumns()

        // Update state
        numColumns = core.getConfig().numColumns

        // Calculate the index of the top-left item before layout change
        let firstVisibleIndex = currentRow * Int(numColumnsBeforeChange)

        // Recalculate layout
        calculateGridLayout()

        // Adjust currentRow to show the firstVisibleIndex
        currentRow = firstVisibleIndex / Int(numColumns)
        currentRow = min(currentRow, maxScrollRow)

        // Fetch and reload data
        fetchAndReloadVisibleData()
    }
}

// MARK: - RowBasedScrollViewDelegate
extension MainViewController {
    func scrollViewDidScroll(direction: ScrollDirection) {
        switch direction {
        case .down:
            if currentRow < maxScrollRow {
                currentRow += 1
                fetchAndReloadVisibleData()
            }
        case .up:
            if currentRow > 0 {
                currentRow -= 1
                fetchAndReloadVisibleData()
            }
        }
    }
}

// MARK: - NSCollectionViewDataSource
extension MainViewController {
    func collectionView(_ collectionView: NSCollectionView, numberOfItemsInSection section: Int)
        -> Int
    {
        return displayedItems.count
    }

    func collectionView(
        _ collectionView: NSCollectionView, itemForRepresentedObjectAt indexPath: IndexPath
    ) -> NSCollectionViewItem {
        let item =
            collectionView.makeItem(
                withIdentifier: NSUserInterfaceItemIdentifier("GridItem"), for: indexPath)
            as! GridItem
        let dataItem = displayedItems[indexPath.item]
        item.configure(with: dataItem)
        return item
    }
}
