import AppKit

// import RustBridge

// Custom AppKit view to replace the SwiftUI ContentView
class MainView: NSView {
    private var splitView: NSSplitView!
    private var leftPanel: NSView!
    private var rightPanel: NSView!

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

        // Create the split view
        splitView = NSSplitView()
        splitView.isVertical = true  // Horizontal split (vertical divider)
        splitView.dividerStyle = .thin
        splitView.translatesAutoresizingMaskIntoConstraints = false
        addSubview(splitView)

        // Create left panel (Grid Panel)
        leftPanel = NSView()
        leftPanel.wantsLayer = true
        leftPanel.layer?.backgroundColor = NSColor.controlBackgroundColor.cgColor

        let gridLabel = NSTextField(labelWithString: "Grid Panel")
        gridLabel.font = NSFont.systemFont(ofSize: 18, weight: .medium)
        gridLabel.alignment = .center
        gridLabel.translatesAutoresizingMaskIntoConstraints = false
        leftPanel.addSubview(gridLabel)

        // Create right panel (Detail Panel)
        rightPanel = NSView()
        rightPanel.wantsLayer = true
        rightPanel.layer?.backgroundColor = NSColor.controlBackgroundColor.cgColor

        let detailLabel = NSTextField(labelWithString: "Detail Panel")
        detailLabel.font = NSFont.systemFont(ofSize: 18, weight: .medium)
        detailLabel.alignment = .center
        detailLabel.translatesAutoresizingMaskIntoConstraints = false
        rightPanel.addSubview(detailLabel)

        // Add placeholder for Rust message to right panel
        // let rustMessage = RustFFI.getGreetingFromRust()
        let rustLabel = NSTextField(labelWithString: "Rust integration pending...")
        rustLabel.font = NSFont.systemFont(ofSize: 12)
        rustLabel.alignment = .center
        rustLabel.backgroundColor = NSColor.lightGray.withAlphaComponent(0.1)
        rustLabel.isBordered = false
        rustLabel.isEditable = false
        rustLabel.translatesAutoresizingMaskIntoConstraints = false
        rightPanel.addSubview(rustLabel)

        // Add panels to split view
        splitView.addArrangedSubview(leftPanel)
        splitView.addArrangedSubview(rightPanel)

        // Set up constraints for split view
        NSLayoutConstraint.activate([
            splitView.topAnchor.constraint(equalTo: topAnchor),
            splitView.leadingAnchor.constraint(equalTo: leadingAnchor),
            splitView.trailingAnchor.constraint(equalTo: trailingAnchor),
            splitView.bottomAnchor.constraint(equalTo: bottomAnchor),
        ])

        // Set up constraints for grid label in left panel
        NSLayoutConstraint.activate([
            gridLabel.centerXAnchor.constraint(equalTo: leftPanel.centerXAnchor),
            gridLabel.centerYAnchor.constraint(equalTo: leftPanel.centerYAnchor),
        ])

        // Set up constraints for detail label and rust message in right panel
        NSLayoutConstraint.activate([
            detailLabel.centerXAnchor.constraint(equalTo: rightPanel.centerXAnchor),
            detailLabel.centerYAnchor.constraint(equalTo: rightPanel.centerYAnchor, constant: -20),

            rustLabel.centerXAnchor.constraint(equalTo: rightPanel.centerXAnchor),
            rustLabel.topAnchor.constraint(equalTo: detailLabel.bottomAnchor, constant: 20),
            rustLabel.leadingAnchor.constraint(
                greaterThanOrEqualTo: rightPanel.leadingAnchor, constant: 10),
            rustLabel.trailingAnchor.constraint(
                lessThanOrEqualTo: rightPanel.trailingAnchor, constant: -10),
        ])

        // Set minimum and maximum widths for panels
        leftPanel.widthAnchor.constraint(greaterThanOrEqualToConstant: 500).isActive = true
        rightPanel.widthAnchor.constraint(greaterThanOrEqualToConstant: 200).isActive = true
        rightPanel.widthAnchor.constraint(lessThanOrEqualToConstant: 400).isActive = true

        // Set initial split position (approximately 70% left, 30% right)
        splitView.setPosition(700, ofDividerAt: 0)
    }
}  // Create a delegate to handle the application's lifecycle events
class AppDelegate: NSObject, NSApplicationDelegate {
    var window: NSWindow!

    func applicationDidFinishLaunching(_ aNotification: Notification) {
        // Create the menu bar
        let mainMenu = NSMenu()
        NSApp.mainMenu = mainMenu

        // Create the application menu
        let appMenuItem = NSMenuItem()
        mainMenu.addItem(appMenuItem)

        let appMenu = NSMenu()
        appMenuItem.submenu = appMenu

        // Add a "Quit" item
        let quitItem = NSMenuItem(
            title: "Quit Piqopiqo", action: #selector(NSApplication.terminate(_:)),
            keyEquivalent: "q")
        appMenu.addItem(quitItem)

        // Get screen dimensions for maximized window (minus menu bar and dock)
        guard let screen = NSScreen.main else { return }
        let screenFrame = screen.visibleFrame  // This excludes the menu bar and dock

        // Create the window to fill the available screen space
        window = NSWindow(
            contentRect: screenFrame,
            styleMask: [.titled, .closable, .miniaturizable, .resizable],
            backing: .buffered, defer: false)
        window.title = "Piqopiqo Photo Browser"
        window.setFrameAutosaveName("Main Window")
        window.minSize = NSSize(width: 800, height: 600)

        // Use our custom AppKit view instead of SwiftUI
        window.contentView = MainView()

        // Set the window frame to fill the visible screen area
        window.setFrame(screenFrame, display: true)

        window.makeKeyAndOrderFront(nil)

        // Force the application to the foreground
        NSApp.activate(ignoringOtherApps: true)
    }

    func applicationWillTerminate(_ aNotification: Notification) {
        // Insert code here to tear down your application
    }

    func applicationShouldTerminateAfterLastWindowClosed(_ sender: NSApplication) -> Bool {
        return true
    }
}

// Manually create and run the application
let delegate = AppDelegate()
NSApplication.shared.delegate = delegate

// Set the activation policy to make this a regular app
NSApp.setActivationPolicy(.regular)

NSApplication.shared.run()
