# piqopiqo


in CoreLib : 
cargo run -p uniffi-bindgen generate --language swift --out-dir ../GuiApp/Sources/UniffiBindings --library target/release/libcore_lib.dylib 

## Codesign

### Create a Certificate:

    Open the Keychain Access application on your Mac.

    From the menu bar, go to Keychain Access > Certificate Assistant > Create a Certificate....

    Give the certificate a recognizable name (e.g., "My Swift Dev Cert").

    Set Identity Type to Self-Signed Root.

    Set Certificate Type to Code Signing.

    Complete the creation process.

Update Your Makefile: Modify your codesign command to use this new certificate:
    
@codesign --force --deep --sign "My Swift Dev Cert" $(APP_BUNDLE)

### Authorize codesign

    Open Keychain Access: You can find it in /Applications/Utilities/.

    Locate Your Certificate: In the "Category" section on the left, select "My Certificates". Find your self-signed certificate, which will be named something like "My Swiudt Dev Cert".

    Find the Private Key: Click the triangle next to your certificate to reveal the associated private key.

    Get Info on the Private Key: Right-click (or Control-click) on the private key and select "Get Info".

    Modify Access Control: In the window that appears, click on the "Access Control" tab.[1][2]

    Grant Access: You have two primary options:

        Allow all applications to access this item: This is a less secure option, as it will allow any application to use this key without prompting.[2][3]

        Add codesign to the list of allowed applications: Click the "+" button, and then navigate to /usr/bin/codesign to add it to the list of applications that can access this key. You might need to use the key combination Command+Shift+G to enter the path directly.

    Save Changes: Click "Save Changes" and enter your login password when prompted to confirm the modifications.