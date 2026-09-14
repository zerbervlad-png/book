// AppModel.swift — session-level observable models (MVVM, section 41).
import Foundation

@MainActor
final class AppModel: ObservableObject {
    @Published var myRights: [AccessRightDTO] = []
    @Published var myReservations: [ReservationDTO] = []
    @Published var myTransfers: [TransferDTO] = []
    // 43: offline must be visible — the data shown may be stale
    @Published var syncError: String?

    func reload() async {
        // Backend is the source of truth; failures leave last known state (43).
        syncError = nil
        do {
            myRights = try await APIClient.shared.request(
                "GET", "/access/my", as: [AccessRightDTO].self)
        } catch APIError.unauthorized {
        } catch {
            syncError = "Нет соединения — показаны последние известные данные"
        }
        do {
            myReservations = try await APIClient.shared.request(
                "GET", "/reservations/my", as: [ReservationDTO].self)
        } catch APIError.unauthorized {
        } catch {
            syncError = "Нет соединения — показаны последние известные данные"
        }
        do {
            myTransfers = try await APIClient.shared.request(
                "GET", "/transfers/my", as: [TransferDTO].self)
        } catch APIError.unauthorized {
        } catch {
            syncError = "Нет соединения — показаны последние известные данные"
        }
    }
}
