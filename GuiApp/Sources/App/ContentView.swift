import RustBridge
import SwiftUI

struct ContentView: View {
    var body: some View {
        Text(RustFFI.getGreetingFromRust())
            .frame(minWidth: 400, minHeight: 300)
    }
}
