// swift-tools-version: 5.9
// AetherSDK 8.7.1

import PackageDescription

let package = Package(
    name: "AetherSDK",
    platforms: [
        .iOS(.v14),
        .macOS(.v12)
    ],
    products: [
        .library(
            name: "AetherSDK",
            targets: ["AetherSDK"]
        ),
    ],
    targets: [
        .target(
            name: "AetherSDK",
            path: "Sources/AetherSDK"
        ),
        .testTarget(
            name: "AetherSDKTests",
            dependencies: ["AetherSDK"],
            path: "Tests/AetherSDKTests"
        ),
    ]
)
