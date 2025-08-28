import AppKit
import SwiftUI

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

        window.contentView = NSHostingView(rootView: ContentView())

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
