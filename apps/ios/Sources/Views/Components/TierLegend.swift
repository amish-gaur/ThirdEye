import SwiftUI

// Mirrors the TierLegend function in apps/figma-ui/src/app/App.tsx.
struct TierLegend: View {
    private struct Item: Identifiable {
        var id: String { tier.label }
        let tier: Tier
        let label: String
        let desc: String
        let bg: Color
    }
    private let tiers: [Item] = [
        Item(tier: .ambient,   label: "Ambient",   desc: "logged, no notice", bg: Color(hex: "#cfc4a6")),
        Item(tier: .notice,    label: "Notice",    desc: "soft awareness",    bg: Hue.gold),
        Item(tier: .alert,     label: "Alert",     desc: "call + clip",       bg: Hue.orange),
        Item(tier: .emergency, label: "Emergency", desc: "full escalation",   bg: Hue.red),
    ]

    var body: some View {
        let cols = [GridItem(.flexible(), spacing: 10), GridItem(.flexible(), spacing: 10)]
        LazyVGrid(columns: cols, spacing: 10) {
            ForEach(Array(tiers.enumerated()), id: \.element.id) { idx, t in
                Cell(item: t, delay: 0.4 + Double(idx) * 0.1)
            }
        }
    }

    private struct Cell: View {
        let item: Item
        let delay: Double
        @State private var visible = false

        var body: some View {
            VStack(alignment: .leading, spacing: 4) {
                Text(item.label.uppercased())
                    .font(.mono(10)).tracking(2).foregroundStyle(Hue.ink)
                Text(item.desc)
                    .font(.mono(10)).foregroundStyle(Hue.ink.opacity(0.7))
            }
            .frame(maxWidth: .infinity, alignment: .leading)
            .padding(10)
            .background(
                RoundedRectangle(cornerRadius: 8).fill(item.bg)
            )
            .overlay(
                RoundedRectangle(cornerRadius: 8).strokeBorder(Hue.ink, lineWidth: 3)
            )
            .background(
                RoundedRectangle(cornerRadius: 8).fill(Hue.ink).offset(y: 4)
            )
            .opacity(visible ? 1 : 0)
            .offset(y: visible ? 0 : 10)
            .onAppear {
                withAnimation(.easeOut(duration: 0.4).delay(delay)) { visible = true }
            }
        }
    }
}
