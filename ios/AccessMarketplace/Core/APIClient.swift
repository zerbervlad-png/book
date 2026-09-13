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
    let code: String?
    let message: String?
}

final class APIClient {
    static let shared = APIClient()

    var baseURL = URL(string: "http://localhost:8000/api")!
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

    func request<Body: Encodable, T: Decodable>(
        _ method: String, _ path: String, body: Body? = nil, as type: T.Type
    ) async throws -> T {
        var req = URLRequest(url: baseURL.appendingPathComponent(path))
        req.httpMethod = method
        req.setValue("application/json", forHTTPHeaderField: "Content-Type")
        if let token { req.setValue("Bearer \(token)", forHTTPHeaderField: "Authorization") }
        if let body { req.httpBody = try encoder.encode(body) }
        return try await run(req)
    }

    func request<T: Decodable>(_ method: String, _ path: String, as type: T.Type) async throws -> T {
        var req = URLRequest(url: baseURL.appendingPathComponent(path))
        req.httpMethod = method
        if let token { req.setValue("Bearer \(token)", forHTTPHeaderField: "Authorization") }
        return try await run(req)
    }

    func raw(_ method: String, _ path: String) async throws -> Data {
        var req = URLRequest(url: baseURL.appendingPathComponent(path))
        req.httpMethod = method
        if let token { req.setValue("Bearer \(token)", forHTTPHeaderField: "Authorization") }
        let (data, response) = try await URLSession.shared.data(for: req)
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
