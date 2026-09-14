// DTOs.swift — mirrors backend schemas (section 78: the client receives
// resourceType / accessModel / policies and builds UX dynamically).
import Foundation

struct UserDTO: Codable, Identifiable {
    let id: Int
    let email: String
    let name: String
    let role: String
    let riskScore: Double
}

struct TokenDTO: Codable {
    let accessToken: String
    let user: UserDTO

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: AnyKey.self)
        accessToken = try c.decode(String.self, forKey: AnyKey("access_token"))
        user = try c.decode(UserDTO.self, forKey: AnyKey("user"))
    }
}

struct AnyKey: CodingKey {
    let stringValue: String
    let intValue: Int?
    init(_ s: String) { stringValue = s; intValue = nil }
    init?(stringValue: String) { self.stringValue = stringValue; intValue = nil }
    init?(intValue: Int) { stringValue = "\(intValue)"; self.intValue = intValue }
}

extension UserDTO {
    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: AnyKey.self)
        id = try c.decode(Int.self, forKey: AnyKey("id"))
        email = try c.decode(String.self, forKey: AnyKey("email"))
        name = try c.decode(String.self, forKey: AnyKey("name"))
        role = try c.decode(String.self, forKey: AnyKey("role"))
        riskScore = (try? c.decode(Double.self, forKey: AnyKey("risk_score"))) ?? 0
    }
}

struct OrganizerDTO: Codable, Identifiable {
    let id: Int
    let name: String
    let isVerified: Bool
}

extension OrganizerDTO {
    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: AnyKey.self)
        id = try c.decode(Int.self, forKey: AnyKey("id"))
        name = try c.decode(String.self, forKey: AnyKey("name"))
        isVerified = (try? c.decode(Bool.self, forKey: AnyKey("is_verified"))) ?? false
    }
}

struct EventDTO: Codable, Identifiable {
    let id: Int
    let title: String
    let description: String
    let startsAt: Date?
    let city: String?
    let address: String?
    let category: String
    let status: String
    let verificationStatus: String
    let capacity: Int?
    let organizer: OrganizerDTO?
}

extension EventDTO {
    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: AnyKey.self)
        id = try c.decode(Int.self, forKey: AnyKey("id"))
        title = try c.decode(String.self, forKey: AnyKey("title"))
        description = (try? c.decode(String.self, forKey: AnyKey("description"))) ?? ""
        startsAt = try? c.decode(Date.self, forKey: AnyKey("starts_at"))
        city = try? c.decode(String.self, forKey: AnyKey("city"))
        address = try? c.decode(String.self, forKey: AnyKey("address"))
        category = (try? c.decode(String.self, forKey: AnyKey("category"))) ?? "OTHER"
        status = (try? c.decode(String.self, forKey: AnyKey("status"))) ?? "DRAFT"
        verificationStatus = (try? c.decode(String.self, forKey: AnyKey("verification_status"))) ?? "UNVERIFIED"
        capacity = try? c.decode(Int.self, forKey: AnyKey("capacity"))
        organizer = try? c.decode(OrganizerDTO.self, forKey: AnyKey("organizer"))
    }
}

struct AvailabilityDTO: Codable {
    let resourceId: Int
    let totalCapacity: Int
    let confirmed: Int
    let available: Int
    let inQueue: Int
    let inWaitlist: Int
    let listed: Int
    let sold: Int
    let checkedIn: Int
}

extension AvailabilityDTO {
    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: AnyKey.self)
        resourceId = try c.decode(Int.self, forKey: AnyKey("resource_id"))
        totalCapacity = try c.decode(Int.self, forKey: AnyKey("total_capacity"))
        confirmed = try c.decode(Int.self, forKey: AnyKey("confirmed"))
        available = try c.decode(Int.self, forKey: AnyKey("available"))
        inQueue = (try? c.decode(Int.self, forKey: AnyKey("in_queue"))) ?? 0
        inWaitlist = (try? c.decode(Int.self, forKey: AnyKey("in_waitlist"))) ?? 0
        listed = (try? c.decode(Int.self, forKey: AnyKey("listed"))) ?? 0
        sold = (try? c.decode(Int.self, forKey: AnyKey("sold"))) ?? 0
        checkedIn = (try? c.decode(Int.self, forKey: AnyKey("checked_in"))) ?? 0
    }
}

struct ResourceDTO: Codable, Identifiable {
    let id: Int
    let eventId: Int
    let type: String
    let name: String
    let capacity: Int
    let queuePolicy: String
    let isTransferable: Bool
    let isResellable: Bool
    let requiresCheckIn: Bool
    let requiresOrganizerApproval: Bool
    let maxResalePrice: Int?
    let priceBase: Int
}

extension ResourceDTO {
    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: AnyKey.self)
        id = try c.decode(Int.self, forKey: AnyKey("id"))
        eventId = try c.decode(Int.self, forKey: AnyKey("event_id"))
        type = try c.decode(String.self, forKey: AnyKey("type"))
        name = try c.decode(String.self, forKey: AnyKey("name"))
        capacity = try c.decode(Int.self, forKey: AnyKey("capacity"))
        queuePolicy = (try? c.decode(String.self, forKey: AnyKey("queue_policy"))) ?? "FIFO"
        isTransferable = (try? c.decode(Bool.self, forKey: AnyKey("is_transferable"))) ?? true
        isResellable = (try? c.decode(Bool.self, forKey: AnyKey("is_resellable"))) ?? true
        requiresCheckIn = (try? c.decode(Bool.self, forKey: AnyKey("requires_check_in"))) ?? true
        requiresOrganizerApproval = (try? c.decode(Bool.self, forKey: AnyKey("requires_organizer_approval"))) ?? false
        maxResalePrice = try? c.decode(Int.self, forKey: AnyKey("max_resale_price"))
        priceBase = (try? c.decode(Int.self, forKey: AnyKey("price_base"))) ?? 0
    }
}

struct AccessRightDTO: Codable, Identifiable {
    let id: Int
    let tokenCode: String
    let kind: String
    let resourceId: Int
    let eventId: Int
    let ownerUserId: Int?
    let position: Int?
    let status: String
    let transferable: Bool
    let resellable: Bool
}

extension AccessRightDTO {
    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: AnyKey.self)
        id = try c.decode(Int.self, forKey: AnyKey("id"))
        tokenCode = try c.decode(String.self, forKey: AnyKey("token_code"))
        kind = try c.decode(String.self, forKey: AnyKey("kind"))
        resourceId = try c.decode(Int.self, forKey: AnyKey("resource_id"))
        eventId = try c.decode(Int.self, forKey: AnyKey("event_id"))
        ownerUserId = try? c.decode(Int.self, forKey: AnyKey("owner_user_id"))
        position = try? c.decode(Int.self, forKey: AnyKey("position"))
        status = try c.decode(String.self, forKey: AnyKey("status"))
        transferable = (try? c.decode(Bool.self, forKey: AnyKey("transferable"))) ?? false
        resellable = (try? c.decode(Bool.self, forKey: AnyKey("resellable"))) ?? false
    }
}

struct MarketplaceItemDTO: Codable, Identifiable {
    let kind: String
    let event: EventDTO?
    let resource: ResourceDTO?
    let listing: ListingDTO?
    let quote: PurchaseQuoteDTO?

    var id: String { "\(kind)-\(event?.id ?? 0)-\(resource?.id ?? 0)-\(listing?.id ?? 0)" }
}

struct PurchaseQuoteDTO: Codable {
    let listingId: Int
    let kind: String
    let price: Int?
    let currency: String
    let feePercent: Double
    let feeAmount: Int
    let sellerPayout: Int?
    let buyerTotal: Int?
    let dealWindowSeconds: Int
}

extension PurchaseQuoteDTO {
    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: AnyKey.self)
        listingId = try c.decode(Int.self, forKey: AnyKey("listing_id"))
        kind = (try? c.decode(String.self, forKey: AnyKey("kind"))) ?? "RESALE"
        price = try? c.decode(Int.self, forKey: AnyKey("price"))
        currency = (try? c.decode(String.self, forKey: AnyKey("currency"))) ?? "RUB"
        feePercent = (try? c.decode(Double.self, forKey: AnyKey("fee_percent"))) ?? 0
        feeAmount = (try? c.decode(Int.self, forKey: AnyKey("fee_amount"))) ?? 0
        sellerPayout = try? c.decode(Int.self, forKey: AnyKey("seller_payout"))
        buyerTotal = try? c.decode(Int.self, forKey: AnyKey("buyer_total"))
        dealWindowSeconds = (try? c.decode(Int.self, forKey: AnyKey("deal_window_seconds"))) ?? 0
    }
}

struct TransferDTO: Codable, Identifiable {
    let id: Int
    let fromUserId: Int
    let toUserId: Int
    let kind: String
    let price: Int?
    let status: String
    let createdAt: Date?
    let completedAt: Date?
}

extension TransferDTO {
    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: AnyKey.self)
        id = try c.decode(Int.self, forKey: AnyKey("id"))
        fromUserId = (try? c.decode(Int.self, forKey: AnyKey("from_user_id"))) ?? 0
        toUserId = (try? c.decode(Int.self, forKey: AnyKey("to_user_id"))) ?? 0
        kind = (try? c.decode(String.self, forKey: AnyKey("kind"))) ?? "RESALE"
        price = try? c.decode(Int.self, forKey: AnyKey("price"))
        status = (try? c.decode(String.self, forKey: AnyKey("status"))) ?? "INITIATED"
        createdAt = try? c.decode(Date.self, forKey: AnyKey("created_at"))
        completedAt = try? c.decode(Date.self, forKey: AnyKey("completed_at"))
    }
}

struct ListingDTO: Codable, Identifiable {
    let id: Int
    let accessRight: AccessRightDTO?
    let sellerUserId: Int
    let kind: String
    let price: Int?
    let isActive: Bool
}

extension ListingDTO {
    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: AnyKey.self)
        id = try c.decode(Int.self, forKey: AnyKey("id"))
        accessRight = try? c.decode(AccessRightDTO.self, forKey: AnyKey("access_right"))
        sellerUserId = (try? c.decode(Int.self, forKey: AnyKey("seller_user_id"))) ?? 0
        kind = (try? c.decode(String.self, forKey: AnyKey("kind"))) ?? "RESALE"
        price = try? c.decode(Int.self, forKey: AnyKey("price"))
        isActive = (try? c.decode(Bool.self, forKey: AnyKey("is_active"))) ?? true
    }
}

struct QueueJoinResultDTO: Codable {
    let queueId: Int
    let position: Int?
    let accessRight: AccessRightDTO?
    let message: String
}

extension QueueJoinResultDTO {
    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: AnyKey.self)
        queueId = try c.decode(Int.self, forKey: AnyKey("queue_id"))
        position = try? c.decode(Int.self, forKey: AnyKey("position"))
        accessRight = try? c.decode(AccessRightDTO.self, forKey: AnyKey("access_right"))
        message = (try? c.decode(String.self, forKey: AnyKey("message"))) ?? ""
    }
}

struct CheckInResultDTO: Codable {
    let result: String
    let method: String
}

extension CheckInResultDTO {
    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: AnyKey.self)
        result = (try? c.decode(String.self, forKey: AnyKey("result"))) ?? "INVALID"
        method = (try? c.decode(String.self, forKey: AnyKey("method"))) ?? "QR"
    }
}

struct WaitlistEntryDTO: Codable, Identifiable {
    let id: Int
    let position: Int
    let status: String
    let offerExpiresAt: Date?
}

extension WaitlistEntryDTO {
    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: AnyKey.self)
        id = try c.decode(Int.self, forKey: AnyKey("id"))
        position = (try? c.decode(Int.self, forKey: AnyKey("position"))) ?? 0
        status = (try? c.decode(String.self, forKey: AnyKey("status"))) ?? "WAITING"
        offerExpiresAt = try? c.decode(Date.self, forKey: AnyKey("offer_expires_at"))
    }
}

struct ReservationDTO: Codable, Identifiable {
    let id: Int
    let status: String
    let expiresAt: Date?
    let paymentStatus: String
}

extension ReservationDTO {
    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: AnyKey.self)
        id = try c.decode(Int.self, forKey: AnyKey("id"))
        status = (try? c.decode(String.self, forKey: AnyKey("status"))) ?? "CREATED"
        expiresAt = try? c.decode(Date.self, forKey: AnyKey("expires_at"))
        paymentStatus = (try? c.decode(String.self, forKey: AnyKey("payment_status"))) ?? "NONE"
    }
}
