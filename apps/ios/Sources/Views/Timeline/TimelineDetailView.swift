import SwiftUI

struct TimelineDetailView: View {
    let event: Incident
    @Environment(\.dismiss) private var dismiss

    var body: some View {
        ZStack {
            Maroon.m950.ignoresSafeArea()
            Aurora().opacity(0.5)

            ScrollView(showsIndicators: false) {
                VStack(alignment: .leading, spacing: 22) {
                    HStack {
                        Button(action: { dismiss() }) {
                            HStack(spacing: 6) {
                                Image(systemName: "chevron.left")
                                Text("Timeline").font(.teH3)
                            }
                            .foregroundStyle(Maroon.m100)
                        }
                        Spacer()
                        SeverityBadge(tier: event.tier)
                    }

                    // Hero summary
                    VStack(alignment: .leading, spacing: 10) {
                        Text("EVENT")
                            .font(.teCaps).tracking(2.0)
                            .foregroundStyle(Maroon.m200)
                        Text(event.summary)
                            .font(.teH1)
                            .foregroundStyle(Cream.c50)
                            .lineLimit(5)
                            .fixedSize(horizontal: false, vertical: true)
                        HStack(spacing: 8) {
                            Image(systemName: "video.fill")
                                .foregroundStyle(Maroon.m200)
                            Text("\(event.cameraNode) · \(event.timeElapsed)")
                                .font(.teBodySm)
                                .foregroundStyle(Maroon.m100)
                        }
                    }
                    .padding(20)
                    .frame(maxWidth: .infinity, alignment: .leading)
                    .background(
                        RoundedRectangle(cornerRadius: 22, style: .continuous)
                            .fill(
                                LinearGradient(
                                    colors: [Maroon.m700.opacity(0.6), Maroon.m900.opacity(0.85)],
                                    startPoint: .topLeading, endPoint: .bottomTrailing
                                )
                            )
                    )

                    // Faux clip thumbnail
                    ZStack {
                        LinearGradient(colors: [Color(hex: "#5E1521"), Color(hex: "#1F050A")], startPoint: .topLeading, endPoint: .bottomTrailing)
                        Image(systemName: "play.circle.fill")
                            .font(.system(size: 56))
                            .foregroundStyle(Cream.c50.opacity(0.92))
                    }
                    .frame(height: 220)
                    .clipShape(RoundedRectangle(cornerRadius: 18, style: .continuous))

                    // Detail sections
                    DetailSection(title: "SUSPECT", bodyText: event.suspectDescription)
                    DetailSection(title: "SCENE",   bodyText: event.scene)
                    DetailSection(title: "ACTIONS TAKEN", chips: actionsTaken(for: event.tier))

                    // Footer actions
                    HStack(spacing: 12) {
                        Button(action: {}) {
                            Text("Acknowledge")
                                .font(.teButton)
                                .foregroundStyle(Cream.c50)
                                .frame(maxWidth: .infinity)
                                .padding(.vertical, 14)
                                .background(
                                    RoundedRectangle(cornerRadius: 14, style: .continuous)
                                        .fill(Maroon.m700)
                                )
                        }
                        Button(action: {}) {
                            Text("Share")
                                .font(.teButton)
                                .foregroundStyle(Ink)
                                .frame(maxWidth: .infinity)
                                .padding(.vertical, 14)
                                .background(
                                    RoundedRectangle(cornerRadius: 14, style: .continuous)
                                        .fill(Cream.c50)
                                )
                        }
                    }
                    Spacer(minLength: 24)
                }
                .padding(.horizontal, 22)
                .padding(.top, 14)
            }
        }
    }

    private func actionsTaken(for tier: Tier) -> [String] {
        switch tier {
        case .ambient:   return ["LOG"]
        case .notice:    return ["SMS HOMEOWNER"]
        case .alert:     return ["CALL HOMEOWNER", "CALL NEIGHBORS", "ELEVENLABS"]
        case .emergency: return ["CALL DISPATCH", "CALL HOMEOWNER", "CALL FAMILY", "CALL NEIGHBORS"]
        }
    }
}

private struct DetailSection: View {
    let title: String
    var bodyText: String? = nil
    var chips: [String]? = nil

    var body: some View {
        VStack(alignment: .leading, spacing: 8) {
            Text(title)
                .font(.teCaps).tracking(1.6)
                .foregroundStyle(Maroon.m200)
            if let bodyText = bodyText {
                Text(bodyText)
                    .font(.teH3)
                    .foregroundStyle(Cream.c50)
                    .fixedSize(horizontal: false, vertical: true)
            }
            if let chips = chips {
                FlexibleChips(items: chips)
            }
        }
        .padding(18)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(
            RoundedRectangle(cornerRadius: 16, style: .continuous)
                .fill(Color.black.opacity(0.30))
        )
        .overlay(
            RoundedRectangle(cornerRadius: 16, style: .continuous)
                .strokeBorder(Maroon.m800, lineWidth: 1)
        )
    }
}

private struct FlexibleChips: View {
    let items: [String]
    var body: some View {
        // simple wrap via HStack; iOS 16+ has Layout but FlowLayout is overkill here
        HStack(alignment: .top) {
            VStack(alignment: .leading, spacing: 6) {
                ForEach(chunked(), id: \.self) { row in
                    HStack(spacing: 6) {
                        ForEach(row, id: \.self) { chip in
                            Text(chip)
                                .font(.teCaps).tracking(1.2)
                                .foregroundStyle(Cream.c50.opacity(0.85))
                                .padding(.horizontal, 10)
                                .padding(.vertical, 5)
                                .background(Capsule().fill(Maroon.m200.opacity(0.10)))
                                .overlay(Capsule().strokeBorder(Maroon.m200.opacity(0.25), lineWidth: 0.5))
                        }
                    }
                }
            }
            Spacer()
        }
    }

    private func chunked() -> [[String]] {
        var rows: [[String]] = []
        var cur: [String] = []
        var len = 0
        for it in items {
            if len + it.count > 26 {
                rows.append(cur); cur = []; len = 0
            }
            cur.append(it); len += it.count
        }
        if !cur.isEmpty { rows.append(cur) }
        return rows
    }
}
