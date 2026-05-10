import Foundation
import Combine
import SwiftUI

struct IncidentRowData: Identifiable, Hashable {
    let id = UUID()
    let tier: Tier
    let title: String
    let node: String
    let time: String
}

@MainActor
final class IncidentStream: ObservableObject {
    @Published private(set) var items: [IncidentRowData] = []
    private var task: Task<Void, Never>?

    func start() {
        guard task == nil else { return }
        task = Task { await loop() }
    }

    func stop() {
        task?.cancel()
        task = nil
    }

    private func loop() async {
        // Auto-reconnect on failure, like EventSource.
        while !Task.isCancelled {
            await connect()
            try? await Task.sleep(nanoseconds: 1_500_000_000)
        }
    }

    private func connect() async {
        guard let url = URL(string: "\(API.backendURL)/events/stream") else { return }
        var req = URLRequest(url: url)
        req.setValue("text/event-stream", forHTTPHeaderField: "Accept")
        req.timeoutInterval = .infinity
        do {
            let (bytes, _) = try await URLSession.shared.bytes(for: req)
            for try await line in bytes.lines {
                if Task.isCancelled { return }
                guard line.hasPrefix("data:") else { continue }
                let raw = String(line.dropFirst(5)).trimmingCharacters(in: .whitespaces)
                guard let data = raw.data(using: .utf8) else { continue }
                guard let parsed = try? JSONDecoder().decode(StreamMessage.self, from: data) else { continue }
                if parsed.result?.duplicate == true { continue }
                let ev = parsed.event ?? IncidentEvent()
                let scene = (ev.scene ?? "").uppercased()
                let nodeText = "\(ev.node_id ?? "NODE-?")\(scene.isEmpty ? "" : " · \(scene)")"
                let row = IncidentRowData(
                    tier: tierFromName(parsed.result?.tier_label ?? ev.tier_name),
                    title: ev.one_line_summary ?? ev.suspect_description ?? "(no summary)",
                    node: nodeText,
                    time: formatTime(ev.timestamp)
                )
                items.insert(row, at: 0)
                if items.count > 50 { items = Array(items.prefix(50)) }
            }
        } catch {
            // EventSource auto-reconnects; loop() will retry.
        }
    }
}

@MainActor
final class CamerasStore: ObservableObject {
    @Published private(set) var cameras: [CameraEntry] = []
    private var timer: Task<Void, Never>?

    func start() {
        guard timer == nil else { return }
        timer = Task {
            while !Task.isCancelled {
                let list = await fetchCameras()
                cameras = list
                try? await Task.sleep(nanoseconds: 5_000_000_000)
            }
        }
    }

    func stop() {
        timer?.cancel()
        timer = nil
    }
}
