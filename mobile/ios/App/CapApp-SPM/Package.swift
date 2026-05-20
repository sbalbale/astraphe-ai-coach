// swift-tools-version: 5.9
import PackageDescription

// DO NOT MODIFY THIS FILE - managed by Capacitor CLI commands
let package = Package(
    name: "CapApp-SPM",
    platforms: [.iOS(.v15)],
    products: [
        .library(
            name: "CapApp-SPM",
            targets: ["CapApp-SPM"])
    ],
    dependencies: [
        .package(url: "https://github.com/ionic-team/capacitor-swift-pm.git", exact: "8.3.1"),
        .package(name: "CapacitorApp", path: "..\..\..\node_modules\.pnpm\@capacitor+app@8.1.0_@capacitor+core@8.3.1\node_modules\@capacitor\app"),
        .package(name: "CapacitorPushNotifications", path: "..\..\..\node_modules\.pnpm\@capacitor+push-notifications@8.1.0_@capacitor+core@8.3.1\node_modules\@capacitor\push-notifications"),
        .package(name: "CapacitorBackgroundRunner", path: "..\..\..\node_modules\.pnpm\@capacitor+background-runner@3.0.0_@capacitor+core@8.3.1\node_modules\@capacitor\background-runner"),
        .package(name: "CapacitorBrowser", path: "..\..\..\node_modules\.pnpm\@capacitor+browser@8.0.3_@capacitor+core@8.3.1\node_modules\@capacitor\browser"),
        .package(name: "CapacitorPreferences", path: "..\..\..\node_modules\.pnpm\@capacitor+preferences@8.0.1_@capacitor+core@8.3.1\node_modules\@capacitor\preferences"),
        .package(name: "IntervalHealthCapacitorHealth", path: "..\..\..\node_modules\.pnpm\@interval-health+capacitor-_0e6f401dd0645823638ff816a784e627\node_modules\@interval-health\capacitor-health")
    ],
    targets: [
        .target(
            name: "CapApp-SPM",
            dependencies: [
                .product(name: "Capacitor", package: "capacitor-swift-pm"),
                .product(name: "Cordova", package: "capacitor-swift-pm"),
                .product(name: "CapacitorApp", package: "CapacitorApp"),
                .product(name: "CapacitorPushNotifications", package: "CapacitorPushNotifications"),
                .product(name: "CapacitorBackgroundRunner", package: "CapacitorBackgroundRunner"),
                .product(name: "CapacitorBrowser", package: "CapacitorBrowser"),
                .product(name: "CapacitorPreferences", package: "CapacitorPreferences"),
                .product(name: "IntervalHealthCapacitorHealth", package: "IntervalHealthCapacitorHealth")
            ]
        )
    ]
)
