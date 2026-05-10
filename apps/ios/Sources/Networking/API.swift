import Foundation
import SwiftUI

// Mirrors apps/figma-ui/src/app/lib/api.ts.
// Override at runtime via UserDefaults key "backend_url".
// Default is generated at build time from .env (see Generated/BackendConfig.swift)
// so an iPhone build dials the dev Mac without any manual setup.
enum API {
    static var backendURL: String {
        if let override = UserDefaults.standard.string(forKey: "backend_url"),
           !override.trimmingCharacters(in: .whitespaces).isEmpty {
            return override
        }
        return BackendConfig.defaultURL
    }
}

struct IncidentEvent: Decodable {
    var event_id: String?
    var incident_id: String?
    var node_id: String?
    var tier: Int?
    var tier_name: String?
    var one_line_summary: String?
    var suspect_description: String?
    var scene: String?
    var timestamp: Double?
    var behavior_pattern: String?
}

struct StreamResult: Decodable {
    var tier: Int?
    var tier_label: String?
    var actions: [String]?
    var duplicate: Bool?
}

struct StreamMessage: Decodable {
    var event: IncidentEvent?
    var result: StreamResult?
}

struct CameraEntry: Decodable, Identifiable, Hashable {
    var node_id: String
    var name: String
    var stream_url: String
    var status: String
    var pid: Int?
    var started_at: Double?
    var ready_at: Double?
    var id: String { node_id }
}

func tierFromName(_ name: String?) -> Tier {
    switch (name ?? "").lowercased() {
    case "emergency": return .emergency
    case "alert":     return .alert
    case "notice":    return .notice
    default:          return .ambient
    }
}

enum NodeStatus { case live, idle, alert }

func statusFromEntry(_ s: String) -> NodeStatus {
    switch s {
    case "running": return .live
    case "crashed": return .alert
    default:        return .idle
    }
}

func formatTime(_ ts: Double?) -> String {
    guard let ts = ts else { return "--:--" }
    let d = Date(timeIntervalSince1970: ts)
    let f = DateFormatter()
    f.dateFormat = "HH:mm"
    return f.string(from: d)
}

func fetchCameras() async -> [CameraEntry] {
    guard let url = URL(string: "\(API.backendURL)/api/cameras") else { return [] }
    do {
        let (data, resp) = try await URLSession.shared.data(from: url)
        guard let http = resp as? HTTPURLResponse, http.statusCode == 200 else { return [] }
        return (try? JSONDecoder().decode([CameraEntry].self, from: data)) ?? []
    } catch {
        return []
    }
}

struct DiscoveredCamera: Decodable, Identifiable, Hashable {
    var name: String
    var host: String
    var port: Int
    var stream_url: String
    var source_protocol: String?
    var id: String { stream_url }
}

func fetchDiscoveredCameras(timeout: Double = 3.0) async -> [DiscoveredCamera] {
    guard let url = URL(string: "\(API.backendURL)/api/discover?timeout=\(timeout)") else { return [] }
    var req = URLRequest(url: url)
    req.timeoutInterval = timeout + 5
    do {
        let (data, resp) = try await URLSession.shared.data(for: req)
        guard let http = resp as? HTTPURLResponse, http.statusCode == 200 else { return [] }
        return (try? JSONDecoder().decode([DiscoveredCamera].self, from: data)) ?? []
    } catch {
        return []
    }
}

@discardableResult
func addCamera(name: String, streamUrl: String) async -> CameraEntry? {
    guard let url = URL(string: "\(API.backendURL)/api/cameras/add") else { return nil }
    var req = URLRequest(url: url)
    req.httpMethod = "POST"
    req.setValue("application/json", forHTTPHeaderField: "Content-Type")
    req.httpBody = try? JSONSerialization.data(withJSONObject: ["name": name, "stream_url": streamUrl])
    do {
        let (data, resp) = try await URLSession.shared.data(for: req)
        guard let http = resp as? HTTPURLResponse, (200..<300).contains(http.statusCode) else { return nil }
        return try? JSONDecoder().decode(CameraEntry.self, from: data)
    } catch {
        return nil
    }
}
