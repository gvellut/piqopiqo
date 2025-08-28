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
        .executableTarget(
            name: "GuiApp",
            path: "Sources"
        )
    ]
)
