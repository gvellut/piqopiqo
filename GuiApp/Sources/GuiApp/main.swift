import SwiftUI

struct ContentView: View {
    var body: some View {
        Text("Hello from Swift")
            .frame(minWidth: 400, minHeight: 300)
    }
}

@main
struct GuiApp: App {
    var body: some Scene {
        WindowGroup {
            ContentView()
        }
    }
}
