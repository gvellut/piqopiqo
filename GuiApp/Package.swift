// swift-tools-version: 5.9
import PackageDescription

let package = Package(
    name: "GuiApp",
    platforms: [
        .macOS(.v14)
    ],
    products: [
        .executable(name: "GuiApp", targets: ["GuiApp"])
    ],
    dependencies: [
    ],
    targets: [
        .systemLibrary(
            name: "RustBridge",
            path: "Sources/GuiApp/RustBridge",
            pkgConfig: nil,
            providers: []
        ),
        .executableTarget(
            name: "GuiApp",
            dependencies: ["RustBridge"],
            path: "Sources/GuiApp"
        )
    ]
)
