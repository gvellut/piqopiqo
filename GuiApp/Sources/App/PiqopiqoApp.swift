import RustBridge
import SwiftUI

@main
struct PiqopiqoApp: App {
    var body: some Scene {
        WindowGroup {
            ContentView()
        }
        .windowStyle(.titleBar)
        .windowToolbarStyle(.unified)
        .commands {
            CommandGroup(replacing: .appInfo) {
                Button("About Piqopiqo") {
                    // About dialog
                }
            }
        }
    }
}
