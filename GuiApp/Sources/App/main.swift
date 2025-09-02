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
}

let delegate = AppDelegate()
NSApplication.shared.delegate = delegate
NSApplication.shared.run()
