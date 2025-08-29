import AppKit
import RustBridge

// Custom AppKit view to replace the SwiftUI ContentView
class MainView: NSView {
    private var titleLabel: NSTextField!
    private var rustLabel: NSTextField!

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
        layer?.backgroundColor = NSColor.white.cgColor

        // Title label
        titleLabel = NSTextField(labelWithString: "Piqopiqo Photo Browser")
        titleLabel.font = NSFont.systemFont(ofSize: 24, weight: .bold)
        titleLabel.alignment = .center
        titleLabel.translatesAutoresizingMaskIntoConstraints = false
        addSubview(titleLabel)

        // Rust message label
        let rustMessage = RustFFI.getGreetingFromRust()
        rustLabel = NSTextField(labelWithString: "Rust says: \(rustMessage)")
        rustLabel.font = NSFont.systemFont(ofSize: 16)
        rustLabel.alignment = .center
        rustLabel.backgroundColor = NSColor.lightGray.withAlphaComponent(0.1)
        rustLabel.isBordered = false
        rustLabel.isEditable = false
        rustLabel.translatesAutoresizingMaskIntoConstraints = false
        addSubview(rustLabel)

        // Set up constraints
        NSLayoutConstraint.activate([
            // Title label constraints
            titleLabel.centerXAnchor.constraint(equalTo: centerXAnchor),
            titleLabel.topAnchor.constraint(equalTo: topAnchor, constant: 50),
            titleLabel.leadingAnchor.constraint(greaterThanOrEqualTo: leadingAnchor, constant: 20),
            titleLabel.trailingAnchor.constraint(lessThanOrEqualTo: trailingAnchor, constant: -20),

            // Rust label constraints
            rustLabel.centerXAnchor.constraint(equalTo: centerXAnchor),
            rustLabel.topAnchor.constraint(equalTo: titleLabel.bottomAnchor, constant: 30),
            rustLabel.leadingAnchor.constraint(greaterThanOrEqualTo: leadingAnchor, constant: 20),
            rustLabel.trailingAnchor.constraint(lessThanOrEqualTo: trailingAnchor, constant: -20),
        ])
    }
}

// Create a delegate to handle the application's lifecycle events
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

        // Create the window and set its content
        window = NSWindow(
            contentRect: NSRect(x: 0, y: 0, width: 500, height: 400),
            styleMask: [.titled, .closable, .miniaturizable, .resizable],
            backing: .buffered, defer: false)
        window.center()
        window.setFrameAutosaveName("Main Window")

        // Use our custom AppKit view instead of SwiftUI
        window.contentView = MainView()

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
