import SwiftUI

struct DashboardView: View {
    @Binding var activeIncident: Incident?
    let cameras: [CameraNode]

    private let columns = [
        GridItem(.flexible(), spacing: 12),
        GridItem(.flexible(), spacing: 12),
    ]

    var body: some View {
        ZStack {
            Theme.bg.ignoresSafeArea()
            Aurora().opacity(0.55)

            ScrollView(showsIndicators: false) {
                VStack(alignment: .leading, spacing: 26) {
                    hero
                    if let incident = activeIncident {
                        ActiveIncidentCard(incident: incident)
                            .transition(.move(edge: .top).combined(with: .opacity))
                    }
                    cameraSection
                    recentSection
                    Spacer(minLength: 100)
                }
                .padding(.horizontal, 22)
                .padding(.top, 16)
            }
        }
    }

    private var hero: some View {
        VStack(alignment: .leading, spacing: 14) {
            HStack(spacing: 6) {
                Image(systemName: "shield.checkered")
                    .font(.system(size: 11, weight: .bold))
                Text("OPERATOR CONSOLE · ALL SYSTEMS LOCAL")
                    .font(.system(size: 10.5, weight: .heavy, design: .monospaced))
                    .tracking(2.4)
            }
            .foregroundStyle(Theme.textMuted)

            heroHeadline

            Text("Four cameras streaming. Frames are analyzed on this device, never uploaded. The brain only sees structured event records.")
                .font(.system(size: 15.5))
                .foregroundStyle(Theme.textMuted)
                .lineSpacing(2)
                .fixedSize(horizontal: false, vertical: true)

            HStack(spacing: 6) {
                HeroStat(label: "Cameras online", value: "\(cameras.filter(\.online).count) / \(cameras.count)")
                HeroStat(label: "Events today", value: "4")
                HeroStat(label: "Frames uploaded", value: "0", strong: true)
            }
            .padding(.top, 4)
        }
    }

    private var heroHeadline: some View {
        let serif = Font.system(size: 44, weight: .semibold, design: .serif)
        return (
            Text("Everything calm ")
                .font(serif)
                .foregroundStyle(Theme.text)
            +
            Text("at home.")
                .font(serif)
                .foregroundStyle(Theme.destructive)
        )
        .lineSpacing(-2)
        .fixedSize(horizontal: false, vertical: true)
    }

    private var cameraSection: some View {
        VStack(alignment: .leading, spacing: 14) {
            SectionHead(eyebrow: "Mesh", title: "Live cameras")
            LazyVGrid(columns: columns, spacing: 12) {
                ForEach(cameras) { node in
                    CameraTile(node: node)
                }
            }
        }
    }

    private var recentSection: some View {
        VStack(alignment: .leading, spacing: 12) {
            SectionHead(eyebrow: "History", title: "Recent events")
            ForEach(Incident.mockHistory) { event in
                EventRow(event: event)
            }
        }
    }
}

private struct HeroStat: View {
    let label: String
    let value: String
    var strong: Bool = false

    var body: some View {
        HStack(spacing: 6) {
            Text(label.uppercased())
                .font(.system(size: 10, weight: .heavy, design: .monospaced))
                .tracking(1.6)
                .foregroundStyle(Theme.textMuted)
            Text("·").foregroundStyle(Theme.textSubtle)
            Text(value)
                .font(.system(size: 10, weight: .heavy, design: .monospaced))
                .tracking(1.6)
                .foregroundStyle(strong ? Theme.destructive : Theme.text)
        }
        .padding(.horizontal, 12)
        .padding(.vertical, 5)
        .background(Capsule().fill(strong ? Theme.destructiveSoft : Theme.muted))
        .overlay(Capsule().strokeBorder(Theme.border, lineWidth: 0.5))
    }
}

private struct ActiveIncidentCard: View {
    let incident: Incident

    var body: some View {
        VStack(alignment: .leading, spacing: 14) {
            HStack(spacing: 8) {
                Circle()
                    .fill(Theme.destructive)
                    .frame(width: 8, height: 8)
                Text("ACTIVE INCIDENT · \(incident.timeElapsed.uppercased())")
                    .font(.system(size: 10.5, weight: .heavy, design: .monospaced))
                    .tracking(2.0)
                    .foregroundStyle(Theme.destructive)
            }
            Text(incident.summary)
                .font(.system(size: 26, weight: .semibold, design: .serif))
                .foregroundStyle(Theme.text)
                .lineLimit(3)
                .fixedSize(horizontal: false, vertical: true)
            Text(incident.suspectDescription)
                .font(.system(size: 15))
                .foregroundStyle(Theme.textMuted)
            HStack(spacing: 8) {
                SeverityBadge(tier: incident.tier, pulsing: true)
                Chip(text: "CALL HOMEOWNER")
                Chip(text: "CALL NEIGHBORS")
            }
            .padding(.top, 4)
        }
        .padding(22)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(
            RoundedRectangle(cornerRadius: 22, style: .continuous)
                .fill(Theme.surface)
        )
        .overlay(
            RoundedRectangle(cornerRadius: 22, style: .continuous)
                .strokeBorder(Theme.destructive.opacity(0.40), lineWidth: 1.5)
        )
        .shadow(color: Theme.destructive.opacity(0.20), radius: 26, y: 8)
    }
}

private struct Chip: View {
    let text: String
    var body: some View {
        Text(text)
            .font(.system(size: 10, weight: .heavy, design: .monospaced))
            .tracking(1.4)
            .foregroundStyle(Theme.textMuted)
            .padding(.horizontal, 10)
            .padding(.vertical, 5)
            .background(Capsule().fill(Theme.muted))
            .overlay(Capsule().strokeBorder(Theme.border, lineWidth: 0.5))
    }
}

private struct EventRow: View {
    let event: Incident

    var body: some View {
        HStack(spacing: 14) {
            Rectangle()
                .fill(
                    LinearGradient(
                        colors: [Color(hex: "#1F050A"), Color(hex: "#5E1521"), Color(hex: "#9A3142")],
                        startPoint: .topLeading, endPoint: .bottomTrailing
                    )
                )
                .frame(width: 64, height: 48)
                .clipShape(RoundedRectangle(cornerRadius: 8, style: .continuous))

            VStack(alignment: .leading, spacing: 4) {
                Text(event.summary)
                    .font(.system(size: 14.5))
                    .foregroundStyle(Theme.text)
                    .lineLimit(2)
                    .multilineTextAlignment(.leading)
                Text("\(event.cameraNode) · \(event.timeElapsed)")
                    .font(.system(size: 11, weight: .medium, design: .monospaced))
                    .foregroundStyle(Theme.textMuted)
            }
            Spacer()
            SeverityBadge(tier: event.tier)
        }
        .padding(14)
        .background(
            RoundedRectangle(cornerRadius: 14, style: .continuous)
                .fill(Theme.surface)
        )
        .overlay(
            RoundedRectangle(cornerRadius: 14, style: .continuous)
                .strokeBorder(Theme.border, lineWidth: 1)
        )
    }
}
