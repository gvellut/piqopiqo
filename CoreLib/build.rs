use std::env;

fn main() {
    let crate_dir = env::var("CARGO_MANIFEST_DIR").unwrap();

    // Inform rustc that we are using a custom `cbindgen` cfg flag.
    // This will prevent warnings about an unknown cfg flag.
    println!("cargo:rustc-check-cfg=cfg(cbindgen)");
    println!("cargo:rerun-if-changed=src/lib.rs");
    println!("cargo:rerun-if-changed=cbindgen.toml");

    // Load the configuration from the toml file.
    let mut config =
        cbindgen::Config::from_file("cbindgen.toml").expect("Failed to read cbindgen.toml");

    // Tell cbindgen's parser to act as if `--cfg cbindgen` was passed.
    // This is the correct way for modern cbindgen versions.
    config
        .parse
        .expand
        .crates
        .push("--cfg=cbindgen".to_string());

    // Generate the bindings.
    cbindgen::Builder::new()
        .with_crate(&crate_dir)
        .with_config(config)
        .generate()
        .expect("Unable to generate bindings")
        .write_to_file("core_lib.h");
}
