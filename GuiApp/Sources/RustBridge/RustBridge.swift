import CRustCore

public enum RustFFI {
    public static func getGreetingFromRust() -> String {
        let cStringPointer = hello_from_rust()
        if let cString = cStringPointer { return String(cString: cString) }
        return "Error: received null pointer from Rust"
    }
}
