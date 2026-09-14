// AuthManager.swift — single authentication layer (section 41).
import Foundation
import SwiftUI

@MainActor
final class AuthManager: ObservableObject {
    @Published var isAuthenticated = false
    @Published var user: UserDTO?
    @Published var error: String?

    private let keychainTokenKey = "am.access.token"

    init() {
        if let token = Keychain.get(keychainTokenKey) {
            APIClient.shared.token = token
            isAuthenticated = true
            Task { await loadMe() }
        }
    }

    func login(email: String, password: String) async {
        do {
            let body = ["email": email, "password": password]
            let dto: TokenDTO = try await APIClient.shared.request("POST", "/auth/login", body: body)
            apply(dto)
        } catch {
            self.error = (error as? LocalizedError)?.errorDescription ?? "Login failed"
        }
    }

    func register(email: String, password: String, name: String) async {
        do {
            let body = ["email": email, "password": password, "name": name]
            let dto: TokenDTO = try await APIClient.shared.request("POST", "/auth/register", body: body)
            apply(dto)
        } catch {
            self.error = (error as? LocalizedError)?.errorDescription ?? "Registration failed"
        }
    }

    private func apply(_ dto: TokenDTO) {
        APIClient.shared.token = dto.accessToken
        Keychain.set(keychainTokenKey, dto.accessToken)
        user = dto.user
        isAuthenticated = true
        error = nil
    }

    func loadMe() async {
        do {
            user = try await APIClient.shared.request("GET", "/users/me", as: UserDTO.self)
        } catch APIError.unauthorized {
            logout()
        } catch {}
    }

    func logout() {
        Keychain.delete(keychainTokenKey)
        APIClient.shared.token = nil
        isAuthenticated = false
        user = nil
    }
}

enum Keychain {
    static func set(_ key: String, _ value: String) {
        let data = Data(value.utf8)
        let query: [String: Any] = [
            kSecClass as String: kSecClassGenericPassword,
            kSecAttrAccount as String: key,
            // device-only, available after first unlock — the token must not
            // be restored onto other devices
            kSecAttrAccessible as String: kSecAttrAccessibleAfterFirstUnlockThisDeviceOnly,
        ]
        SecItemDelete(query as CFDictionary)
        var attrs = query
        attrs[kSecValueData as String] = data
        SecItemAdd(attrs as CFDictionary, nil)
    }

    static func get(_ key: String) -> String? {
        let query: [String: Any] = [
            kSecClass as String: kSecClassGenericPassword,
            kSecAttrAccount as String: key,
            kSecReturnData as String: true,
        ]
        var item: CFTypeRef?
        guard SecItemCopyMatching(query as CFDictionary, &item) == errSecSuccess,
              let data = item as? Data else { return nil }
        return String(data: data, encoding: .utf8)
    }

    static func delete(_ key: String) {
        let query: [String: Any] = [
            kSecClass as String: kSecClassGenericPassword,
            kSecAttrAccount as String: key,
        ]
        SecItemDelete(query as CFDictionary)
    }
}
