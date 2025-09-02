//! Core library exposing uniffi bindings for Swift interop.

/// Returns a greeting message from Rust.
/// This function is exposed via uniffi and can be called from Swift.
pub fn hello_from_rust() -> String {
    "Hello from Rust!".to_string()
}

// Include the generated uniffi bindings
uniffi::include_scaffolding!("core_lib");
