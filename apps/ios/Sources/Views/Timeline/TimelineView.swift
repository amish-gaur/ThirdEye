import SwiftUI

struct TimelineView: View {
    @State private var selected: Incident? = nil
    @State private var filter: Tier? = nil

    private var filtered: [Incident] {
        guard let filter = filter else { return Incident.mockHistory }
        return Incident.mockHistory.filter { $0.tier == filter }
    }

    var body: some View {
        ZStack {
            Maroon.m950.ignoresSafeArea()
            Aurora().opacity(0.55)

            ScrollView(showsIndicators: false) {
                VStack(alignment: .leading, spacing: 22) {
                    header.padding(.top, 12)
                    chips
                    if filtered.isEmpty {
                        emptyState
                    } else {
                        sections
                    }
                    Spacer(minLength: 100)
                }
                .padding(.horizontal, 22)
            }
        }
        .sheet(item: $selected) { event in
            TimelineDetailView(event: event)
        }
    }

    // MARK: - Pieces

    private var header: some View {
        VStack(alignment: .leading, spacing: 6) {
            Text("TIMELINE")
                .font(.teCaps).tracking(2.4)
                .foregroundStyle(Maroon.m200.opacity(0.85))
            Text("What happened.")
                .font(.system(size: 40, weight: .heavy, design: .serif))
                .foregroundStyle(Cream.c50)
        }
    }

    private var chips: some View {
        HStack(spacing: 8) {
            FilterChip(text: "All", active: filter == nil) { filter = nil }
            ForEach(Tier.allCases) { t in
                FilterChip(text: "Tier \(t.rawValue)", active: filter == t) {
                    filter = t
                }
            }
        }
    }

    private var sections: some View {
        VStack(alignment: .leading, spacing: 22) {
            ForEach(grouped(), id: \.0) { day, items in
                VStack(alignment: .leading, spacing: 10) {
                    Text(day.uppercased())
                        .font(.teCaps).tracking(2.2)
                        .foregroundStyle(Maroon.m200.opacity(0.70))
                    VStack(spacing: 8) {
                        ForEach(items) { event in
                            Button {
                                selected = event
                            } label: {
                                row(event)
                            }
                            .buttonStyle(.plain)
                        }
                    }
                }
            }
        }
    }

    private var emptyState: some View {
        VStack(spacing: 8) {
            Text("No events at this tier.")
                .font(.teH3)
                .foregroundStyle(Cream.c50.opacity(0.7))
            Text("Tap All to see everything.")
                .font(.teBodySm)
                .foregroundStyle(Maroon.m200)
        }
        .frame(maxWidth: .infinity, alignment: .center)
        .padding(.vertical, 40)
    }

    private func row(_ event: Incident) -> some View {
        HStack(spacing: 14) {
            Text(event.timeElapsed.uppercased())
                .font(.teMono)
                .foregroundStyle(Cream.c50.opacity(0.55))
                .frame(width: 80, alignment: .leading)
            VStack(alignment: .leading, spacing: 2) {
                Text(event.summary)
                    .font(.system(size: 14.5))
                    .foregroundStyle(Cream.c50)
                    .lineLimit(2)
                    .multilineTextAlignment(.leading)
                Text("\(event.scene) · \(event.cameraNode)")
                    .font(.teMono)
                    .foregroundStyle(Cream.c50.opacity(0.50))
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

    private func grouped() -> [(String, [Incident])] {
        // Mock grouping by the timeElapsed string ("2h ago", "yesterday")
        var dict: [String: [Incident]] = [:]
        var order: [String] = []
        for ev in filtered {
            let key = dayLabel(for: ev.timeElapsed)
            if dict[key] == nil { order.append(key) }
            dict[key, default: []].append(ev)
        }
        return order.map { ($0, dict[$0]!) }
    }

    private func dayLabel(for elapsed: String) -> String {
        if elapsed.contains("yesterday") { return "Yesterday" }
        return "Today"
    }
}

private struct FilterChip: View {
    let text: String
    let active: Bool
    let action: () -> Void

    var body: some View {
        Button(action: action) {
            Text(text)
                .font(.system(size: 12, weight: .medium))
                .foregroundStyle(active ? Ink : Cream.c50.opacity(0.75))
                .padding(.horizontal, 14)
                .padding(.vertical, 6)
                .background(
                    Capsule().fill(active ? Cream.c50 : Color.clear)
                )
                .overlay(
                    Capsule().strokeBorder(
                        active ? Color.clear : Maroon.m300.opacity(0.20),
                        lineWidth: 1
                    )
                )
        }
        .buttonStyle(.plain)
    }
}
