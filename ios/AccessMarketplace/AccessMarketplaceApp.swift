// AccessMarketplaceApp.swift
// Entry point — section 41: Swift, SwiftUI, async/await, DI.
import SwiftUI

@main
struct AccessMarketplaceApp: App {
    @StateObject private var auth = AuthManager()
    @StateObject private var appModel = AppModel()

    var body: some Scene {
        WindowGroup {
            RootView()
                .environmentObject(auth)
                .environmentObject(appModel)
        }
    }
}

struct RootView: View {
    @EnvironmentObject var auth: AuthManager

    var body: some View {
        if auth.isAuthenticated {
            MainTabView()
        } else {
            LoginView()
        }
    }
}

struct MainTabView: View {
    var body: some View {
        TabView {
            MarketplaceView()
                .tabItem { Label("Marketplace", systemImage: "square.grid.2x2") }
            MyAccessView()
                .tabItem { Label("My Access", systemImage: "ticket") }
            ScannerView()
                .tabItem { Label("Check-in", systemImage: "qrcode.viewfinder") }
            ProfileView()
                .tabItem { Label("Profile", systemImage: "person") }
        }
    }
}
