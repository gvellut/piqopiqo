//! Core library exposing C ABI for Swift interop.
use std::os::raw::c_char;

/// The greeting message shared between the safe and unsafe functions.
/// It includes a NUL terminator for C-compatibility.
#[cfg_attr(cbindgen, cbindgen(skip))]
const GREETING: &[u8] = b"Hello from Rust!\0";

/// Returns a pointer to a null-terminated static C string "Hello from Rust!".
/// The string has static lifetime so no free function is required yet.
///
/// # Safety
/// The returned pointer is valid for the lifetime of the program and must not
/// be freed. It points to immutable memory containing a NUL-terminated string.
#[unsafe(no_mangle)]
pub unsafe extern "C" fn hello_from_rust() -> *const c_char {
    GREETING.as_ptr() as *const c_char
}

/// A safe, idiomatic Rust wrapper for the greeting functionality.
pub fn hello_from_rust_safe() -> &'static str {
    // The slice is created up to the byte before the NUL terminator.
    // This is safe because we defined the constant GREETING ourselves.
    std::str::from_utf8(&GREETING[..GREETING.len() - 1]).unwrap()
}
