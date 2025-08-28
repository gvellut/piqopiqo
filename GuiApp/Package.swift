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
            name: "CBindings",
            path: "Sources/CBindings",
            pkgConfig: nil,
            providers: []
        ),
        .target(
            name: "RustBridge",
            dependencies: ["CBindings"],
            path: "Sources/RustBridge",
            linkerSettings: [
                .linkedLibrary("core_lib"),
                .unsafeFlags(["-L", "../CoreLib/target/debug"])
            ]
        ),
        .executableTarget(
            name: "GuiApp",
            dependencies: ["RustBridge"],
            path: "Sources/App"
        )
    ]
)
