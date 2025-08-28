import RustBridge
import SwiftUI

struct ContentView: View {
    var body: some View {
        VStack {
            Text("Piqopiqo Photo Browser")
                .font(.title)
                .padding()

            Text("Rust says: \(RustFFI.getGreetingFromRust())")
                .font(.body)
                .padding()
                .background(Color.gray.opacity(0.1))
                .cornerRadius(8)
        }
        .frame(minWidth: 500, minHeight: 400)
        .background(Color.white)
    }
}
