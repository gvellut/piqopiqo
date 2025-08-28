import RustBridge

enum RustFFI {
    static func getGreetingFromRust() -> String {
        let cStringPointer = hello_from_rust()
        if let cString = cStringPointer {
            return String(cString: cString)
        } else {
            return "Error: received null pointer from Rust"
        }
    }
}
