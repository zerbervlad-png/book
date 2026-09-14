// ListingDetailView.swift — полный путь покупателя (ТЗ, разделы 2, 9, 10):
// выбор места → цена и комиссия → подтверждение → расчёт → место переходит покупателю.
// Место блокируется на время сделки (TRANSFER_PENDING + TTL на бэкенде),
// одновременная покупка двумя пользователями невозможна.
import SwiftUI

@MainActor
final class ListingDetailViewModel: ObservableObject {
    @Published var quote: PurchaseQuoteDTO?
    @Published var isBuying = false
    @Published var resultMessage: String?
    @Published var error: String?

    let item: MarketplaceItemDTO

    init(item: MarketplaceItemDTO) {
        self.item = item
        self.quote = item.quote
    }

    var listingId: Int? { item.listing?.id }
    var isPaid: Bool { (quote?.price ?? item.listing?.price) != nil }

    func loadQuote() async {
        guard let listingId else { return }
        do {
            quote = try await APIClient.shared.request(
                "GET", "transfers/listings/\(listingId)/quote", as: PurchaseQuoteDTO.self)
        } catch {
            self.error = (error as? LocalizedError)?.errorDescription ?? "Не удалось загрузить условия"
        }
    }

    /// Купить / получить место: buy → (оплата при цене > 0) → место закрепляется.
    func buy(appModel: AppModel) async {
        guard let listingId else { return }
        isBuying = true
        defer { isBuying = false }
        do {
            struct BuyResponse: Codable {
                let id: Int
                let status: String
                let price: Int?
            }
            let transfer: BuyResponse = try await APIClient.shared.request(
                "POST", "transfers/buy",
                body: ["listing_id": AnyEncodable(listingId),
                       "idempotency_key": AnyEncodable(UUID().uuidString)],
                as: BuyResponse.self)
            if transfer.price != nil {
                // расчёт: авторизация + захват; комиссия удерживается из суммы продавца
                struct PayResponse: Codable { let id: Int }
                let _: PayResponse = try await APIClient.shared.request(
                    "POST", "transfers/\(transfer.id)/pay",
                    body: ["idempotency_key": AnyEncodable(UUID().uuidString)],
                    as: PayResponse.self)
            }
            resultMessage = "Место передано вам. Новый токен доступа — в разделе «Мой доступ»."
            error = nil
            await appModel.reload()
        } catch let APIError.server(code, message, _) where code == "RIGHT_NOT_TRANSFERABLE"
                                                        || code == "ALREADY_LISTED"
                                                        || code == "INVALID_STATE":
            error = "Место уже купил другой пользователь или сделка была отменена"
        } catch {
            self.error = (error as? LocalizedError)?.errorDescription ?? "Не удалось завершить сделку"
        }
    }
}

struct ListingDetailView: View {
    @StateObject private var model: ListingDetailViewModel
    @EnvironmentObject var appModel: AppModel
    @State private var confirmBuying = false

    init(item: MarketplaceItemDTO) {
        _model = StateObject(wrappedValue: ListingDetailViewModel(item: item))
    }

    var body: some View {
        List {
            summarySection
            quoteSection
            actionSection
        }
        .navigationTitle("Место в очереди")
        .navigationBarTitleDisplayMode(.inline)
        .task { if model.quote == nil { await model.loadQuote() } }
        .refreshable { await model.loadQuote() }
        .confirmationDialog("Подтвердите сделку", isPresented: $confirmBuying, titleVisibility: .visible) {
            Button(model.isPaid ? "Купить место" : "Получить место") {
                Task { await model.buy(appModel: appModel) }
            }
            Button("Отмена", role: .cancel) {}
        } message: {
            Text(confirmMessage)
        }
    }

    private var summarySection: some View {
        Section {
            if let event = model.item.event {
                LabeledContent { Text(event.title) } label: {
                    Label("Объект", systemImage: "mappin.and.ellipse")
                }
                if let city = event.city, !city.isEmpty {
                    LabeledContent { Text(city) } label: { Label("Город", systemImage: "building.2") }
                }
            }
            if let right = model.item.listing?.accessRight {
                LabeledContent {
                    Text(right.position.map { "№\($0)" } ?? "—")
                } label: {
                    Label("Позиция", systemImage: "number")
                }
            }
            if let resource = model.item.resource {
                LabeledContent { Text(resource.name) } label: {
                    Label("Очередь", systemImage: "person.2")
                }
            }
        }
    }

    private var quoteSection: some View {
        Section {
            if let quote = model.quote {
                if let price = quote.price {
                    LabeledContent { Text("\(price) ₽").font(.headline) } label: {
                        Text("Цена места")
                    }
                    LabeledContent { Text("\(quote.feeAmount) ₽ (\(String(format: "%.0f", quote.feePercent))%)") } label: {
                        Text("Комиссия сервиса")
                    }
                    if let payout = quote.sellerPayout {
                        LabeledContent { Text("\(payout) ₽") } label: {
                            Text("Получит продавец")
                        }
                    }
                    LabeledContent {
                        Text("\(quote.buyTotal ?? price) ₽").font(.title3.bold()).foregroundStyle(.tint)
                    } label: {
                        Text("К оплате")
                    }
                    Label("Оплата удерживается в escrow до подтверждения передачи",
                          systemImage: "lock.shield")
                        .font(.caption).foregroundStyle(.secondary)
                } else {
                    Label("Передача без оплаты", systemImage: "gift")
                        .font(.headline).foregroundStyle(.green)
                }
                if quote.dealWindowSeconds > 0 {
                    Label("На завершение сделки — \(quote.dealWindowSeconds / 60) мин, затем блокировка снимается",
                          systemImage: "timer")
                        .font(.caption).foregroundStyle(.secondary)
                }
            } else if model.error == nil {
                HStack { Spacer(); ProgressView("Загрузка условий…"); Spacer() }
            }
        } header: {
            Label("Условия сделки", systemImage: "rublesign")
        } footer: {
            Text("Комиссия удерживается из суммы продавца: вы платите ровно цену места.")
        }
    }

    private var actionSection: some View {
        Section {
            if let message = model.resultMessage {
                Label(message, systemImage: "checkmark.circle.fill")
                    .foregroundStyle(.green).font(.headline)
            } else if model.isBuying {
                HStack { Spacer(); ProgressView("Обработка сделки…"); Spacer() }
            } else {
                Button {
                    confirmBuying = true
                } label: {
                    Label(model.isPaid ? "Купить место" : "Получить место",
                          systemImage: model.isPaid ? "cart.fill.badge.plus" : "hand.thumbsup.fill")
                        .frame(maxWidth: .infinity)
                }
                .buttonStyle(.borderedProminent)
                .disabled(model.quote == nil)
            }
            if let error = model.error {
                Label(error, systemImage: "exclamationmark.triangle.fill")
                    .foregroundStyle(.red)
            }
        }
    }

    private var confirmMessage: String {
        if let quote = model.quote, let price = quote.price {
            return "Списывается \(price) ₽. После подтверждения место будет заблокировано за вами."
        }
        return "Место будет передано вам бесплатно."
    }
}
