import SwiftUI

// Mirrors apps/figma-ui/src/app/components/IncidentRow.tsx.
struct IncidentRow: View {
    let row: IncidentRowData
    var delay: Double = 0
    @State private var visible = false
    @State private var pulse = false

    var body: some View {
        HStack(spacing: 14) {
            ZStack {
                Circle()
                    .fill(row.tier.bg)
                    .overlay(Circle().strokeBorder(Hue.ink, lineWidth: 3))
                    .frame(width: 36, height: 36)
                Circle()
                    .fill(row.tier.fg)
                    .frame(width: 8, height: 8)
                    .scaleEffect(pulse ? 1.6 : 1.0)
                    .opacity(pulse ? 0.4 : 1.0)
                    .animation(
                        (row.tier == .alert || row.tier == .emergency)
                            ? .easeInOut(duration: 0.7).repeatForever(autoreverses: true)
                            : .default,
                        value: pulse
                    )
            }

            VStack(alignment: .leading, spacing: 4) {
                HStack(spacing: 10) {
                    Text(row.tier.label)
                        .font(.mono(10))
                        .tracking(2)
                        .foregroundStyle(row.tier.fg)
                        .padding(.horizontal, 6).padding(.vertical, 2)
                        .background(Rectangle().fill(row.tier.bg))
                        .overlay(Rectangle().strokeBorder(Hue.ink, lineWidth: 2))
                    Text(row.node)
                        .font(.mono(11))
                        .foregroundStyle(Hue.wine.opacity(0.9))
                }
                Text(row.title)
                    .font(.playfair(15, weight: .semibold))
                    .foregroundStyle(Hue.ink)
                    .lineLimit(1)
            }

            Spacer(minLength: 8)

            Text(row.time)
                .font(.mono(12))
                .foregroundStyle(Hue.ink)
        }
        .padding(.horizontal, 16).padding(.vertical, 12)
        .overlay(alignment: .bottom) {
            Rectangle().fill(Hue.ink).frame(height: 3)
        }
        .opacity(visible ? 1 : 0)
        .offset(x: visible ? 0 : -16)
        .onAppear {
            withAnimation(.easeOut(duration: 0.35).delay(delay)) { visible = true }
            if row.tier == .alert || row.tier == .emergency { pulse = true }
        }
    }
}
