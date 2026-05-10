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
            Theme.bg.ignoresSafeArea()

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

    private var header: some View {
        VStack(alignment: .leading, spacing: 6) {
            Text("TIMELINE")
                .font(.system(size: 10.5, weight: .heavy, design: .monospaced))
                .tracking(2.4)
                .foregroundStyle(Theme.textMuted)
            Text("What happened.")
                .font(.system(size: 40, weight: .semibold, design: .serif))
                .foregroundStyle(Theme.text)
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
                        .font(.system(size: 10.5, weight: .heavy, design: .monospaced))
                        .tracking(2.2)
                        .foregroundStyle(Theme.textMuted)
                    VStack(spacing: 8) {
                        ForEach(items) { event in
                            Button { selected = event } label: { row(event) }
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
                .font(.system(size: 17, weight: .semibold))
                .foregroundStyle(Theme.text)
            Text("Tap All to see everything.")
                .font(.system(size: 13))
                .foregroundStyle(Theme.textMuted)
        }
        .frame(maxWidth: .infinity, alignment: .center)
        .padding(.vertical, 40)
    }

    private func row(_ event: Incident) -> some View {
        HStack(spacing: 14) {
            Text(event.timeElapsed.uppercased())
                .font(.system(size: 11, weight: .medium, design: .monospaced))
                .foregroundStyle(Theme.textMuted)
                .frame(width: 80, alignment: .leading)
            VStack(alignment: .leading, spacing: 2) {
                Text(event.summary)
                    .font(.system(size: 14.5))
                    .foregroundStyle(Theme.text)
                    .lineLimit(2)
                    .multilineTextAlignment(.leading)
                Text("\(event.scene) · \(event.cameraNode)")
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

    private func grouped() -> [(String, [Incident])] {
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
                .foregroundStyle(active ? Theme.primaryFg : Theme.text)
                .padding(.horizontal, 14)
                .padding(.vertical, 6)
                .background(Capsule().fill(active ? Theme.primary : Theme.surface))
                .overlay(Capsule().strokeBorder(active ? Color.clear : Theme.border, lineWidth: 1))
        }
        .buttonStyle(.plain)
    }
}
