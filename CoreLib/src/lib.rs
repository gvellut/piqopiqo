//! Core library exposing C ABI for Swift interop.
use std::os::raw::c_char;

/// Returns a pointer to a null-terminated static C string "Hello from Rust!".
/// The string has static lifetime so no free function is required yet.
///
/// # Safety
/// The returned pointer is valid for the lifetime of the program and must not
/// be freed. It points to immutable memory containing a NUL-terminated string.
#[cfg(not(cbindgen))]
#[unsafe(no_mangle)]
#[cfg(cbindgen)]
#[no_mangle]
pub unsafe extern "C" fn hello_from_rust() -> *const c_char {
    // Explicitly include trailing NUL terminator
    static GREETING: &[u8] = b"Hello from Rust!\0";
    GREETING.as_ptr() as *const c_char
}

// Optional safe wrapper for internal Rust use
pub fn hello_from_rust_safe() -> &'static str {
    "Hello from Rust!"
}
