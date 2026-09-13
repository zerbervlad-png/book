// EventDetailView.swift — section 22 event card + section 79 dynamic UX.
// The UI is built from resourceType / accessModel / policies sent by backend.
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
            self.error = (error as? LocalizedError)?.errorDescription ?? "Failed to load event"
        }
    }

    /// One unified entry point — the backend decides what "getting access"
    /// means for this resource type (sections 80-83).
    func getAccess(to resource: ResourceDTO) async {
        do {
            switch resource.type {
            case "PHYSICAL_QUEUE", "EVENT_QUEUE":
                let result: QueueJoinResultDTO = try await APIClient.shared.request(
                    "POST", "queues/resources/\(resource.id)/join", body: EmptyBody(),
                    as: QueueJoinResultDTO.self)
                joinedMessage = result.accessRight.map { right in
                    right.position.map { "You are #\($0) in the queue" } ?? "Joined — awaiting draw"
                } ?? "Joined — awaiting draw"
            case "WAITLIST":
                let entry: WaitlistEntryDTO = try await APIClient.shared.request(
                    "POST", "waitlists/resources/\(resource.id)/join", body: EmptyBody(),
                    as: WaitlistEntryDTO.self)
                joinedMessage = "Waitlist #\(entry.position)"
            case "TICKET", "TIME_SLOT", "EVENT_REGISTRATION", "ACCESS_PASS":
                let reservation: ReservationDTO = try await APIClient.shared.request(
                    "POST", "/reservations", body: ["resource_id": resource.id],
                    as: ReservationDTO.self)
                let confirmed: ReservationDTO = try await APIClient.shared.request(
                    "POST", "/reservations/\(reservation.id)/confirm", body: EmptyBody(),
                    as: ReservationDTO.self)
                joinedMessage = "Confirmed — \(confirmed.status)"
            default:
                joinedMessage = nil
            }
            error = nil
            await load()
        } catch {
            self.error = (error as? LocalizedError)?.errorDescription ?? "Failed to get access"
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
                Section("Ways to get access") {
                    ForEach(model.resources) { resource in
                        ResourceRow(resource: resource,
                                    availability: model.availability[resource.id]) {
                            Task {
                                await model.getAccess(to: resource)
                                await appModel.reload()
                            }
                        }
                    }
                }
            }
            if let message = model.joinedMessage {
                Section { Label(message, systemImage: "checkmark.circle.fill")
                    .foregroundStyle(.green) }
            }
            if let error = model.error {
                Section { Label(error, systemImage: "exclamationmark.triangle")
                    .foregroundStyle(.red) }
            }
        }
        .navigationTitle(model.event.title)
        .task { await model.load(); await appModel.reload() }
    }

    private var header: some View {
        Section {
            LabeledContent("Starts", value: model.event.startsAt?
                .formatted(date: .long, time: .shortened) ?? "—")
            if let city = model.event.city { LabeledContent("City", value: city) }
            if let organizer = model.event.organizer {
                LabeledContent("Organizer", value: organizer.name)
            }
            LabeledContent("Status", value: model.event.status)
            LabeledContent("Verification", value: model.event.verificationStatus)
            Text(model.event.description)
                .font(.body).foregroundStyle(.secondary)
        }
    }
}

struct ResourceRow: View {
    let resource: ResourceDTO
    let availability: AvailabilityDTO?
    let action: () -> Void

    var body: some View {
        VStack(alignment: .leading, spacing: 6) {
            HStack {
                Text(resource.name).font(.headline)
                Spacer()
                Button(actionTitle, action: action)
                    .buttonStyle(.borderedProminent)
                    .disabled(!canJoin)
            }
            if let av = availability {
                Text("Available \(av.available) / \(av.totalCapacity) · in queue \(av.inQueue)")
                    .font(.caption).foregroundStyle(.secondary)
            }
            if !resource.isTransferable {
                Label("Transfer disabled by organizer", systemImage: "lock")
                    .font(.caption2).foregroundStyle(.orange)
            }
        }
    }

    private var canJoin: Bool {
        availability.map { $0.available > 0 || resource.type.contains("QUEUE") } ?? true
    }

    private var actionTitle: String {
        switch resource.type {
        case "PHYSICAL_QUEUE", "EVENT_QUEUE": return "Join queue"
        case "WAITLIST": return "Join waitlist"
        case "TICKET": return "Buy ticket"
        case "TIME_SLOT": return "Book slot"
        case "EVENT_REGISTRATION": return "Register"
        default: return "Get access"
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
