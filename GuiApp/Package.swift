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
    dependencies: [],
    targets: [
        .systemLibrary(
            name: "core_libFFI",
            path: "Sources/UniffiBindings",
            pkgConfig: nil,
            providers: []
        ),
        .target(
            name: "UniffiBindings",
            dependencies: ["core_libFFI"],
            path: "Sources/UniffiBindings",
            linkerSettings: [
                .linkedLibrary("core_lib"),
                // Link against the release build of the Rust library
                .unsafeFlags(["-L", "../CoreLib/target/release"], .when(configuration: .release)),
                // Link against the debug build of the Rust library
                .unsafeFlags(["-L", "../CoreLib/target/debug"], .when(configuration: .debug)),
            ]
        ),
        .executableTarget(
            name: "GuiApp",
            dependencies: ["UniffiBindings"],
            path: "Sources/App",
            resources: [.process("Resources")]
        ),
    ]
)
