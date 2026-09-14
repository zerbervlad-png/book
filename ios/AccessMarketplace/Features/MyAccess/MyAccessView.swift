// MyAccessView.swift — мои права, передача/перепродажа, QR (разделы 9, 12, 14 ТЗ).
import SwiftUI

struct MyAccessView: View {
    @EnvironmentObject var appModel: AppModel
    @EnvironmentObject var auth: AuthManager
    @State private var transferError: String?

    var body: some View {
        NavigationStack {
            List {
                Section {
                    if appModel.myRights.isEmpty {
                        ContentUnavailableView(
                            "Пока нет прав доступа",
                            systemImage: "ticket",
                            description: Text("Встаньте в очередь или забронируйте слот на главном экране"))
                            .frame(maxWidth: .infinity)
                            .listRowBackground(Color.clear)
                    }
                    ForEach(appModel.myRights) { right in
                        AccessRightRow(right: right) { price in
                            await listForSale(right, price: price)
                        }
                    }
                } header: {
                    Label("Мои права доступа", systemImage: "ticket")
                }
                if !appModel.myReservations.isEmpty {
                    Section {
                        ForEach(appModel.myReservations) { reservation in
                            HStack {
                                Image(systemName: "calendar.badge.checkmark")
                                    .foregroundStyle(.tint)
                                Text("Бронь №\(reservation.id)")
                                Spacer()
                                Text(reservationTitle(reservation.status))
                                    .font(.caption.bold())
                                    .padding(.horizontal, 8).padding(.vertical, 4)
                                    .background(Capsule().fill(.tint.opacity(0.12)))
                            }
                        }
                    } header: {
                        Label("Брони", systemImage: "calendar")
                    }
                }
                if !appModel.myTransfers.isEmpty {
                    Section {
                        ForEach(appModel.myTransfers) { transfer in
                            TransferHistoryRow(transfer: transfer, myUserId: auth.user?.id ?? 0)
                        }
                    } header: {
                        Label("История сделок", systemImage: "clock.arrow.circlepath")
                    } footer: {
                        Text("Все операции сохраняются в неизменяемом журнале на сервере.")
                    }
                }
                if let syncError = appModel.syncError {
                    Section {
                        Label(syncError, systemImage: "wifi.exclamationmark")
                            .font(.footnote).foregroundStyle(.orange)
                    }
                }
                if let transferError {
                    Section {
                        Label(transferError, systemImage: "exclamationmark.triangle.fill")
                            .font(.footnote).foregroundStyle(.red)
                    }
                }
            }
            .navigationTitle("Мой доступ")
            .task { await appModel.reload() }
            .refreshable { await appModel.reload() }
        }
    }

    private func listForSale(_ right: AccessRightDTO, price: String) async {
        let trimmed = price.trimmingCharacters(in: .whitespaces)
        if !trimmed.isEmpty, Int(trimmed) == nil {
            transferError = "Цена должна быть целым числом"
            return
        }
        do {
            let value = Int(trimmed)
            let body: [String: AnyEncodable?] = [
                "access_right_id": AnyEncodable(right.id),
                "price": value.map { AnyEncodable($0) },
            ]
            struct ListingResponse: Codable { let id: Int }
            let _: ListingResponse = try await APIClient.shared.request(
                "POST", "/transfers/listings", body: body.compactMapValues { $0 },
                as: ListingResponse.self)
            await appModel.reload()
            transferError = nil
        } catch {
            transferError = (error as? LocalizedError)?.errorDescription ?? "Не удалось выставить на продажу"
        }
    }
}

struct AnyEncodable: Encodable {
    private let encodeFunc: (Encoder) throws -> Void
    init(_ value: some Encodable) {
        encodeFunc = { try value.encode(to: $0) }
    }
    func encode(to encoder: Encoder) throws {
        try encodeFunc(encoder)
    }
}

struct TransferHistoryRow: View {
    let transfer: TransferDTO
    let myUserId: Int

    var body: some View {
        HStack(spacing: 12) {
            Image(systemName: isBuying ? "cart.fill" : "arrow.up.circle.fill")
                .foregroundStyle(isBuying ? .blue : .orange)
            VStack(alignment: .leading, spacing: 2) {
                Text(isBuying ? "Покупка места" : "Передача места")
                    .font(.headline)
                if let date = transfer.createdAt {
                    Text(date.formatted(.dateTime.day().month().hour().minute()
                        .locale(Locale(identifier: "ru_RU"))))
                        .font(.caption)
                        .foregroundStyle(.secondary)
                }
            }
            Spacer()
            VStack(alignment: .trailing, spacing: 2) {
                if let price = transfer.price {
                    Text("\(price) ₽").font(.subheadline.bold())
                } else {
                    Text("Даром").font(.subheadline).foregroundStyle(.green)
                }
                Text(statusTitle)
                    .font(.caption.bold())
                    .foregroundStyle(statusColor)
            }
        }
        .padding(.vertical, 2)
    }

    private var isBuying: Bool { transfer.toUserId == myUserId }

    private var statusTitle: String {
        switch transfer.status {
        case "INITIATED": return "Начата"
        case "AWAITING_PAYMENT": return "Ожидает оплаты"
        case "AWAITING_BUYER_CLAIM": return "На подтверждении"
        case "VERIFYING": return "Проверяется"
        case "TOKEN_LOCKED": return "Заблокировано"
        case "COMPLETED": return "Передано"
        case "CANCELLED": return "Отменено"
        case "REJECTED": return "Отклонено"
        case "EXPIRED": return "Срок истёк"
        default: return transfer.status
        }
    }

    private var statusColor: Color {
        switch transfer.status {
        case "COMPLETED": return .green
        case "CANCELLED", "REJECTED", "EXPIRED": return .red
        default: return .orange
        }
    }
}

struct AccessRightRow: View {
    let right: AccessRightDTO
    let onList: (String) async -> Void
    @State private var isListing = false
    @State private var enteredPrice = ""

    var body: some View {
        VStack(alignment: .leading, spacing: 8) {
            HStack(spacing: 12) {
                if let position = right.position {
                    ZStack {
                        Circle().fill(.tint.opacity(0.12))
                        Text("\(position)")
                            .font(.title3.bold()).monospacedDigit()
                    }
                    .frame(width: 44, height: 44)
                    .accessibilityLabel("Позиция №\(position)")
                }
                VStack(alignment: .leading, spacing: 2) {
                    Text(kindTitle).font(.headline)
                    Text(right.tokenCode).font(.caption.monospaced())
                        .foregroundStyle(.secondary)
                }
                Spacer()
                Text(statusTitle(right.status))
                    .font(.caption.bold())
                    .padding(.horizontal, 10).padding(.vertical, 5)
                    .foregroundStyle(statusColor(right.status))
                    .background(Capsule().fill(statusColor(right.status).opacity(0.15)))
            }
            if right.status == "OWNED" && right.transferable {
                if isListing {
                    HStack(spacing: 8) {
                        TextField("Цена, ₽", text: $enteredPrice)
                            .keyboardType(.numberPad)
                            .padding(10)
                            .background(RoundedRectangle(cornerRadius: 10)
                                .fill(.quaternary.opacity(0.5)))
                        Button {
                            Task { await onList(enteredPrice) }
                            isListing = false
                        } label: {
                            Text("Выставить").font(.subheadline.bold())
                        }
                        .buttonStyle(.borderedProminent)
                        Button("Отмена") {
                            isListing = false
                            enteredPrice = ""
                        }
                        .font(.subheadline)
                    }
                } else {
                    // 56: UI скрывает передачу, если политика запрещает
                    // ТЗ 9: продавец выбирает — продать или передать бесплатно
                    Menu {
                        if right.resellable {
                            Button {
                                isListing = true
                            } label: {
                                Label("Выставить на продажу…", systemImage: "rublesign")
                            }
                        }
                        Button {
                            Task { await onList("") }
                        } label: {
                            Label("Передать даром", systemImage: "gift")
                        }
                    } label: {
                        Label("Передать место", systemImage: "arrow.triangle.2.circlepath")
                            .font(.subheadline)
                    }
                }
            }
            NavigationLink {
                AccessQRView(right: right)
            } label: {
                Label("Показать QR-код", systemImage: "qrcode")
                    .font(.subheadline.bold())
            }
        }
        .padding(.vertical, 4)
    }

    private var kindTitle: String {
        switch right.kind {
        case "QUEUE_POSITION": return "Позиция в очереди"
        case "TICKET": return "Билет"
        case "SLOT": return "Тайм-слот"
        case "WAITLIST_PRIORITY": return "Приоритет в листе ожидания"
        case "REGISTRATION": return "Регистрация"
        default: return "Пропуск"
        }
    }

    private func statusTitle(_ status: String) -> String {
        switch status {
        case "OWNED": return "Активно"
        case "LISTED": return "На продаже"
        case "TRANSFER_PENDING": return "Передаётся"
        case "USED": return "Использовано"
        default: return status
        }
    }

    private func statusColor(_ status: String) -> Color {
        switch status {
        case "OWNED": return .green
        case "LISTED": return .blue
        case "TRANSFER_PENDING": return .orange
        case "USED": return .gray
        default: return .red
        }
    }
}

struct AccessQRView: View {
    let right: AccessRightDTO
    @State private var oneTimeCode: String?
    @State private var qrImage: UIImage?
    @State private var error: String?

    var body: some View {
        VStack(spacing: 24) {
            if let error {
                Label(error, systemImage: "exclamationmark.triangle.fill")
                    .foregroundStyle(.red)
            } else {
                ZStack {
                    RoundedRectangle(cornerRadius: 20)
                        .fill(.white)
                        .shadow(color: .black.opacity(0.15), radius: 12, y: 4)
                    if let qrImage {
                        Image(uiImage: qrImage)
                            .resizable().interpolation(.none)
                            .frame(width: 220, height: 220)
                            .padding(12)
                    } else {
                        ProgressView().frame(width: 220, height: 220)
                    }
                }
                if let code = oneTimeCode {
                    VStack(spacing: 6) {
                        Text("Одноразовый код")
                            .font(.caption)
                            .foregroundStyle(.secondary)
                        Text(code)
                            .font(.title2.bold().monospaced())
                            .tracking(2)
                    }
                    .padding(.horizontal, 20)
                    .padding(.vertical, 12)
                    .background(RoundedRectangle(cornerRadius: 14)
                        .fill(.tint.opacity(0.08)))
                }
                Text(right.tokenCode)
                    .font(.footnote.monospaced())
                    .foregroundStyle(.secondary)
            }
            Spacer()
        }
        .padding()
        .navigationTitle("Ваш доступ")
        .navigationBarTitleDisplayMode(.inline)
        .task { await loadCode() }
    }

    private func loadCode() async {
        struct CodeDTO: Decodable {
            let oneTimeCode: String
            enum CodingKeys: String, CodingKey {
                case oneTimeCode = "one_time_code"
            }
        }
        do {
            let dto: CodeDTO = try await APIClient.shared.request(
                "GET", "/access/\(right.id)/code", as: CodeDTO.self)
            oneTimeCode = dto.oneTimeCode
            // QR приходит с бэкенда с auth-заголовком — клиент не может
            // подделать payload (раздел 42 ТЗ)
            let data = try await APIClient.shared.raw("GET", "/access/\(right.id)/qr")
            if let image = UIImage(data: data) {
                qrImage = image
            }
        } catch {
            self.error = (error as? LocalizedError)?.errorDescription ?? "Не удалось загрузить QR"
        }
    }
}
