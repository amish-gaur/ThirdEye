import SwiftUI

struct SettingsView: View {
    @EnvironmentObject var cameras: CamerasStore
    @State private var toggles: [Bool] = [false, true, true, true]
    @State private var discovered: [DiscoveredCamera] = []
    @State private var scanning = false
    @State private var statusMsg: String? = nil
    @AppStorage("backend_url") private var backendURL: String = "http://127.0.0.1:8001"

    private let labels = [
        "Notify on Notice",
        "Outbound call on Alert",
        "Neighbor IVR on Emergency",
        "Keep frames local-only",
    ]

    var body: some View {
        VStack(alignment: .leading, spacing: 22) {
            SectionHeader(title: "Settings", sub: "Routing · contacts · LAN cameras")

            // Backend URL editor
            Card(corner: 16) {
                VStack(alignment: .leading, spacing: 6) {
                    Text("BACKEND")
                        .font(.mono(10)).tracking(2)
                        .foregroundStyle(Hue.deep)
                    TextField("http://127.0.0.1:8001", text: $backendURL)
                        .textInputAutocapitalization(.never)
                        .autocorrectionDisabled()
                        .font(.mono(12))
                        .foregroundStyle(Hue.ink)
                        .padding(.vertical, 4)
                }
                .padding(14)
                .frame(maxWidth: .infinity, alignment: .leading)
            }

            // LAN discovery
            Card(corner: 16) {
                VStack(alignment: .leading, spacing: 10) {
                    HStack {
                        Text("LAN CAMERAS")
                            .font(.mono(10)).tracking(2)
                            .foregroundStyle(Hue.deep)
                        Spacer()
                        Button(action: scan) {
                            Text(scanning ? "SCANNING…" : "SCAN")
                                .font(.mono(10)).tracking(2)
                                .foregroundStyle(Hue.cream)
                                .padding(.horizontal, 10).padding(.vertical, 5)
                                .background(Capsule().fill(Hue.red))
                                .overlay(Capsule().strokeBorder(Hue.ink, lineWidth: 2))
                        }
                        .buttonStyle(.plain)
                        .disabled(scanning)
                    }

                    if discovered.isEmpty {
                        Text(scanning ? "BROWSING _safewatch._tcp.local…" : "TAP SCAN TO BROWSE mDNS")
                            .font(.mono(10)).tracking(1.5)
                            .foregroundStyle(Hue.deep.opacity(0.7))
                            .padding(.vertical, 4)
                    } else {
                        ForEach(discovered) { cam in
                            DiscoveredRow(cam: cam) { Task { await add(cam) } }
                        }
                    }

                    if let msg = statusMsg {
                        Text(msg)
                            .font(.mono(10)).tracking(1.5)
                            .foregroundStyle(Hue.wine)
                    }
                }
                .padding(14)
                .frame(maxWidth: .infinity, alignment: .leading)
            }

            // Routing toggles
            VStack(spacing: 10) {
                ForEach(Array(labels.enumerated()), id: \.offset) { idx, label in
                    Card(corner: 16) {
                        HStack {
                            Text(label.uppercased())
                                .font(.mono(11))
                                .tracking(1.4)
                                .foregroundStyle(Hue.ink)
                            Spacer()
                            ToggleSwitch(on: Binding(
                                get: { toggles[idx] },
                                set: { toggles[idx] = $0 }
                            ))
                        }
                        .padding(.horizontal, 14).padding(.vertical, 12)
                    }
                }
            }
        }
    }

    private func scan() {
        scanning = true
        statusMsg = nil
        Task {
            let list = await fetchDiscoveredCameras(timeout: 3.0)
            await MainActor.run {
                discovered = list
                scanning = false
                if list.isEmpty { statusMsg = "No cameras advertising on this LAN." }
            }
        }
    }

    private func add(_ cam: DiscoveredCamera) async {
        let entry = await addCamera(name: cam.name, streamUrl: cam.stream_url)
        await MainActor.run {
            statusMsg = entry == nil ? "Failed to add \(cam.name)." : "Added \(entry!.name)."
        }
    }
}

private struct DiscoveredRow: View {
    let cam: DiscoveredCamera
    let onAdd: () -> Void

    var body: some View {
        HStack {
            VStack(alignment: .leading, spacing: 2) {
                Text(cam.name)
                    .font(.system(size: 13, weight: .semibold))
                    .foregroundStyle(Hue.ink)
                Text("\(cam.host):\(cam.port)")
                    .font(.mono(10))
                    .foregroundStyle(Hue.deep.opacity(0.8))
            }
            Spacer()
            Button(action: onAdd) {
                Text("ADD")
                    .font(.mono(10)).tracking(2)
                    .foregroundStyle(Hue.ink)
                    .padding(.horizontal, 8).padding(.vertical, 4)
                    .background(Capsule().fill(Hue.gold))
                    .overlay(Capsule().strokeBorder(Hue.ink, lineWidth: 2))
            }
            .buttonStyle(.plain)
        }
        .padding(.vertical, 4)
    }
}

private struct ToggleSwitch: View {
    @Binding var on: Bool
    var body: some View {
        Button { on.toggle() } label: {
            ZStack {
                Capsule()
                    .fill(on ? Hue.red : Color(hex: "#cfc4a6"))
                    .overlay(Capsule().strokeBorder(Hue.ink, lineWidth: 3))
                Circle()
                    .fill(Hue.cream)
                    .overlay(Circle().strokeBorder(Hue.ink, lineWidth: 2))
                    .frame(width: 20, height: 20)
                    .offset(x: on ? 12 : -12)
            }
            .frame(width: 56, height: 28)
        }
        .buttonStyle(.plain)
    }
}
