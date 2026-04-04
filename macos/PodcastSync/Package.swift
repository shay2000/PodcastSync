// swift-tools-version: 5.9
import PackageDescription

let package = Package(
    name: "PodcastSync",
    platforms: [.macOS(.v13)],
    targets: [
        .executableTarget(
            name: "PodcastSync",
            path: "Sources"
        ),
    ]
)
