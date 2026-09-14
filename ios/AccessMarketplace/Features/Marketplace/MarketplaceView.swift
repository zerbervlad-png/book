// MarketplaceView.swift — главный экран: универсальный маркет доступа.
import SwiftUI

@MainActor
final class MarketplaceViewModel: ObservableObject {
    @Published var items: [MarketplaceItemDTO] = []
    @Published var listings: [MarketplaceItemDTO] = []
    @Published var query = ""
    @Published var onlyVerified = false
    @Published var category = "ALL"
    @Published var showCreateQueue = false
    @Published var error: String?
    @Published var isLoading = false
    private var searchTask: Task<Void, Never>?

    static let categories: [(id: String, title: String)] = [
        ("ALL", "Все"), ("GAS_STATION", "АЗС"), ("CONCERT", "Концерты"),
        ("FESTIVAL", "Фестивали"), ("CLUB", "Клубы"), ("RESTAURANT", "Рестораны"),
        ("STORE", "Магазины"), ("CONFERENCE", "Конференции"), ("OTHER", "Другое"),
    ]

    func search() async {
        var path = "marketplace/search?limit=50"
        if !query.isEmpty { path += "&q=\(APIClient.encodeQueryValue(query))" }
        if onlyVerified { path += "&verified_only=true" }
        if category != "ALL" { path += "&category=\(category)" }
        isLoading = true
        defer { isLoading = false }
        do {
            items = try await APIClient.shared.request("GET", path, as: [MarketplaceItemDTO].self)
            // предложения с котировкой комиссии (ТЗ 2, 9: покупатель видит стоимость)
            listings = (try? await APIClient.shared.request(
                "GET", "marketplace/listings?limit=50", as: [MarketplaceItemDTO].self)) ?? []
            error = nil
        } catch {
            self.error = (error as? LocalizedError)?.errorDescription ?? "Не удалось загрузить маркет"
        }
    }

    /// Дебаунс, чтобы поиск не стрелял запросом на каждую букву.
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
                    Toggle(isOn: $model.onlyVerified) {
                        Label("Только проверенные", systemImage: "checkmark.seal")
                            .font(.subheadline)
                    }
                    .tint(.green)
                    Picker("Категория", selection: $model.category) {
                        ForEach(MarketplaceViewModel.categories, id: \.id) { item in
                            Text(item.title).tag(item.id)
                        }
                    }
                    .font(.subheadline)
                }
                if !model.listings.isEmpty {
                    Section {
                        ForEach(model.listings) { item in
                            NavigationLink {
                                ListingDetailView(item: item)
                            } label: {
                                ListingRow(item: item)
                            }
                        }
                    } header: {
                        Label("Передают и продают", systemImage: "arrow.triangle.2.circlepath")
                    }
                }
                Section {
                    if model.items.isEmpty && !model.isLoading && model.error == nil {
                        ContentUnavailableView(
                            "Ничего не найдено",
                            systemImage: "magnifyingglass",
                            description: Text("Попробуйте изменить запрос или сбросить фильтры"))
                            .frame(maxWidth: .infinity)
                            .listRowBackground(Color.clear)
                    }
                    ForEach(model.items) { item in
                        if let event = item.event {
                            NavigationLink {
                                EventDetailView(item: item)
                            } label: {
                                EventRow(event: event, resource: item.resource)
                            }
                        }
                    }
                } header: {
                    Label("События", systemImage: "calendar")
                }
                if model.isLoading && model.items.isEmpty {
                    Section {
                        HStack {
                            Spacer()
                            ProgressView("Загрузка…")
                            Spacer()
                        }
                    }
                }
                if let error = model.error {
                    Section {
                        Label(error, systemImage: "wifi.exclamationmark")
                            .foregroundStyle(.red)
                            .font(.footnote)
                    }
                }
            }
            .searchable(text: $model.query, prompt: "Поиск: АЗС, концерт, бар, очередь…")
            .navigationTitle("Маркет")
            .toolbar {
                ToolbarItem(placement: .primaryAction) {
                    Button {
                        model.showCreateQueue = true
                    } label: {
                        Label("Создать очередь", systemImage: "plus")
                    }
                }
            }
            .sheet(isPresented: $model.showCreateQueue, onDismiss: {
                Task { await model.search() }
            }) {
                CreateQueueView()
            }
            .task { await model.search() }
            .refreshable { await model.search() }
            .onDisappear { model.cancelPendingSearch() }
            .onChange(of: model.query) { model.searchDebounced() }
            .onChange(of: model.onlyVerified) { Task { await model.search() } }
            .onChange(of: model.category) { Task { await model.search() } }
        }
    }
}

struct ListingRow: View {
    let item: MarketplaceItemDTO

    var body: some View {
        HStack(spacing: 12) {
            ZStack {
                RoundedRectangle(cornerRadius: 10)
                    .fill(LinearGradient(colors: [.orange, .pink],
                                         startPoint: .top, endPoint: .bottom))
                Image(systemName: "arrow.triangle.2.circlepath")
                    .font(.headline)
                    .foregroundStyle(.white)
            }
            .frame(width: 40, height: 40)
            .accessibilityHidden(true)
            VStack(alignment: .leading, spacing: 4) {
                Text(item.event?.title ?? "Предложение")
                    .font(.headline)
                if let right = item.listing?.accessRight {
                    Text(positionTitle(right))
                        .font(.caption)
                        .foregroundStyle(.secondary)
                }
            }
            Spacer()
            if let quote = item.quote, let price = quote.price {
                VStack(alignment: .trailing, spacing: 2) {
                    Text("\(price) ₽")
                        .font(.title3.bold())
                    if quote.feeAmount > 0 {
                        Text("к оплате \(quote.buyTotal ?? price) ₽ · комиссия \(quote.feeAmount) ₽")
                            .font(.caption2)
                            .foregroundStyle(.secondary)
                    }
                }
            } else if let price = item.listing?.price {
                Text("\(price) ₽")
                    .font(.title3.bold())
            } else {
                Text("Даром")
                    .font(.headline)
                    .foregroundStyle(.green)
            }
        }
        .padding(.vertical, 2)
    }

    private func positionTitle(_ right: AccessRightDTO) -> String {
        switch right.kind {
        case "QUEUE_POSITION": return "Позиция №\(right.position ?? 0)"
        case "TICKET": return "Билет"
        case "SLOT": return "Тайм-слот"
        default: return "Доступ"
        }
    }
}

struct EventRow: View {
    let event: EventDTO
    let resource: ResourceDTO?

    var body: some View {
        HStack(alignment: .top, spacing: 12) {
            ZStack {
                RoundedRectangle(cornerRadius: 10)
                    .fill(LinearGradient(colors: categoryGradient,
                                         startPoint: .top, endPoint: .bottom))
                Image(systemName: categoryIcon)
                    .font(.headline)
                    .foregroundStyle(.white)
            }
            .frame(width: 44, height: 44)
            .accessibilityHidden(true)
            VStack(alignment: .leading, spacing: 4) {
                HStack(spacing: 6) {
                    Text(event.title).font(.headline)
                    if isVerified {
                        Image(systemName: "checkmark.seal.fill")
                            .foregroundStyle(.green).font(.caption)
                    }
                }
                if let startsAt = event.startsAt {
                    Label(startsAt.formatted(
                        .dateTime.day().month().hour().minute()
                        .locale(Locale(identifier: "ru_RU"))),
                          systemImage: "clock")
                        .font(.caption).foregroundStyle(.secondary)
                }
                if let city = event.city, !city.isEmpty {
                    Label(city, systemImage: "mappin.and.ellipse")
                        .font(.caption).foregroundStyle(.secondary)
                }
                if let resource {
                    // динамический UX от типа ресурса (раздел 79 ТЗ)
                    Text(actionVerb(for: resource.type))
                        .font(.caption.bold())
                        .padding(.horizontal, 10).padding(.vertical, 5)
                        .foregroundStyle(.tint)
                        .background(Capsule().fill(.tint.opacity(0.12)))
                }
            }
        }
        .padding(.vertical, 2)
    }

    private var isVerified: Bool {
        event.verificationStatus.contains("VERIFIED")
            || event.verificationStatus == "OFFICIAL"
    }

    private var categoryIcon: String {
        switch event.category {
        case "CONCERT": return "music.note"
        case "FESTIVAL": return "music.note.list"
        case "SHOW": return "theatermasks"
        case "CONFERENCE": return "person.3"
        case "SPORT": return "sportscourt"
        case "RESTAURANT": return "fork.knife"
        case "GAS_STATION": return "fuelpump.fill"
        case "STORE": return "bag.fill"
        case "CLUB": return "speaker.wave.2.fill"
        case "SERVICE": return "wrench.and.screwdriver"
        case "GOVERNMENT": return "building.columns"
        default: return "sparkles"
        }
    }

    private var categoryGradient: [Color] {
        switch event.category {
        case "CONCERT": return [.pink, .purple]
        case "FESTIVAL": return [.purple, .orange]
        case "SHOW": return [.orange, .pink]
        case "CONFERENCE": return [.blue, .cyan]
        case "SPORT": return [.green, .teal]
        case "RESTAURANT": return [.orange, .yellow]
        case "GAS_STATION": return [.green, .blue]
        case "STORE": return [.teal, .indigo]
        case "CLUB": return [.indigo, .pink]
        case "SERVICE": return [.gray, .blue]
        case "GOVERNMENT": return [.blue, .gray]
        default: return [.indigo, .blue]
        }
    }

    private func actionVerb(for type: String) -> String {
        switch type {
        case "PHYSICAL_QUEUE", "EVENT_QUEUE": return "Встать в очередь"
        case "WAITLIST": return "В лист ожидания"
        case "TICKET": return "Купить билет"
        case "TIME_SLOT": return "Забронировать слот"
        case "EVENT_REGISTRATION": return "Зарегистрироваться"
        default: return "Получить доступ"
        }
    }
}
