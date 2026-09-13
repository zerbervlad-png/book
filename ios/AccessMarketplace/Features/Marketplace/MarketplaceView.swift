// MarketplaceView.swift — sections 20, 21, 35, 45, 51.
// The main screen is a universal marketplace, not "queues".
import SwiftUI

@MainActor
final class MarketplaceViewModel: ObservableObject {
    @Published var items: [MarketplaceItemDTO] = []
    @Published var listings: [MarketplaceItemDTO] = []
    @Published var query = ""
    @Published var onlyVerified = false
    @Published var error: String?
    private var searchTask: Task<Void, Never>?

    func search() async {
        var path = "marketplace/search?limit=50"
        if !query.isEmpty { path += "&q=\(query.addingPercentEncoding(withAllowedCharacters: .urlQueryAllowed) ?? "")" }
        if onlyVerified { path += "&verified_only=true" }
        do {
            items = try await APIClient.shared.request("GET", path, as: [MarketplaceItemDTO].self)
            listings = (try? await APIClient.shared.request(
                "GET", "transfers/listings", as: [MarketplaceItemDTO].self)) ?? []
            error = nil
        } catch {
            self.error = (error as? LocalizedError)?.errorDescription ?? "Search failed"
        }
    }

    /// Debounced search so typing doesn't fire a request per keystroke.
    func searchDebounced() {
        searchTask?.cancel()
        searchTask = Task {
            try? await Task.sleep(for: .milliseconds(350))
            guard !Task.isCancelled else { return }
            await search()
        }
    }

    func cancelPendingSearch() {
        searchTask?.cancel()
    }
}

struct MarketplaceView: View {
    @StateObject private var model = MarketplaceViewModel()
    @EnvironmentObject var appModel: AppModel

    var body: some View {
        NavigationStack {
            List {
                Section {
                    Toggle("Verified only", isOn: $model.onlyVerified)
                }
                if !model.listings.isEmpty {
                    Section("Transfer offers") {
                        ForEach(model.listings) { item in
                            NavigationLink(value: item) {
                                ListingRow(item: item)
                            }
                        }
                    }
                }
                Section("Discover") {
                    ForEach(model.items) { item in
                        if let event = item.event {
                            NavigationLink(value: item) {
                                EventRow(event: event, resource: item.resource)
                            }
                        }
                    }
                }
                if let error = model.error {
                    Text(error).foregroundStyle(.red).font(.footnote)
                }
            }
            .searchable(text: $model.query)
            .navigationTitle("Marketplace")
            .navigationDestination(for: MarketplaceItemDTO.self) { item in
                EventDetailView(item: item)
            }
            .task { await model.search() }
            .refreshable { await model.search() }
            .onDisappear { model.cancelPendingSearch() }
            .onChange(of: model.query) { _, _ in model.searchDebounced() }
            .onChange(of: model.onlyVerified) { _, _ in Task { await model.search() } }
        }
    }
}

struct ListingRow: View {
    let item: MarketplaceItemDTO

    var body: some View {
        VStack(alignment: .leading, spacing: 4) {
            Text(item.event?.title ?? "Offer")
                .font(.headline)
            if let right = item.listing?.accessRight {
                Label(right.kind == "QUEUE_POSITION"
                      ? "Position #\(right.position ?? 0)"
                      : right.kind.capitalized,
                      systemImage: "arrow.triangle.2.circlepath")
            }
            if let price = item.listing?.price {
                Text("\(price) ₽").font(.subheadline).foregroundStyle(.secondary)
            }
        }
    }
}

struct EventRow: View {
    let event: EventDTO
    let resource: ResourceDTO?

    var body: some View {
        VStack(alignment: .leading, spacing: 4) {
            HStack {
                Text(event.title).font(.headline)
                if event.verificationStatus.contains("VERIFIED")
                    || event.verificationStatus == "OFFICIAL" {
                    Image(systemName: "checkmark.seal.fill")
                        .foregroundStyle(.green).font(.caption)
                }
            }
            if let startsAt = event.startsAt {
                Text(startsAt.formatted(date: .abbreviated, time: .shortened))
                    .font(.subheadline).foregroundStyle(.secondary)
            }
            if let city = event.city, !city.isEmpty {
                Label(city, systemImage: "mappin.and.ellipse")
                    .font(.footnote).foregroundStyle(.secondary)
            }
            if let resource {
                // 79: dynamic UX from resourceType
                Text(actionVerb(for: resource.type))
                    .font(.caption.bold())
                    .padding(.horizontal, 8).padding(.vertical, 4)
                    .background(Capsule().fill(.tint.opacity(0.15)))
            }
        }
    }

    private func actionVerb(for type: String) -> String {
        switch type {
        case "PHYSICAL_QUEUE", "EVENT_QUEUE": return "Join queue"
        case "WAITLIST": return "Join waitlist"
        case "TICKET": return "Buy ticket"
        case "TIME_SLOT": return "Book slot"
        case "EVENT_REGISTRATION": return "Register"
        default: return "Get access"
        }
    }
}
