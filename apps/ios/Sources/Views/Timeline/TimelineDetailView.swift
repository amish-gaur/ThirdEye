import SwiftUI

struct TimelineDetailView: View {
    let event: Incident
    @Environment(\.dismiss) private var dismiss

    var body: some View {
        ZStack {
            Theme.bg.ignoresSafeArea()

            ScrollView(showsIndicators: false) {
                VStack(alignment: .leading, spacing: 22) {
                    HStack {
                        Button(action: { dismiss() }) {
                            HStack(spacing: 6) {
                                Image(systemName: "chevron.left")
                                Text("Timeline").font(.system(size: 17, weight: .semibold))
                            }
                            .foregroundStyle(Theme.text)
                        }
                        Spacer()
                        SeverityBadge(tier: event.tier)
                    }

                    VStack(alignment: .leading, spacing: 10) {
                        Text("EVENT")
                            .font(.system(size: 10.5, weight: .heavy, design: .monospaced))
                            .tracking(2.0)
                            .foregroundStyle(Theme.textMuted)
                        Text(event.summary)
                            .font(.system(size: 28, weight: .semibold, design: .serif))
                            .foregroundStyle(Theme.text)
                            .lineLimit(5)
                            .fixedSize(horizontal: false, vertical: true)
                        HStack(spacing: 8) {
                            Image(systemName: "video.fill")
                                .foregroundStyle(Theme.textMuted)
                            Text("\(event.cameraNode) · \(event.timeElapsed)")
                                .font(.system(size: 13))
                                .foregroundStyle(Theme.textMuted)
                        }
                    }

                    ZStack {
                        LinearGradient(
                            colors: [Color(hex: "#5E1521"), Color(hex: "#1F050A")],
                            startPoint: .topLeading, endPoint: .bottomTrailing
                        )
                        Image(systemName: "play.circle.fill")
                            .font(.system(size: 56))
                            .foregroundStyle(.white.opacity(0.92))
                    }
                    .frame(height: 220)
                    .clipShape(RoundedRectangle(cornerRadius: 18, style: .continuous))

                    DetailSection(title: "SUSPECT", bodyText: event.suspectDescription)
                    DetailSection(title: "SCENE",   bodyText: event.scene)
                    DetailSection(title: "ACTIONS TAKEN", chips: actionsTaken(for: event.tier))

                    HStack(spacing: 12) {
                        Button(action: {}) {
                            Text("Acknowledge")
                                .font(.system(size: 14, weight: .semibold))
                                .foregroundStyle(Theme.text)
                                .frame(maxWidth: .infinity)
                                .padding(.vertical, 14)
                                .background(
                                    RoundedRectangle(cornerRadius: 14, style: .continuous)
                                        .fill(Theme.muted)
                                )
                        }
                        Button(action: {}) {
                            Text("Share")
                                .font(.system(size: 14, weight: .semibold))
                                .foregroundStyle(Theme.primaryFg)
                                .frame(maxWidth: .infinity)
                                .padding(.vertical, 14)
                                .background(
                                    RoundedRectangle(cornerRadius: 14, style: .continuous)
                                        .fill(Theme.primary)
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
                .font(.system(size: 10.5, weight: .heavy, design: .monospaced))
                .tracking(1.6)
                .foregroundStyle(Theme.textMuted)
            if let bodyText = bodyText {
                Text(bodyText)
                    .font(.system(size: 16, weight: .medium))
                    .foregroundStyle(Theme.text)
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
                .fill(Theme.surface)
        )
        .overlay(
            RoundedRectangle(cornerRadius: 16, style: .continuous)
                .strokeBorder(Theme.border, lineWidth: 1)
        )
    }
}

private struct FlexibleChips: View {
    let items: [String]
    var body: some View {
        HStack(alignment: .top) {
            VStack(alignment: .leading, spacing: 6) {
                ForEach(chunked(), id: \.self) { row in
                    HStack(spacing: 6) {
                        ForEach(row, id: \.self) { chip in
                            Text(chip)
                                .font(.system(size: 10, weight: .heavy, design: .monospaced))
                                .tracking(1.2)
                                .foregroundStyle(Theme.text)
                                .padding(.horizontal, 10)
                                .padding(.vertical, 5)
                                .background(Capsule().fill(Theme.muted))
                                .overlay(Capsule().strokeBorder(Theme.border, lineWidth: 0.5))
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
