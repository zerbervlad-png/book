// MyAccessView.swift — my rights, transfer/resale, QR display (sections 9, 12, 14).
import SwiftUI

struct MyAccessView: View {
    @EnvironmentObject var appModel: AppModel
    @State private var transferError: String?

    var body: some View {
        NavigationStack {
            List {
                Section("My access rights") {
                    if appModel.myRights.isEmpty {
                        Text("No access rights yet")
                            .foregroundStyle(.secondary)
                    }
                    ForEach(appModel.myRights) { right in
                        AccessRightRow(right: right) { price in
                            await listForSale(right, price: price)
                        }
                    }
                }
                Section("Reservations") {
                    ForEach(appModel.myReservations) { reservation in
                        LabeledContent("Reservation #\(reservation.id)",
                                       value: reservation.status)
                    }
                }
                if let transferError {
                    Text(transferError).font(.footnote).foregroundStyle(.red)
                }
            }
            .navigationTitle("My Access")
            .task { await appModel.reload() }
            .refreshable { await appModel.reload() }
        }
    }

    private func listForSale(_ right: AccessRightDTO, price: String) async {
        let trimmed = price.trimmingCharacters(in: .whitespaces)
        if !trimmed.isEmpty, Int(trimmed) == nil {
            transferError = "Price must be a whole number"
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
            transferError = (error as? LocalizedError)?.errorDescription ?? "Failed to list for sale"
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

struct AccessRightRow: View {
    let right: AccessRightDTO
    let onList: (String) -> Void
    @State private var isListing = false
    @State private var enteredPrice = ""

    var body: some View {
        VStack(alignment: .leading, spacing: 6) {
            HStack {
                if let position = right.position {
                    Text("#\(position)").font(.title2.bold())
                }
                VStack(alignment: .leading) {
                    Text(kindTitle).font(.headline)
                    Text(right.tokenCode).font(.caption.monospaced())
                        .foregroundStyle(.secondary)
                }
                Spacer()
                Text(right.status)
                    .font(.caption.bold())
                    .padding(.horizontal, 8).padding(.vertical, 4)
                    .background(Capsule().fill(statusColor.opacity(0.2)))
            }
            if right.status == "OWNED" && right.transferable {
                if isListing {
                    HStack {
                        TextField("Price (optional)", text: $enteredPrice)
                            .keyboardType(.numberPad)
                        Button("List") { onList(enteredPrice); isListing = false }
                            .buttonStyle(.borderedProminent)
                    }
                } else {
                    // 56: UI hides transfer when policy forbids it
                    Button("Transfer / Sell") { isListing = true }
                        .buttonStyle(.bordered)
                }
            }
            NavigationLink("Show QR") {
                AccessQRView(right: right)
            }
        }
    }

    private var kindTitle: String {
        switch right.kind {
        case "QUEUE_POSITION": return "Queue position"
        case "TICKET": return "Ticket"
        case "SLOT": return "Time slot"
        case "WAITLIST_PRIORITY": return "Waitlist priority"
        case "REGISTRATION": return "Registration"
        default: return "Access pass"
        }
    }

    private var statusColor: Color {
        switch right.status {
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
                Text(error).foregroundStyle(.red)
            } else {
                if let qrImage {
                    Image(uiImage: qrImage)
                        .resizable().interpolation(.none)
                        .frame(width: 240, height: 240)
                } else {
                    ProgressView()
                }
                if let code = oneTimeCode {
                    Text(code).font(.title2.bold().monospaced())
                }
                Text(right.tokenCode).font(.footnote.monospaced())
                    .foregroundStyle(.secondary)
            }
        }
        .padding()
        .navigationTitle("Your access")
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
            // QR bytes come from the backend with the auth header — the client
            // cannot forge the payload (section 42)
            let data = try await APIClient.shared.raw("GET", "/access/\(right.id)/qr")
            if let image = UIImage(data: data) {
                qrImage = image
            }
        } catch {
            self.error = (error as? LocalizedError)?.errorDescription ?? "Failed to load code"
        }
    }
}
