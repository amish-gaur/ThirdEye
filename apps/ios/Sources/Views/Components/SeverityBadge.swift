import SwiftUI

struct SeverityBadge: View {
    let tier: Tier
    var pulsing: Bool = false

    @State private var pulse: Bool = false

    var body: some View {
        HStack(spacing: 8) {
            Circle()
                .fill(tier.dot)
                .frame(width: 8, height: 8)
                .scaleEffect(pulse && pulsing ? 1.3 : 1.0)
                .opacity(pulse && pulsing ? 0.55 : 1.0)
                .animation(
                    pulsing
                        ? .easeInOut(duration: 1.0).repeatForever(autoreverses: true)
                        : .default,
                    value: pulse
                )
                .onAppear { if pulsing { pulse = true } }
            Text(tier.label)
                .font(.teCaps)
                .tracking(1.4)
                .foregroundStyle(tier.fg)
        }
        .padding(.horizontal, 10)
        .padding(.vertical, 6)
        .background(
            RoundedRectangle(cornerRadius: 999, style: .continuous)
                .fill(tier.bg)
        )
        .overlay(
            RoundedRectangle(cornerRadius: 999, style: .continuous)
                .strokeBorder(tier.dot.opacity(0.25), lineWidth: 0.5)
        )
    }
}
