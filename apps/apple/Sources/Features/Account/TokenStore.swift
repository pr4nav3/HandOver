import Foundation
import Security

/// The hub's bearer token, one per hub, in the Keychain. Only this app's own generic-password items under
/// `service` are read or written; nothing else in the Keychain is touched.
struct TokenStore: Sendable {
    static let appService = "com.soham109.handover.hub-token"

    let service: String

    init(service: String = TokenStore.appService) {
        self.service = service
    }

    func token(for hub: HubURL) -> String? {
        var query = base(account: account(hub))
        query[kSecReturnData as String] = true
        query[kSecMatchLimit as String] = kSecMatchLimitOne
        var result: CFTypeRef?
        guard SecItemCopyMatching(query as CFDictionary, &result) == errSecSuccess,
              let data = result as? Data, let token = String(data: data, encoding: .utf8), !token.isEmpty else { return nil }
        return token
    }

    /// Saves or replaces the token for this hub. False when the Keychain refused it.
    @discardableResult
    func save(_ token: String, for hub: HubURL) -> Bool {
        let data = Data(token.utf8)
        let query = base(account: account(hub))
        let update: [String: Any] = [kSecValueData as String: data]
        let status = SecItemUpdate(query as CFDictionary, update as CFDictionary)
        if status == errSecSuccess { return true }
        guard status == errSecItemNotFound else { return false }
        var add = query
        add[kSecValueData as String] = data
        add[kSecAttrAccessible as String] = kSecAttrAccessibleAfterFirstUnlockThisDeviceOnly
        add[kSecAttrLabel as String] = "HandOver hub sign-in"
        return SecItemAdd(add as CFDictionary, nil) == errSecSuccess
    }

    func delete(for hub: HubURL) {
        SecItemDelete(base(account: account(hub)) as CFDictionary)
    }

    /// Removes every token this store saved (its own service only).
    func deleteAll() {
        let query: [String: Any] = [kSecClass as String: kSecClassGenericPassword, kSecAttrService as String: service]
        SecItemDelete(query as CFDictionary)
    }

    private func account(_ hub: HubURL) -> String { hub.base.absoluteString }

    private func base(account: String) -> [String: Any] {
        [kSecClass as String: kSecClassGenericPassword,
         kSecAttrService as String: service,
         kSecAttrAccount as String: account]
    }
}
