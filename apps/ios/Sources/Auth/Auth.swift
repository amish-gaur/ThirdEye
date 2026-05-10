import Foundation
import SwiftUI
import AVFoundation
import UserNotifications
import CommonCrypto

// Local-only PIN auth. Never leaves the device.
@MainActor
final class AuthStore: ObservableObject {
    @AppStorage("onboarded") var onboarded: Bool = false
    @AppStorage("pin_hash")  var pinHash: String = ""

    @Published var unlocked: Bool = false

    var hasPIN: Bool { !pinHash.isEmpty }

    func setPIN(_ pin: String) { pinHash = Self.sha256(pin) }

    func verify(_ pin: String) -> Bool {
        !pinHash.isEmpty && Self.sha256(pin) == pinHash
    }

    func resetForDemo() {
        onboarded = false
        pinHash = ""
        unlocked = false
    }

    private static func sha256(_ s: String) -> String {
        let bytes = Array(s.utf8)
        var hash = [UInt8](repeating: 0, count: 32)
        bytes.withUnsafeBufferPointer { buf in
            _ = CC_SHA256(buf.baseAddress, CC_LONG(buf.count), &hash)
        }
        return hash.map { String(format: "%02x", $0) }.joined()
    }
}

@MainActor
enum Permissions {
    static func requestCamera() async -> Bool {
        await withCheckedContinuation { c in
            AVCaptureDevice.requestAccess(for: .video) { c.resume(returning: $0) }
        }
    }
    static func requestMic() async -> Bool {
        await withCheckedContinuation { c in
            AVCaptureDevice.requestAccess(for: .audio) { c.resume(returning: $0) }
        }
    }
    static func requestNotifications() async -> Bool {
        let center = UNUserNotificationCenter.current()
        return (try? await center.requestAuthorization(options: [.alert, .sound, .badge])) ?? false
    }
    // Triggers iOS's local-network prompt the first time we touch a LAN address.
    static func nudgeLocalNetwork() {
        guard let url = URL(string: "http://224.0.0.251") else { return }
        var req = URLRequest(url: url)
        req.timeoutInterval = 1
        URLSession.shared.dataTask(with: req) { _, _, _ in }.resume()
    }
}
