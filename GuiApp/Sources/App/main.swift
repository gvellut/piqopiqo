import AppKit
import UniffiBindings

class AppDelegate: NSObject, NSApplicationDelegate {
    var window: NSWindow!
    private var mainView: MainView!

    private func buildMainMenu() {
        let mainMenu = NSMenu()
        let appItem = NSMenuItem()
        mainMenu.addItem(appItem)

        let appMenu = NSMenu()
        let appName = "Piqopiqo"

        appMenu.addItem(
            withTitle: "About \(appName)",
            action: #selector(NSApplication.orderFrontStandardAboutPanel(_:)),
            keyEquivalent: "")
        appMenu.addItem(NSMenuItem.separator())
        appMenu.addItem(
            withTitle: "Quit \(appName)",
            action: #selector(NSApplication.terminate(_:)),
            keyEquivalent: "q")

        appItem.submenu = appMenu

        // File menu
        let fileMenuItem = NSMenuItem()
        fileMenuItem.submenu = NSMenu(title: "File")
        let openFolderItem = NSMenuItem(
            title: "Open Folder...", action: #selector(openFolder(_:)), keyEquivalent: "o")
        openFolderItem.target = self
        fileMenuItem.submenu?.addItem(openFolderItem)
        mainMenu.addItem(fileMenuItem)

        NSApp.mainMenu = mainMenu
    }

    func applicationDidFinishLaunching(_ notification: Notification) {
        buildMainMenu()

        let screenFrame =
            NSScreen.main?.visibleFrame ?? NSRect(x: 200, y: 200, width: 1200, height: 800)

        let defaultRect = NSRect(
            x: screenFrame.origin.x,
            y: screenFrame.origin.y,
            width: min(screenFrame.width, 1600),
            height: min(screenFrame.height, 1000))

        window = NSWindow(
            contentRect: defaultRect,
            styleMask: [.titled, .closable, .miniaturizable, .resizable],
            backing: .buffered,
            defer: false)

        window.title = "Piqopiqo Photo Browser"
        window.minSize = NSSize(width: 900, height: 600)
        window.setFrameAutosaveName("MainWindow")
        _ = window.setFrameUsingName("MainWindow")  // ignore result; defaultRect already set

        mainView = MainView()
        window.contentView = mainView
        window.makeKeyAndOrderFront(nil)
        NSApp.activate(ignoringOtherApps: true)

        // Defer restoration until layout pass is done.
        DispatchQueue.main.async { [weak self] in
            self?.mainView.restoreOrInitializeDivider()
        }
    }

    func applicationShouldTerminateAfterLastWindowClosed(_ sender: NSApplication) -> Bool {
        true
    }

    @objc private func openFolder(_ sender: NSMenuItem) {
        openFolderDialog()
    }

    private func openFolderDialog() {
        let openPanel = NSOpenPanel()
        openPanel.canChooseFiles = false
        openPanel.canChooseDirectories = true
        openPanel.allowsMultipleSelection = false
        openPanel.canCreateDirectories = false  // Ensure folder must exist

        // Create accessory view with recursive checkbox
        let accessoryView = NSView(frame: NSRect(x: 0, y: 0, width: 200, height: 40))
        let checkbox = NSButton(checkboxWithTitle: "Recursive", target: nil, action: nil)
        checkbox.frame = NSRect(x: 10, y: 10, width: 180, height: 20)
        accessoryView.addSubview(checkbox)
        openPanel.accessoryView = accessoryView

        openPanel.begin { [weak self] response in
            if response == .OK, let url = openPanel.url {
                let isRecursive = checkbox.state == .on
                // Pass to CoreLib (Rust) for processing
                self?.handleFolderSelection(url: url, recursive: isRecursive)
            }
        }
    }

    private func handleFolderSelection(url: URL, recursive: Bool) {
        // Call Rust function via UniffiBindings to process the folder
        // Example: CoreLib.openFolder(path: url.path, recursive: recursive)
        // Update UI state as needed (e.g., notify MainView or a view model)
        print("Selected folder: \(url.path), Recursive: \(recursive)")
    }
}

let delegate = AppDelegate()
NSApplication.shared.delegate = delegate
NSApplication.shared.run()
