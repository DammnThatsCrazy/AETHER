// swift-tools-version: 5.9
// AetherSDK 8.12.0

import PackageDescription

let package = Package(
    name: "AetherSDK",
    platforms: [
        .iOS(.v14)
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
            path: "Sources/AetherSDK",
            resources: [
                .copy("PrivacyInfo.xcprivacy")
            ]
        ),
        .testTarget(
            name: "AetherSDKTests",
            dependencies: ["AetherSDK"],
            path: "Tests/AetherSDKTests"
        ),
    ]
)
