// AppModel.swift — session-level observable models (MVVM, section 41).
import Foundation

@MainActor
final class AppModel: ObservableObject {
    @Published var myRights: [AccessRightDTO] = []
    @Published var myReservations: [ReservationDTO] = []

    func reload() async {
        // Backend is the source of truth; failures leave last known state (43).
        if let rights: [AccessRightDTO] = try? await APIClient.shared.request(
            "GET", "/access/my", as: [AccessRightDTO].self) {
            myRights = rights
        }
        if let reservations: [ReservationDTO] = try? await APIClient.shared.request(
            "GET", "/reservations/my", as: [ReservationDTO].self) {
            myReservations = reservations
        }
    }
}
