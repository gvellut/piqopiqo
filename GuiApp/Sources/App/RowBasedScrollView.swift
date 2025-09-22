import AppKit

enum ScrollDirection {
    case up, down
}

protocol RowBasedScrollViewDelegate: AnyObject {
    func scrollViewDidScroll(direction: ScrollDirection)
}

class RowBasedScrollView: NSScrollView {
    weak var rowScrollDelegate: RowBasedScrollViewDelegate?
    private var lastScrollEventTimestamp: TimeInterval = 0

    // MARK: - Public Methods
    func updateScrollPosition(currentRow: Int, totalRows: Int, visibleRows: Int) {
        guard let documentView = documentView else { return }

        // Calculate scroll position as a fraction of total scrollable area
        let maxScrollableRows = max(0, totalRows - visibleRows)
        guard maxScrollableRows > 0 else { return }

        let scrollFraction = CGFloat(currentRow) / CGFloat(maxScrollableRows)

        // Get the document view's frame
        let documentHeight = documentView.frame.height
        let clipHeight = contentView.frame.height

        // Calculate the scroll position
        let maxScrollY = max(0, documentHeight - clipHeight)
        let targetY = maxScrollY * scrollFraction

        // Update the scroll position
        DispatchQueue.main.async { [weak self] in
            self?.contentView.scroll(to: NSPoint(x: 0, y: targetY))
            self?.reflectScrolledClipView(self?.contentView ?? NSClipView())
        }
    }

    override func scrollWheel(with event: NSEvent) {
        // Handle different scroll phases and devices
        let deltaY: CGFloat

        // Debug logging
        print(
            "🖱️ Scroll wheel event - Phase: \(event.phase.rawValue), hasPrecise: \(event.hasPreciseScrollingDeltas)"
        )
        print("   deltaY: \(event.deltaY), scrollingDeltaY: \(event.scrollingDeltaY)")

        // Check if this is a trackpad gesture or mouse wheel
        if event.hasPreciseScrollingDeltas {
            // Trackpad - use phase to detect discrete gestures
            guard event.phase == .began || event.phase == .changed else {
                print("   Ignoring trackpad phase: \(event.phase.rawValue)")
                return
            }
            deltaY = event.scrollingDeltaY
        } else {
            // Mouse wheel - no phase, use delta directly
            deltaY = event.deltaY
        }

        // Implement throttling to prevent rapid-fire events
        let currentTime = Date().timeIntervalSince1970
        guard currentTime - lastScrollEventTimestamp > 0.1 else {
            print("   Throttled (too soon)")
            return
        }

        // Check for significant vertical scroll
        let threshold: CGFloat = event.hasPreciseScrollingDeltas ? 5.0 : 0.1

        print("   Using deltaY: \(deltaY), threshold: \(threshold)")

        if deltaY < -threshold {
            // Scrolling down (negative delta)
            print("   📍 Scrolling DOWN")
            rowScrollDelegate?.scrollViewDidScroll(direction: .down)
            lastScrollEventTimestamp = currentTime
        } else if deltaY > threshold {
            // Scrolling up (positive delta)
            print("   📍 Scrolling UP")
            rowScrollDelegate?.scrollViewDidScroll(direction: .up)
            lastScrollEventTimestamp = currentTime
        } else {
            print("   No action (below threshold)")
        }

        // Do NOT call super.scrollWheel to prevent default pixel-based scrolling
    }
}
