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

    override func scrollWheel(with event: NSEvent) {
        // Check if this is a scrolling event
        guard event.phase == .changed else {
            return
        }

        // Implement throttling to prevent rapid-fire events
        let currentTime = Date().timeIntervalSince1970
        guard currentTime - lastScrollEventTimestamp > 0.2 else {
            return
        }

        let deltaY = event.scrollingDeltaY

        // Check for significant vertical scroll (reduced threshold for better responsiveness)
        if deltaY < -0.3 {
            // Scrolling down (negative delta)
            rowScrollDelegate?.scrollViewDidScroll(direction: .down)
            lastScrollEventTimestamp = currentTime
        } else if deltaY > 0.3 {
            // Scrolling up (positive delta)
            rowScrollDelegate?.scrollViewDidScroll(direction: .up)
            lastScrollEventTimestamp = currentTime
        }

        // Do NOT call super.scrollWheel to prevent default pixel-based scrolling
    }
}
