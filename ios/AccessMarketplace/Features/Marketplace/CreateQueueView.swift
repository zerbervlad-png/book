// CreateQueueView.swift — создание очереди пользователем (ТЗ, разделы 5, 6, 7).
// Пользователь сам создаёт очередь вокруг любого объекта: АЗС, магазин, клуб,
// учреждение. Очередь создаётся как USER_REQUEST и проходит проверку на бэкенде;
// дубликаты отклоняются (canonical key).
import SwiftUI

struct QueueCategory: Identifiable {
    let id: String
    let title: String
    let icon: String

    static let all: [QueueCategory] = [
        .init(id: "GAS_STATION", title: "АЗС", icon: "fuelpump.fill"),
        .init(id: "STORE", title: "Магазин", icon: "bag.fill"),
        .init(id: "CONCERT", title: "Концерт", icon: "music.note"),
        .init(id: "FESTIVAL", title: "Фестиваль", icon: "music.note.list"),
        .init(id: "CLUB", title: "Клуб", icon: "speaker.wave.2.fill"),
        .init(id: "RESTAURANT", title: "Ресторан", icon: "fork.knife"),
        .init(id: "CONFERENCE", title: "Конференция", icon: "person.3"),
        .init(id: "SERVICE", title: "Сервис / услуга", icon: "wrench.and.screwdriver"),
        .init(id: "GOVERNMENT", title: "Учреждение", icon: "building.columns"),
        .init(id: "OTHER", title: "Другое", icon: "sparkles"),
    ]
}

@MainActor
final class CreateQueueViewModel: ObservableObject {
    @Published var isSubmitting = false
    @Published var error: String?
    @Published var createdMessage: String?

    struct CreateEventBody: Encodable {
        let title: String
        let description: String
        let startsAt: String
        let city: String?
        let address: String?
        let capacity: Int?
        let category: String

        enum CodingKeys: String, CodingKey {
            case title, description, capacity, category, city, address
            case startsAt = "starts_at"
        }
    }

    struct CreateResourceBody: Encodable {
        let eventId: Int
        let type = "PHYSICAL_QUEUE"
        let name: String
        let capacity: Int
        let queuePolicy = "FIFO"

        enum CodingKeys: String, CodingKey {
            case type, name, capacity
            case eventId = "event_id"
            case queuePolicy = "queue_policy"
        }
    }

    func submit(title: String, category: String, city: String, address: String,
                description: String, startsAt: Date, capacity: Int) async {
        let trimmedTitle = title.trimmingCharacters(in: .whitespaces)
        guard !trimmedTitle.isEmpty else {
            error = "Укажите название объекта"
            return
        }
        isSubmitting = true
        defer { isSubmitting = false }
        do {
            let formatter = ISO8601DateFormatter()
            let event: EventDTO = try await APIClient.shared.request(
                "POST", "events",
                body: CreateEventBody(
                    title: trimmedTitle,
                    description: description,
                    startsAt: formatter.string(from: startsAt),
                    city: city.isEmpty ? nil : city,
                    address: address.isEmpty ? nil : address,
                    capacity: capacity,
                    category: category),
                as: EventDTO.self)
            let _: ResourceDTO = try await APIClient.shared.request(
                "POST", "resources",
                body: CreateResourceBody(
                    eventId: event.id,
                    name: "Очередь (FIFO)",
                    capacity: capacity),
                as: ResourceDTO.self)
            createdMessage = "Очередь создана и отправлена на проверку. " +
                "Другие пользователи уже могут её найти и занять место."
            error = nil
        } catch {
            if case let APIError.server(code, _, _) = error, code == "DUPLICATE_EVENT" {
                self.error = "Такая очередь уже существует — найдите её через поиск"
            } else {
                self.error = (error as? LocalizedError)?.errorDescription ?? "Не удалось создать очередь"
            }
        }
    }
}

struct CreateQueueView: View {
    @StateObject private var model = CreateQueueViewModel()
    @Environment(\.dismiss) private var dismiss

    @State private var title = ""
    @State private var category = "GAS_STATION"
    @State private var city = ""
    @State private var address = ""
    @State private var description = ""
    @State private var startsAt = Calendar.current.date(byAdding: .hour, value: 1, to: Date()) ?? Date()
    @State private var capacity = 30

    var body: some View {
        NavigationStack {
            Form {
                Section {
                    TextField("Например: АЗС Газпромнефть, Ленинградское шоссе, 25", text: $title)
                        .autocorrectionDisabled()
                    Picker("Тип объекта", selection: $category) {
                        ForEach(QueueCategory.all) { item in
                            Label(item.title, systemImage: item.icon).tag(item.id)
                        }
                    }
                    TextField("Город", text: $city)
                    TextField("Адрес", text: $address)
                    DatePicker("Дата и время", selection: $startsAt)
                    Stepper("Мест в очереди: \(capacity)", value: $capacity, in: 1...1000)
                    TextField("Описание (необязательно)", text: $description, axis: .vertical)
                        .lineLimit(2...5)
                } header: {
                    Label("Новая очередь", systemImage: "person.2.wave.2")
                } footer: {
                    Text("Указывайте реальный адрес объекта: очередь проходит проверку, " +
                         "дубликаты и фейковые объекты удаляются модерацией.")
                }
                if let message = model.createdMessage {
                    Section {
                        Label(message, systemImage: "checkmark.circle.fill")
                            .foregroundStyle(.green)
                        Button("Готово") { dismiss() }
                            .buttonStyle(.borderedProminent)
                    }
                }
                if model.isSubmitting {
                    Section {
                        HStack { Spacer(); ProgressView("Создание…"); Spacer() }
                    }
                }
                if let error = model.error {
                    Section {
                        Label(error, systemImage: "exclamationmark.triangle.fill")
                            .foregroundStyle(.red)
                    }
                }
            }
            .navigationTitle("Создать очередь")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .cancellationAction) {
                    Button("Отмена") { dismiss() }
                }
                ToolbarItem(placement: .confirmationAction) {
                    Button("Создать") {
                        Task {
                            await model.submit(title: title, category: category, city: city,
                                               address: address, description: description,
                                               startsAt: startsAt, capacity: capacity)
                        }
                    }
                    .disabled(model.isSubmitting || model.createdMessage != nil || title.isEmpty)
                }
            }
        }
    }
}
