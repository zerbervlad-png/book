// APIClient.swift
// Single networking layer (section 41). The client never decides business
// truth — every critical fact comes from the backend (section 42).
import Foundation

enum APIError: LocalizedError {
    case invalidURL
    case unauthorized
    case server(code: String, message: String, status: Int)
    case network(Error)
    case decoding(Error)

    var errorDescription: String? {
        switch self {
        case .invalidURL: return "Invalid request"
        case .unauthorized: return "Please sign in again"
        case .server(_, let message, _): return message
        case .network(let e): return e.localizedDescription
        case .decoding: return "Unexpected server response"
        }
    }
}

struct APIEnvelope: Decodable {
    // Backend error envelope: {"detail": {"code": ..., "message": ...}}
    let code: String?
    let message: String?

    enum CodingKeys: String, CodingKey { case detail }
    struct Detail: Decodable {
        let code: String?
        let message: String?

        init(from decoder: Decoder) throws {
            let c = try decoder.container(keyedBy: CodingKeys2.self)
            code = (try? c.decode(String.self, forKey: CodingKeys2.code)) ?? "ERROR"
            message = (try? c.decode(String.self, forKey: CodingKeys2.message))
            enum CodingKeys2: String, CodingKey { case code, message }
        }
    }

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        let detail = try c.decode(Detail.self, forKey: .detail)
        code = detail.code
        message = detail.message
    }
}

final class APIClient {
    static let shared = APIClient()

    var baseURL = URL(string: ServerConfig.apiBaseURL)!
    var token: String?

    private let decoder: JSONDecoder = {
        let d = JSONDecoder()
        d.dateDecodingStrategy = .iso8601
        return d
    }()

    private let encoder: JSONEncoder = {
        let e = JSONEncoder()
        e.dateEncodingStrategy = .iso8601
        return e
    }()

    /// Builds a URL from a path that may contain a query string.
    /// `appendingPathComponent` percent-encodes "?" which breaks queries.
    private func makeURL(_ path: String) -> URL? {
        let parts = path.split(separator: "?", maxSplits: 1).map(String.init)
        guard var comps = URLComponents(url: baseURL, resolvingAgainstBaseURL: false) else {
            return nil
        }
        let pathPart = parts[0].hasPrefix("/") ? parts[0] : "/" + parts[0]
        comps.path = comps.path + pathPart
        if parts.count > 1 {
            comps.percentEncodedQuery = parts[1]
        }
        return comps.url
    }

    func request<Body: Encodable, T: Decodable>(
        _ method: String, _ path: String, body: Body? = nil, as type: T.Type = T.self
    ) async throws -> T {
        guard let url = makeURL(path) else { throw APIError.invalidURL }
        var req = URLRequest(url: url)
        req.httpMethod = method
        req.setValue("application/json", forHTTPHeaderField: "Content-Type")
        if let token { req.setValue("Bearer \(token)", forHTTPHeaderField: "Authorization") }
        if let body { req.httpBody = try encoder.encode(body) }
        return try await run(req)
    }

    func request<T: Decodable>(_ method: String, _ path: String, as type: T.Type) async throws -> T {
        guard let url = makeURL(path) else { throw APIError.invalidURL }
        var req = URLRequest(url: url)
        req.httpMethod = method
        if let token { req.setValue("Bearer \(token)", forHTTPHeaderField: "Authorization") }
        return try await run(req)
    }

    func raw(_ method: String, _ path: String) async throws -> Data {
        guard let url = makeURL(path) else { throw APIError.invalidURL }
        var req = URLRequest(url: url)
        req.httpMethod = method
        if let token { req.setValue("Bearer \(token)", forHTTPHeaderField: "Authorization") }
        let (data, _) = try await URLSession.shared.data(for: req)
        return data
    }

    private func run<T: Decodable>(_ req: URLRequest) async throws -> T {
        let data: Data
        let response: URLResponse
        do {
            (data, response) = try await URLSession.shared.data(for: req)
        } catch {
            throw APIError.network(error) // offline — critical ops impossible (43)
        }
        guard let http = response as? HTTPURLResponse else { throw APIError.invalidURL }
        if http.statusCode == 401 { throw APIError.unauthorized }
        guard (200..<300).contains(http.statusCode) else {
            let env = try? decoder.decode(APIEnvelope.self, from: data)
            throw APIError.server(code: env?.code ?? "ERROR",
                                  message: env?.message ?? "Request failed",
                                  status: http.statusCode)
        }
        do {
            return try decoder.decode(T.self, from: data)
        } catch {
            throw APIError.decoding(error)
        }
    }
}
