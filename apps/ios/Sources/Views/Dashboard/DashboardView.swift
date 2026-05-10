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
            Maroon.m950.ignoresSafeArea()
            Aurora().opacity(0.85)

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

    // MARK: - Hero

    private var hero: some View {
        ZStack(alignment: .topLeading) {
            // hero card aurora
            RoundedRectangle(cornerRadius: 26, style: .continuous)
                .fill(Maroon.m900.opacity(0.30))
            Aurora().clipShape(RoundedRectangle(cornerRadius: 26, style: .continuous))

            VStack(alignment: .leading, spacing: 14) {
                HStack(spacing: 6) {
                    Image(systemName: "shield.checkered")
                        .font(.system(size: 11, weight: .bold))
                    Text("OPERATOR CONSOLE · ALL SYSTEMS LOCAL")
                        .font(.teCaps).tracking(2.4)
                }
                .foregroundStyle(Maroon.m200.opacity(0.95))

                heroHeadline

                Text("Four cameras streaming. Frames are analyzed on this device, never uploaded. The brain only sees structured event records.")
                    .font(.system(size: 15.5, weight: .regular))
                    .foregroundStyle(Cream.c50.opacity(0.65))
                    .lineSpacing(2)
                    .fixedSize(horizontal: false, vertical: true)

                HStack(spacing: 6) {
                    HeroStat(label: "Cameras online", value: "\(cameras.filter(\.online).count) / \(cameras.count)")
                    HeroStat(label: "Events today", value: "4")
                    HeroStat(label: "Frames uploaded", value: "0", strong: true)
                }
                .padding(.top, 4)
            }
            .padding(24)
        }
        .overlay(
            RoundedRectangle(cornerRadius: 26, style: .continuous)
                .strokeBorder(Maroon.m300.opacity(0.10), lineWidth: 1)
        )
    }

    private var heroHeadline: some View {
        let serif = Font.system(size: 44, weight: .heavy, design: .serif)
        return (
            Text("Everything calm ")
                .font(serif)
                .foregroundStyle(Cream.c50)
            +
            Text("at home.")
                .font(serif)
                .foregroundStyle(Maroon.m100)
        )
        .lineSpacing(-2)
        .fixedSize(horizontal: false, vertical: true)
    }

    // MARK: - Sections

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

// MARK: - Hero stat pill

private struct HeroStat: View {
    let label: String
    let value: String
    var strong: Bool = false

    var body: some View {
        HStack(spacing: 6) {
            Text(label.uppercased())
                .font(.teCaps).tracking(1.6)
                .foregroundStyle(Cream.c50.opacity(strong ? 1.0 : 0.65))
            Text("·").foregroundStyle(Maroon.m200.opacity(0.4))
            Text(value)
                .font(.teCaps).tracking(1.6)
                .foregroundStyle(Cream.c50)
        }
        .padding(.horizontal, 12)
        .padding(.vertical, 5)
        .background(
            Capsule().fill(strong ? Maroon.m200.opacity(0.10) : Maroon.m900.opacity(0.40))
        )
        .overlay(
            Capsule().strokeBorder(strong ? Maroon.m200.opacity(0.40) : Maroon.m300.opacity(0.15), lineWidth: 0.5)
        )
    }
}

// MARK: - Active incident card (Spotlight-flavored)

private struct ActiveIncidentCard: View {
    let incident: Incident

    var body: some View {
        ZStack {
            RoundedRectangle(cornerRadius: 22, style: .continuous)
                .fill(
                    LinearGradient(
                        colors: [Maroon.m700.opacity(0.85), Maroon.m900.opacity(0.95)],
                        startPoint: .topLeading, endPoint: .bottomTrailing
                    )
                )
            // soft cream glow upper-left (Spotlight-style static)
            RadialGradient(
                colors: [Color(hex: "#E5B4BB").opacity(0.18), .clear],
                center: UnitPoint(x: 0.2, y: 0.25),
                startRadius: 0, endRadius: 240
            )
            .clipShape(RoundedRectangle(cornerRadius: 22, style: .continuous))

            VStack(alignment: .leading, spacing: 14) {
                HStack(spacing: 8) {
                    Circle().fill(Maroon.m200).frame(width: 8, height: 8)
                    Text("ACTIVE INCIDENT · \(incident.timeElapsed.uppercased())")
                        .font(.teCaps).tracking(2.0)
                        .foregroundStyle(Maroon.m100)
                }
                Text(incident.summary)
                    .font(.system(size: 26, weight: .heavy, design: .serif))
                    .foregroundStyle(Cream.c50)
                    .lineLimit(3)
                    .fixedSize(horizontal: false, vertical: true)
                Text(incident.suspectDescription)
                    .font(.teH3)
                    .foregroundStyle(Cream.c50.opacity(0.70))
                HStack(spacing: 8) {
                    SeverityBadge(tier: incident.tier, pulsing: true)
                    Chip(text: "CALL HOMEOWNER")
                    Chip(text: "CALL NEIGHBORS")
                }
                .padding(.top, 4)
            }
            .padding(22)
        }
        .overlay(
            RoundedRectangle(cornerRadius: 22, style: .continuous)
                .strokeBorder(Maroon.m100.opacity(0.22), lineWidth: 1)
        )
        .shadow(color: Maroon.m900.opacity(0.6), radius: 30, y: 18)
    }
}

private struct Chip: View {
    let text: String
    var body: some View {
        Text(text)
            .font(.teCaps).tracking(1.4)
            .foregroundStyle(Cream.c50.opacity(0.75))
            .padding(.horizontal, 10)
            .padding(.vertical, 5)
            .background(Capsule().fill(Maroon.m200.opacity(0.10)))
            .overlay(Capsule().strokeBorder(Maroon.m200.opacity(0.20), lineWidth: 0.5))
    }
}

// MARK: - Event row (mini gradient thumbnail)

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
                    .foregroundStyle(Cream.c50)
                    .lineLimit(2)
                    .multilineTextAlignment(.leading)
                Text("\(event.cameraNode) · \(event.timeElapsed)")
                    .font(.teMono)
                    .foregroundStyle(Cream.c50.opacity(0.55))
            }
            Spacer()
            SeverityBadge(tier: event.tier)
        }
        .padding(14)
        .background(
            RoundedRectangle(cornerRadius: 14, style: .continuous)
                .fill(Color.black.opacity(0.30))
        )
        .overlay(
            RoundedRectangle(cornerRadius: 14, style: .continuous)
                .strokeBorder(Maroon.m300.opacity(0.10), lineWidth: 1)
        )
    }
}
