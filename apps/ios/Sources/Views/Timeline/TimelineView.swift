import SwiftUI

// Mirrors the Timeline function in apps/figma-ui/src/app/App.tsx.
struct TimelineView: View {
    @EnvironmentObject var incidents: IncidentStream

    var body: some View {
        VStack(alignment: .leading, spacing: 20) {
            SectionHeader(title: "Timeline", sub: "Filter by tier · the last calm minute is what matters")
            Card(corner: 18) {
                if incidents.items.isEmpty {
                    Text("AWAITING EVENTS · STREAM CONNECTED")
                        .font(.mono(11)).tracking(2)
                        .foregroundStyle(Hue.deep.opacity(0.7))
                        .frame(maxWidth: .infinity, alignment: .leading)
                        .padding(.horizontal, 14).padding(.vertical, 18)
                } else {
                    VStack(spacing: 0) {
                        ForEach(Array(incidents.items.enumerated()), id: \.element.id) { idx, row in
                            IncidentRow(row: row, delay: 0.04 * Double(min(idx, 5)))
                        }
                    }
                }
            }
        }
    }
}
