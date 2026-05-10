import Foundation
import SwiftUI
import UIKit

/// One row of the iOS↔web identity contract. Mirrors the JSON the
/// action_router returns from /api/identity and /api/identity/by-code/{code}.
struct Identity: Codable, Equatable {
    var session_id: String
    var code: String
    var name: String
    var email: String
    var device_id: String?
    var status: String
    var created_at: Double?
    var claimed_at: Double?

    var isClaimed: Bool { status == "claimed" }
}

/// Backend warmup signal from /api/warmup. Used by the onboarding screen
/// so the user has a "models are ready" moment before they leave the app.
struct Warmup: Codable {
    var state: String       // "cold" | "warming" | "ready"
    var elapsed_s: Double
    var running: Int?
    var warming: Int?
    var crashed: Int?
}

@MainActor
final class IdentityStore: ObservableObject {
    @Published private(set) var identity: Identity?
    @Published private(set) var warmup: Warmup?
    @Published private(set) var submitting: Bool = false
    @Published private(set) var error: String?

    @AppStorage("identity_json") private var identityJSON: String = ""

    private var pollTask: Task<Void, Never>?
    private var warmupTask: Task<Void, Never>?

    init() {
        if !identityJSON.isEmpty,
           let data = identityJSON.data(using: .utf8),
           let stored = try? JSONDecoder().decode(Identity.self, from: data) {
            self.identity = stored
        }
    }

    /// POST /api/identity. Saves the returned Identity (with code) locally
    /// and starts polling for claim from the web side.
    func submit(name: String, email: String) async -> Bool {
        let trimmedName = name.trimmingCharacters(in: .whitespacesAndNewlines)
        let trimmedEmail = email.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !trimmedName.isEmpty, trimmedEmail.contains("@") else {
            error = "Enter a valid name and email."
            return false
        }
        guard let url = URL(string: "\(API.backendURL)/api/identity") else {
            error = "Bad backend URL."
            return false
        }

        submitting = true; error = nil
        defer { submitting = false }

        let body: [String: Any] = [
            "name": trimmedName,
            "email": trimmedEmail,
            "device_id": UIDevice.current.identifierForVendor?.uuidString ?? "iphone-unknown",
        ]
        var req = URLRequest(url: url)
        req.httpMethod = "POST"
        req.setValue("application/json", forHTTPHeaderField: "Content-Type")
        req.timeoutInterval = 8
        req.httpBody = try? JSONSerialization.data(withJSONObject: body)

        do {
            let (data, resp) = try await URLSession.shared.data(for: req)
            guard let http = resp as? HTTPURLResponse, (200..<300).contains(http.statusCode) else {
                error = "Backend rejected sign-up. Make sure `make run` is up."
                return false
            }
            guard let id = try? JSONDecoder().decode(Identity.self, from: data) else {
                error = "Couldn't parse backend response."
                return false
            }
            identity = id
            persist(id)
            startPolling()
            return true
        } catch {
            self.error = "Couldn't reach backend: \(error.localizedDescription)"
            return false
        }
    }

    /// Resume polling — useful if the app was killed mid-onboarding.
    func startPolling() {
        guard let code = identity?.code, !code.isEmpty else { return }
        pollTask?.cancel()
        pollTask = Task { [weak self] in
            await self?.poll(code: code)
        }
    }

    func stopPolling() {
        pollTask?.cancel()
        pollTask = nil
    }

    private func poll(code: String) async {
        guard let url = URL(string: "\(API.backendURL)/api/identity/by-code/\(code)") else { return }
        var req = URLRequest(url: url)
        req.timeoutInterval = 5
        while !Task.isCancelled {
            if let (data, resp) = try? await URLSession.shared.data(for: req),
               let http = resp as? HTTPURLResponse, http.statusCode == 200,
               let updated = try? JSONDecoder().decode(Identity.self, from: data) {
                identity = updated
                persist(updated)
                if updated.isClaimed {
                    return  // stop polling once web has claimed
                }
            }
            try? await Task.sleep(nanoseconds: 1_500_000_000)
        }
    }

    /// Continuously poll /api/warmup so the onboarding UI can show
    /// "models warming…" → "models ready" while the user is in the form.
    func startWarmup() {
        guard warmupTask == nil else { return }
        warmupTask = Task { [weak self] in
            guard let self else { return }
            while !Task.isCancelled {
                if let url = URL(string: "\(API.backendURL)/api/warmup"),
                   let (data, _) = try? await URLSession.shared.data(from: url),
                   let w = try? JSONDecoder().decode(Warmup.self, from: data) {
                    await MainActor.run { self.warmup = w }
                    if w.state == "ready" { return }
                }
                try? await Task.sleep(nanoseconds: 2_000_000_000)
            }
        }
    }

    func stopWarmup() {
        warmupTask?.cancel()
        warmupTask = nil
    }

    func reset() {
        identity = nil
        warmup = nil
        identityJSON = ""
        stopPolling()
        stopWarmup()
    }

    private func persist(_ id: Identity) {
        if let data = try? JSONEncoder().encode(id),
           let s = String(data: data, encoding: .utf8) {
            identityJSON = s
        }
    }
}
