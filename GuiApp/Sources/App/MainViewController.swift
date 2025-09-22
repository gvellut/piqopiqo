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
    private var totalRows: Int = 0
    private var lastStartIndex: Int = 0
    private var isSnappingScroll: Bool = false
    // Layout constants
    private let horizontalEdgeInset: CGFloat = 8  // matches scroll view constraints
    private let verticalEdgeInset: CGFloat = 8  // matches scroll view constraints
    private let interItemSpacing: CGFloat = 8
    private let lineSpacing: CGFloat = 8

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
        panelWidth = mainView.leftPanel.bounds.width
        panelHeight = mainView.leftPanel.bounds.height

        // Calculate and update grid layout
        calculateGridLayout()
    }

    // MARK: - Collection View Setup
    private func setupCollectionView() {
        // Create custom scroll view
        scrollView = RowBasedScrollView()
        scrollView.translatesAutoresizingMaskIntoConstraints = false
        scrollView.rowScrollDelegate = self
        scrollView.hasVerticalScroller = true
        scrollView.autohidesScrollers = true
        scrollView.contentView.postsBoundsChangedNotifications = true

        // Create collection view
        collectionView = NSCollectionView()
        // As a documentView, Auto Layout is not used; rely on autoresizing mask.
        collectionView.translatesAutoresizingMaskIntoConstraints = true
        collectionView.autoresizingMask = [.width]

        // Configure a flow layout to strictly control columns via itemSize
        let layout = NSCollectionViewFlowLayout()
        layout.minimumInteritemSpacing = interItemSpacing
        layout.minimumLineSpacing = lineSpacing
        layout.sectionInset = NSEdgeInsets(top: lineSpacing, left: 0, bottom: lineSpacing, right: 0)
        collectionView.collectionViewLayout = layout

        // Register the GridItem class for the collection view
        collectionView.register(
            GridItem.self, forItemWithIdentifier: NSUserInterfaceItemIdentifier("GridItem"))

        // Set data source
        collectionView.dataSource = self

        // Match collection view frame to scroll view's visible bounds initially
        collectionView.frame = scrollView.contentView.bounds

        // Set collection view as document view of scroll view
        scrollView.documentView = collectionView

        // Observe clip view scrolling to snap to row boundaries (handles scrollbar drags)
        NotificationCenter.default.addObserver(
            self,
            selector: #selector(clipViewBoundsDidChange(_:)),
            name: NSView.boundsDidChangeNotification,
            object: scrollView.contentView
        )

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

        // Compute available content size inside scroll view insets
        // Horizontal: account for our scroll view constraints (8pt each side) and inter-item spacing
        let totalInterItemSpacing = interItemSpacing * CGFloat(numColumns - 1)
        let availableWidth = max(0, panelWidth - 2 * horizontalEdgeInset - totalInterItemSpacing)
        itemWidth = availableWidth / CGFloat(numColumns)

        // Vertical: compute available vertical height minus top/bottom insets (match constraints)
        let availableHeight = max(0, panelHeight - 2 * verticalEdgeInset)

        // Start with square item height
        var computedItemHeight = itemWidth
        let totalItems = Int(core.getTotalItemCount())

        // Base rows that fit without cutting, using floor, and considering line spacing
        let rowUnit = computedItemHeight + lineSpacing
        let baseVisibleRows = max(1, Int(floor((availableHeight + lineSpacing) / rowUnit)))
        visibleRows = baseVisibleRows

        // If we have enough items to fill baseVisibleRows completely, stretch height to fill
        let capacityAtBase = Int(numColumns) * baseVisibleRows
        if totalItems >= capacityAtBase {
            let totalSpacingHeight = lineSpacing * CGFloat(max(0, baseVisibleRows - 1))
            let filledHeight = (availableHeight - totalSpacingHeight) / CGFloat(baseVisibleRows)
            computedItemHeight = max(computedItemHeight, filledHeight)
        } else {
            // Not enough items: keep square height and leave empty space below
            computedItemHeight = itemWidth
        }
        itemHeight = computedItemHeight

        // Update flow layout with final item size
        if let flow = collectionView.collectionViewLayout as? NSCollectionViewFlowLayout {
            flow.itemSize = NSSize(width: itemWidth, height: itemHeight)
            flow.minimumInteritemSpacing = interItemSpacing
            flow.minimumLineSpacing = lineSpacing
        }

        // Log calculated values for verification
        print("🔢 Layout calculated:")
        print("   Panel: \(Int(panelWidth))×\(Int(panelHeight))")
        print("   Columns: \(numColumns)")
        print("   Item size: \(Int(itemWidth))×\(Int(itemHeight))")
        print("   Visible rows: \(visibleRows)")
        print("   Total visible items: \(Int(numColumns) * visibleRows)")

        // Update document view frame height to reflect total content (for proper scrollbar/thumb)
        let totalRowsCount = max(1, Int(ceil(Double(totalItems) / Double(numColumns))))
        let contentHeight =
            CGFloat(totalRowsCount) * itemHeight
            + CGFloat(max(0, totalRowsCount - 1)) * lineSpacing
        var docFrame = collectionView.frame
        docFrame.size.width = scrollView.contentView.bounds.width
        docFrame.size.height = contentHeight
        collectionView.frame = docFrame

        // Calculate max scroll row based on total items and visible rows
        totalRows = totalRowsCount
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
        let prevDisplayed = self.displayedItems
        let prevStartIndex = self.lastStartIndex

        // Perform Rust call on background thread
        DispatchQueue.global(qos: .userInitiated).async { [weak self] in
            guard let self = self else { return }
            let items: [Item]
            let step = Int(self.numColumns)
            if !prevDisplayed.isEmpty && totalVisibleItems == prevDisplayed.count {
                let delta = startIndex - prevStartIndex
                if delta == step {
                    // Scrolled down by one row: reuse top items
                    let reuse = Array(prevDisplayed.dropFirst(step))
                    let fetchStart = startIndex + (totalVisibleItems - step)
                    let fetched = self.core.getItems(start: UInt32(fetchStart), count: UInt32(step))
                    items = reuse + fetched
                } else if delta == -step {
                    // Scrolled up by one row: reuse bottom items
                    let reuse = Array(prevDisplayed.prefix(totalVisibleItems - step))
                    let fetchStart = startIndex
                    let fetched = self.core.getItems(start: UInt32(fetchStart), count: UInt32(step))
                    items = fetched + reuse
                } else {
                    items = self.core.getItems(
                        start: UInt32(startIndex), count: UInt32(totalVisibleItems))
                }
            } else {
                items = self.core.getItems(
                    start: UInt32(startIndex), count: UInt32(totalVisibleItems))
            }

            // Update UI on main thread
            DispatchQueue.main.async {
                self.displayedItems = items
                self.collectionView?.reloadData()
                self.lastStartIndex = startIndex

                // Update the scroll bar position to reflect currentRow
                self.scrollView?.updateScrollPosition(
                    currentRow: self.currentRow,
                    totalRows: self.totalRows,
                    visibleRows: self.visibleRows
                )

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

    @objc private func clipViewBoundsDidChange(_ notification: Notification) {
        guard !isSnappingScroll else { return }
        guard let clip = notification.object as? NSClipView, clip === scrollView.contentView else {
            return
        }
        let unit = itemHeight + lineSpacing
        guard unit > 0 else { return }
        let y = clip.bounds.origin.y
        let targetRow = max(0, min(maxScrollRow, Int(round(y / unit))))
        let targetY = CGFloat(targetRow) * unit
        if abs(targetY - y) > 0.5 {
            isSnappingScroll = true
            clip.scroll(to: NSPoint(x: 0, y: targetY))
            scrollView.reflectScrolledClipView(clip)
            isSnappingScroll = false
        }
        if targetRow != currentRow {
            currentRow = targetRow
            fetchAndReloadVisibleData()
        }
    }

    deinit {
        NotificationCenter.default.removeObserver(self)
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
