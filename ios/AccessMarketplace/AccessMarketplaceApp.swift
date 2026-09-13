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
                .tint(.indigo)
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
                .tabItem { Label("Маркет", systemImage: "square.grid.2x2") }
            MyAccessView()
                .tabItem { Label("Мой доступ", systemImage: "ticket") }
            ScannerView()
                .tabItem { Label("Вход", systemImage: "qrcode.viewfinder") }
            ProfileView()
                .tabItem { Label("Профиль", systemImage: "person") }
        }
    }
}
