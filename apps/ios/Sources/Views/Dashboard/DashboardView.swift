import SwiftUI

// Mirrors the Dashboard function in apps/figma-ui/src/app/App.tsx.
struct Dashboard: View {
    @EnvironmentObject var incidents: IncidentStream
    @EnvironmentObject var cameras: CamerasStore
    @EnvironmentObject var identity: IdentityStore

    var body: some View {
        VStack(alignment: .leading, spacing: 18) {
            hero
            // Surface the pairing code on the home view so the user can read
            // it off the phone whenever — not just during the handoff step.
            // Auto-hides once the web claims it.
            if let id = identity.identity, !id.isClaimed {
                pairingBanner(code: id.code)
            }
            SecurityEye(size: 160)
                .frame(maxWidth: .infinity, alignment: .center)

            // incident feed card
            Card(corner: 18) {
                VStack(spacing: 0) {
                    HStack {
                        HStack(spacing: 10) {
                            Circle()
                                .fill(Hue.red)
                                .overlay(Circle().strokeBorder(Hue.ink, lineWidth: 2))
                                .frame(width: 12, height: 12)
                            Text("INCIDENT FEED · LAST 24H")
                                .font(.mono(11))
                                .tracking(3)
                                .foregroundStyle(Hue.ink)
                        }
                        Spacer()
                        Text(summaryLine)
                            .font(.mono(10))
                            .tracking(1.5)
                            .foregroundStyle(Hue.ink)
                            .lineLimit(1)
                    }
                    .padding(.horizontal, 14).padding(.vertical, 10)
                    .background(Hue.gold)
                    .overlay(alignment: .bottom) {
                        Rectangle().fill(Hue.ink).frame(height: 4)
                    }

                    if incidents.items.isEmpty {
                        Text("AWAITING EVENTS · STREAM CONNECTED")
                            .font(.mono(11)).tracking(2)
                            .foregroundStyle(Hue.deep.opacity(0.7))
                            .frame(maxWidth: .infinity, alignment: .leading)
                            .padding(.horizontal, 14).padding(.vertical, 18)
                    } else {
                        VStack(spacing: 0) {
                            ForEach(Array(incidents.items.enumerated()), id: \.element.id) { idx, row in
                                IncidentRow(row: row, delay: 0.05 * Double(min(idx, 5)))
                            }
                        }
                    }
                }
            }

            // nodes card
            Card(corner: 18) {
                VStack(alignment: .leading, spacing: 12) {
                    HStack(spacing: 8) {
                        Image(systemName: "dot.radiowaves.left.and.right")
                            .font(.system(size: 12, weight: .bold))
                        Text("NODES · \(cameras.cameras.count) ACTIVE")
                            .font(.mono(11)).tracking(3)
                    }
                    .foregroundStyle(Hue.ink)

                    if cameras.cameras.isEmpty {
                        Text("NO CAMERAS REGISTERED")
                            .font(.mono(10)).tracking(2)
                            .foregroundStyle(Hue.deep.opacity(0.7))
                    } else {
                        ForEach(Array(cameras.cameras.enumerated()), id: \.element.id) { idx, c in
                            NodeRow(
                                id: c.node_id.uppercased(),
                                loc: c.name.uppercased(),
                                status: statusFromEntry(c.status),
                                delay: 0.05 * Double(idx)
                            )
                        }
                    }
                }
                .padding(16)
            }

        }
    }

    private var hero: some View {
        VStack(alignment: .leading, spacing: 10) {
            HStack(spacing: 6) {
                Image(systemName: "shield.checkered")
                    .font(.system(size: 10, weight: .bold))
                Text("ALL SYSTEMS LOCAL")
                    .font(.mono(9))
                    .tracking(2.5)
            }
            .foregroundStyle(Hue.deep)

            VStack(alignment: .leading, spacing: -2) {
                EyeText(text: "Everything", size: 30)
                HStack(alignment: .firstTextBaseline, spacing: 6) {
                    EyeText(text: "calm at", size: 30)
                    Text("home.")
                        .font(.playfair(30, weight: .heavy))
                        .italic()
                        .foregroundStyle(Hue.red)
                }
            }

            Text("Severity-aware sensors. Frames stay on-device.")
                .font(.system(size: 13))
                .foregroundStyle(Hue.deep)
                .lineSpacing(2)
                .fixedSize(horizontal: false, vertical: true)
        }
    }

    private var summaryLine: String {
        let counts = Dictionary(grouping: incidents.items, by: { $0.tier }).mapValues(\.count)
        return "\(incidents.items.count) EVENTS · \(counts[.emergency] ?? 0) EMERGENCY · \(counts[.alert] ?? 0) ALERTS"
    }

    /// Persistent reminder of the 6-character pairing code so the user can
    /// type it on the web app from the home view (not just during the
    /// handoff step). Disappears the moment `/api/identity` poll reports
    /// `claimed`.
    private func pairingBanner(code: String) -> some View {
        VStack(alignment: .leading, spacing: 8) {
            HStack(spacing: 6) {
                Image(systemName: "link")
                    .font(.system(size: 10, weight: .bold))
                Text("PAIR WEB · TYPE THIS AT LOCALHOST:5173")
                    .font(.mono(9))
                    .tracking(2)
            }
            .foregroundStyle(Hue.cream)

            HStack(spacing: 12) {
                Text(code)
                    .font(.system(size: 28, weight: .black, design: .monospaced))
                    .tracking(6)
                    .foregroundStyle(Hue.ink)
                    .padding(.horizontal, 14).padding(.vertical, 10)
                    .background(RoundedRectangle(cornerRadius: 12).fill(Hue.gold))
                    .overlay(RoundedRectangle(cornerRadius: 12).strokeBorder(Hue.ink, lineWidth: 2))

                VStack(alignment: .leading, spacing: 2) {
                    Text("WAITING FOR WEB…")
                        .font(.mono(9)).tracking(1.6)
                        .foregroundStyle(Hue.cream.opacity(0.85))
                    Text("Auto-clears when the web app claims it.")
                        .font(.system(size: 11))
                        .foregroundStyle(Hue.cream.opacity(0.85))
                }
                Spacer()
            }
        }
        .padding(14)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(RoundedRectangle(cornerRadius: 14).fill(Hue.red))
        .overlay(RoundedRectangle(cornerRadius: 14).strokeBorder(Hue.ink, lineWidth: 3))
    }
}
