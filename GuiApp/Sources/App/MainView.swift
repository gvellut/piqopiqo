import AppKit
import UniffiBindings

class MainView: NSView {
    private(set) var splitView: NSSplitView!
    private var leftPanel: NSView!
    private var rightPanel: NSView!
    private let splitAutosaveKey = "NSSplitView Subview Frames MainSplitView"

    override init(frame frameRect: NSRect) {
        super.init(frame: frameRect)
        setupUI()
    }

    required init?(coder: NSCoder) {
        super.init(coder: coder)
        setupUI()
    }

    private func setupUI() {
        wantsLayer = true
        layer?.backgroundColor = NSColor.windowBackgroundColor.cgColor

        splitView = NSSplitView()
        splitView.isVertical = true
        splitView.dividerStyle = .thin
        splitView.translatesAutoresizingMaskIntoConstraints = false
        addSubview(splitView)

        leftPanel = NSView()
        leftPanel.wantsLayer = true
        leftPanel.layer?.backgroundColor = NSColor.controlBackgroundColor.cgColor

        let gridLabel = NSTextField(labelWithString: "Grid Panel")
        gridLabel.font = NSFont.systemFont(ofSize: 18, weight: .medium)
        gridLabel.alignment = .center
        gridLabel.translatesAutoresizingMaskIntoConstraints = false
        leftPanel.addSubview(gridLabel)

        rightPanel = NSView()
        rightPanel.wantsLayer = true
        rightPanel.layer?.backgroundColor = NSColor.controlBackgroundColor.cgColor

        let detailLabel = NSTextField(labelWithString: "Detail Panel")
        detailLabel.font = NSFont.systemFont(ofSize: 18, weight: .medium)
        detailLabel.alignment = .center
        detailLabel.translatesAutoresizingMaskIntoConstraints = false
        rightPanel.addSubview(detailLabel)

        let rustString = helloFromRust()
        let rustLabel = NSTextField(labelWithString: rustString)
        rustLabel.font = NSFont.systemFont(ofSize: 12)
        rustLabel.alignment = .center
        rustLabel.isBordered = false
        rustLabel.isEditable = false
        rustLabel.translatesAutoresizingMaskIntoConstraints = false
        rightPanel.addSubview(rustLabel)

        // Add subviews BEFORE assigning autosaveName so NSSplitView can restore them.
        splitView.addArrangedSubview(leftPanel)
        splitView.addArrangedSubview(rightPanel)

        // Now enable autosave.
        splitView.autosaveName = "MainSplitView"

        NSLayoutConstraint.activate([
            splitView.topAnchor.constraint(equalTo: topAnchor),
            splitView.leadingAnchor.constraint(equalTo: leadingAnchor),
            splitView.trailingAnchor.constraint(equalTo: trailingAnchor),
            splitView.bottomAnchor.constraint(equalTo: bottomAnchor),

            gridLabel.centerXAnchor.constraint(equalTo: leftPanel.centerXAnchor),
            gridLabel.centerYAnchor.constraint(equalTo: leftPanel.centerYAnchor),

            detailLabel.centerXAnchor.constraint(equalTo: rightPanel.centerXAnchor),
            detailLabel.centerYAnchor.constraint(equalTo: rightPanel.centerYAnchor, constant: -20),

            rustLabel.centerXAnchor.constraint(equalTo: rightPanel.centerXAnchor),
            rustLabel.topAnchor.constraint(equalTo: detailLabel.bottomAnchor, constant: 20),
            rustLabel.leadingAnchor.constraint(
                greaterThanOrEqualTo: rightPanel.leadingAnchor, constant: 10),
            rustLabel.trailingAnchor.constraint(
                lessThanOrEqualTo: rightPanel.trailingAnchor, constant: -10),
        ])

        leftPanel.widthAnchor.constraint(greaterThanOrEqualToConstant: 500).isActive = true
        rightPanel.widthAnchor.constraint(greaterThanOrEqualToConstant: 200).isActive = true
        rightPanel.widthAnchor.constraint(lessThanOrEqualToConstant: 400).isActive = true
    }

    /// Call after the view is in a window & laid out.
    func restoreOrInitializeDivider() {
        let defaults = UserDefaults.standard
        if defaults.object(forKey: splitAutosaveKey) == nil {
            // First launch (no saved frames) — set an initial position once layout done.
            DispatchQueue.main.async { [weak self] in
                guard let self = self else { return }
                // 700pt left if possible, else 2/3 of width.
                let fallback = self.bounds.width * 0.66
                let target = min(max(500, fallback), self.bounds.width - 200)
                self.splitView.setPosition(target, ofDividerAt: 0)
            }
        }
        // If there IS saved state, NSSplitView already applied it when autosaveName was set
        // (after subviews were added). No manual action needed.
    }
}
