import SwiftUI

// Mirrors apps/figma-ui/src/app/components/AmbientBg.tsx.
struct AmbientBg: View {
    @State private var driftA: CGSize = .zero
    @State private var driftB: CGSize = .zero
    @State private var moteRise = false

    var body: some View {
        ZStack {
            RadialGradient(
                colors: [Hue.wine.opacity(0.10), .clear],
                center: UnitPoint(x: 0.20, y: 0.80),
                startRadius: 0, endRadius: 360
            )
            .offset(driftA)
            RadialGradient(
                colors: [Hue.gold.opacity(0.10), .clear],
                center: UnitPoint(x: 0.80, y: 0.20),
                startRadius: 0, endRadius: 380
            )
            .offset(driftB)

            ForEach(0..<18, id: \.self) { i in
                let leftPct = CGFloat((i * 53) % 100) / 100
                let topPct = CGFloat((i * 31) % 100) / 100
                let dur = Double(18 + (i % 6) * 3)
                Mote(leftPct: leftPct, topPct: topPct, duration: dur, delay: Double(i) * 0.4)
            }
        }
        .ignoresSafeArea()
        .allowsHitTesting(false)
        .onAppear {
            withAnimation(.easeInOut(duration: 24).repeatForever(autoreverses: true)) {
                driftA = CGSize(width: 30, height: 10)
            }
            withAnimation(.easeInOut(duration: 28).repeatForever(autoreverses: true)) {
                driftB = CGSize(width: -20, height: -10)
            }
        }
    }
}

private struct Mote: View {
    let leftPct: CGFloat
    let topPct: CGFloat
    let duration: Double
    let delay: Double
    @State private var rise = false

    var body: some View {
        GeometryReader { geo in
            Circle()
                .fill(Hue.wine.opacity(rise ? 0 : 0.35))
                .frame(width: 3, height: 3)
                .position(
                    x: leftPct * geo.size.width,
                    y: topPct * geo.size.height + (rise ? -40 : 0)
                )
                .animation(
                    .easeInOut(duration: duration).repeatForever(autoreverses: true).delay(delay),
                    value: rise
                )
                .onAppear { rise.toggle() }
        }
    }
}
