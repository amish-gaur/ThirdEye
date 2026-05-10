import Foundation
import SwiftUI

/// Polls the action router's `/health` endpoint so the UI can show a
/// live "READY" badge and react to the backend coming up / dropping out.
@MainActor
final class BackendStatus: ObservableObject {
    enum State { case connecting, live, offline }

    @Published private(set) var state: State = .connecting
    @Published private(set) var publicBaseURL: String? = nil
    @Published private(set) var twilioConfigured: Bool = false
    @Published private(set) var elevenlabsEnabled: Bool = false

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
        while !Task.isCancelled {
            await poll()
            try? await Task.sleep(nanoseconds: 2_500_000_000)
        }
    }

    private func poll() async {
        guard let url = URL(string: "\(API.backendURL)/health") else {
            state = .offline
            return
        }
        var req = URLRequest(url: url)
        req.timeoutInterval = 2.5
        req.cachePolicy = .reloadIgnoringLocalAndRemoteCacheData
        do {
            let (data, resp) = try await URLSession.shared.data(for: req)
            guard let http = resp as? HTTPURLResponse, http.statusCode == 200 else {
                state = .offline
                return
            }
            if let json = try? JSONSerialization.jsonObject(with: data) as? [String: Any] {
                publicBaseURL = json["public_base_url"] as? String
                twilioConfigured = (json["twilio_configured"] as? Bool) ?? false
                elevenlabsEnabled = (json["elevenlabs_play_enabled"] as? Bool) ?? false
            }
            state = .live
        } catch {
            state = .offline
        }
    }
}
