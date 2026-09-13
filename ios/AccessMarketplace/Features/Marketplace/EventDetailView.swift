// EventDetailView.swift — карточка события + динамический UX (раздел 79 ТЗ).
// UI строится из resourceType / accessModel / policies, присылаемых бэкендом.
import SwiftUI

@MainActor
final class EventDetailViewModel: ObservableObject {
    @Published var event: EventDTO
    @Published var resources: [ResourceDTO] = []
    @Published var availability: [Int: AvailabilityDTO] = [:]
    @Published var error: String?
    @Published var joinedMessage: String?

    init(event: EventDTO) {
        self.event = event
    }

    func load() async {
        do {
            resources = try await APIClient.shared.request(
                "GET", "events/\(event.id)/resources", as: [ResourceDTO].self)
            availability = await withTaskGroup(
                of: (Int, AvailabilityDTO?).self
            ) { group in
                for resource in resources {
                    group.addTask {
                        let av: AvailabilityDTO? = try? await APIClient.shared.request(
                            "GET", "resources/\(resource.id)/availability",
                            as: AvailabilityDTO.self)
                        return (resource.id, av)
                    }
                }
                var dict: [Int: AvailabilityDTO] = [:]
                for await (id, av) in group {
                    if let av { dict[id] = av }
                }
                return dict
            }
            error = nil
        } catch {
            self.error = (error as? LocalizedError)?.errorDescription ?? "Не удалось загрузить событие"
        }
    }

    /// Единая точка входа — бэкенд сам решает, что значит «получить доступ»
    /// для данного типа ресурса (разделы 80–83 ТЗ).
    func getAccess(to resource: ResourceDTO) async {
        do {
            switch resource.type {
            case "PHYSICAL_QUEUE", "EVENT_QUEUE":
                let result: QueueJoinResultDTO = try await APIClient.shared.request(
                    "POST", "queues/resources/\(resource.id)/join", body: EmptyBody(),
                    as: QueueJoinResultDTO.self)
                joinedMessage = result.accessRight.map { right in
                    right.position.map { "Вы №\($0) в очереди" } ?? "Вы в очереди — ждём жеребьёвки"
                } ?? "Вы в очереди — ждём жеребьёвки"
            case "WAITLIST":
                let entry: WaitlistEntryDTO = try await APIClient.shared.request(
                    "POST", "waitlists/resources/\(resource.id)/join", body: EmptyBody(),
                    as: WaitlistEntryDTO.self)
                joinedMessage = "Вы №\(entry.position) в листе ожидания"
            case "TICKET", "TIME_SLOT", "EVENT_REGISTRATION", "ACCESS_PASS":
                let reservation: ReservationDTO = try await APIClient.shared.request(
                    "POST", "/reservations", body: ["resource_id": resource.id],
                    as: ReservationDTO.self)
                let confirmed: ReservationDTO = try await APIClient.shared.request(
                    "POST", "/reservations/\(reservation.id)/confirm", body: EmptyBody(),
                    as: ReservationDTO.self)
                joinedMessage = "Готово — бронь подтверждена"
            default:
                joinedMessage = nil
            }
            error = nil
            await load()
        } catch {
            self.error = (error as? LocalizedError)?.errorDescription ?? "Не удалось получить доступ"
            joinedMessage = nil
        }
    }
}

struct EmptyBody: Codable {}

struct EventDetailView: View {
    @StateObject private var model: EventDetailViewModel
    @EnvironmentObject var appModel: AppModel
    let item: MarketplaceItemDTO

    init(item: MarketplaceItemDTO) {
        self.item = item
        _model = StateObject(wrappedValue: EventDetailViewModel(
            event: item.event ?? EventDTO.placeholder))
    }

    var body: some View {
        List {
            header
            if !model.resources.isEmpty {
                Section {
                    ForEach(model.resources) { resource in
                        ResourceRow(resource: resource,
                                    availability: model.availability[resource.id]) {
                            Task {
                                await model.getAccess(to: resource)
                                await appModel.reload()
                            }
                        }
                    }
                } header: {
                    Label("Способы получить доступ", systemImage: "key.horizontal")
                }
            }
            if let message = model.joinedMessage {
                Section {
                    Label(message, systemImage: "checkmark.circle.fill")
                        .foregroundStyle(.green)
                        .font(.headline)
                }
            }
            if let error = model.error {
                Section {
                    Label(error, systemImage: "exclamationmark.triangle.fill")
                        .foregroundStyle(.red)
                }
            }
        }
        .navigationTitle(model.event.title)
        .navigationBarTitleDisplayMode(.inline)
        .task { await model.load(); await appModel.reload() }
    }

    private var header: some View {
        Section {
            if let startsAt = model.event.startsAt {
                LabeledContent {
                    Text(startsAt.formatted(
                        date: .long, time: .shortened, locale: Locale(identifier: "ru_RU")))
                        .multilineTextAlignment(.trailing)
                } label: {
                    Label("Начало", systemImage: "clock")
                }
            }
            if let city = model.event.city, !city.isEmpty {
                LabeledContent { Text(city) } label: {
                    Label("Город", systemImage: "mappin.and.ellipse")
                }
            }
            if let organizer = model.event.organizer {
                LabeledContent { Text(organizer.name) } label: {
                    Label("Организатор", systemImage: "person.badge.shield.checkmark")
                }
            }
            LabeledContent { Text(statusTitle) } label: {
                Label("Статус", systemImage: "info.circle")
            }
            if !model.event.description.isEmpty {
                Text(model.event.description)
                    .font(.body)
                    .foregroundStyle(.secondary)
                    .padding(.top, 4)
            }
        }
    }

    private var statusTitle: String {
        switch model.event.verificationStatus {
        case "VERIFIED", "ORGANIZER_VERIFIED", "OFFICIAL": return "Проверено"
        default: return "На проверке"
        }
    }
}

struct ResourceRow: View {
    let resource: ResourceDTO
    let availability: AvailabilityDTO?
    let action: () -> Void

    var body: some View {
        VStack(alignment: .leading, spacing: 10) {
            HStack {
                VStack(alignment: .leading, spacing: 2) {
                    Text(resource.name).font(.headline)
                    if resource.priceBase > 0 {
                        Text("\(resource.priceBase) ₽")
                            .font(.subheadline)
                            .foregroundStyle(.secondary)
                    }
                }
                Spacer()
                Button(actionTitle, action: action)
                    .buttonStyle(.borderedProminent)
                    .disabled(!canJoin)
            }
            if let av = availability {
                // прогресс заполненности
                VStack(alignment: .leading, spacing: 4) {
                    ProgressView(value: Double(av.totalCapacity - av.available),
                                 total: Double(max(av.totalCapacity, 1)))
                        .tint(av.available > 0 ? .green : .red)
                    HStack(spacing: 12) {
                        Label("Свободно \(av.available)", systemImage: "checkmark.circle")
                        Label("В очереди \(av.inQueue)", systemImage: "person.2")
                    }
                    .font(.caption)
                    .foregroundStyle(.secondary)
                }
            }
            if !resource.isTransferable {
                Label("Передача запрещена организатором", systemImage: "lock.fill")
                    .font(.caption)
                    .foregroundStyle(.orange)
            }
        }
        .padding(.vertical, 4)
    }

    private var canJoin: Bool {
        availability.map { $0.available > 0 || resource.type.contains("QUEUE") } ?? true
    }

    private var actionTitle: String {
        switch resource.type {
        case "PHYSICAL_QUEUE", "EVENT_QUEUE": return "В очередь"
        case "WAITLIST": return "В лист ожидания"
        case "TICKET": return "Купить"
        case "TIME_SLOT": return "Забронировать"
        case "EVENT_REGISTRATION": return "Регистрация"
        default: return "Получить"
        }
    }
}

extension EventDTO {
    static var placeholder: EventDTO {
        .init(id: 0, title: "", description: "", startsAt: nil, city: nil, address: nil,
              category: "OTHER", status: "DRAFT", verificationStatus: "UNVERIFIED",
              capacity: nil, organizer: nil)
    }
}
