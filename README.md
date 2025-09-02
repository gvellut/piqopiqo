# piqopiqo


in CoreLib : 
cargo run -p uniffi-bindgen generate --language swift --out-dir ../GuiApp/Sources/UniffiBindings --library target/release/libcore_lib.dylib 


Create a Certificate:

    Open the Keychain Access application on your Mac.

    From the menu bar, go to Keychain Access > Certificate Assistant > Create a Certificate....

    Give the certificate a recognizable name (e.g., "My Swift Dev Cert").

    Set Identity Type to Self-Signed Root.

    Set Certificate Type to Code Signing.

    Complete the creation process.

Update Your Makefile: Modify your codesign command to use this new certificate:
    
@codesign --force --deep --sign "My Swift Dev Cert" $(APP_BUNDLE)

  