import Foundation

/// Hubs this device connected to, newest first, kept in UserDefaults.
struct HubRecents {
    static let key = "handover.recentHubs"
    static let limit = 6

    let defaults: UserDefaults

    func load() -> [HubURL] {
        guard let data = defaults.data(forKey: Self.key),
              let saved = try? JSONDecoder().decode([String].self, from: data) else { return [] }
        return Self.unique(saved.compactMap(HubURL.init(parsing:)))
    }

    func save(_ hubs: [HubURL]) {
        let strings = Self.unique(hubs).prefix(Self.limit).map(\.base.absoluteString)
        defaults.set(try? JSONEncoder().encode(Array(strings)), forKey: Self.key)
    }

    /// `hub` moved to the front.
    static func adding(_ hub: HubURL, to list: [HubURL]) -> [HubURL] {
        Array(unique([hub] + list).prefix(limit))
    }

    private static func unique(_ list: [HubURL]) -> [HubURL] {
        var seen = Set<HubURL>()
        return list.filter { seen.insert($0).inserted }
    }
}
