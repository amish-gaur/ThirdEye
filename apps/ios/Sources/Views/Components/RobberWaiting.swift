import SwiftUI

// Mirrors apps/figma-ui/src/app/components/RobberWaiting.tsx.
struct RobberWaiting: View {
    var message: String = "waiting for live video"
    var height: CGFloat = 220
    @State private var pulse = false
    @State private var sweep: CGFloat = -1
    @State private var dotsTick = 0

    var body: some View {
        ZStack {
            // panel
            RoundedRectangle(cornerRadius: 12, style: .continuous)
                .fill(Hue.sand)
            RoundedRectangle(cornerRadius: 12, style: .continuous)
                .strokeBorder(Hue.ink, lineWidth: 3)

            // sweep
            GeometryReader { geo in
                LinearGradient(
                    colors: [.clear, Hue.ink.opacity(0.06), .clear],
                    startPoint: .leading, endPoint: .trailing
                )
                .frame(width: geo.size.width * 0.4)
                .offset(x: sweep * geo.size.width)
            }
            .clipShape(RoundedRectangle(cornerRadius: 12, style: .continuous))

            // camera glyph in pulsing rings
            ZStack {
                ForEach(0..<3, id: \.self) { i in
                    PulseRing(delay: Double(i) * 0.8)
                }
                ZStack {
                    Circle().fill(Hue.cream)
                    Circle().strokeBorder(Hue.ink, lineWidth: 3)
                    Image(systemName: "video.fill")
                        .font(.system(size: 22, weight: .bold))
                        .foregroundStyle(Hue.ink)
                    Circle()
                        .fill(Hue.red)
                        .frame(width: 8, height: 8)
                        .offset(x: 18, y: -18)
                        .opacity(pulse ? 0.25 : 1)
                        .animation(.easeInOut(duration: 1.2).repeatForever(autoreverses: true), value: pulse)
                }
                .frame(width: 64, height: 64)
                .background(
                    Circle().fill(Hue.ink).offset(y: 4)
                        .frame(width: 64, height: 64)
                )
            }

            // caption
            VStack {
                Spacer()
                HStack(alignment: .firstTextBaseline, spacing: 4) {
                    Text(message)
                        .font(.playfair(18, weight: .black))
                        .italic()
                        .foregroundStyle(Hue.ink)
                    HStack(spacing: 3) {
                        ForEach(0..<3, id: \.self) { i in
                            Circle()
                                .fill(Hue.ink)
                                .frame(width: 5, height: 5)
                                .opacity(dotOpacity(for: i))
                        }
                    }
                }
                .padding(.bottom, 18)
            }

            // corner tags
            VStack {
                HStack {
                    HStack(spacing: 6) {
                        Circle()
                            .fill(Hue.red)
                            .frame(width: 6, height: 6)
                            .opacity(pulse ? 0.2 : 1)
                        Text("SCANNING")
                            .font(.mono(10))
                            .tracking(2)
                            .foregroundStyle(Hue.ink.opacity(0.6))
                    }
                    Spacer()
                    Text("NO SIGNAL")
                        .font(.mono(10))
                        .tracking(2)
                        .foregroundStyle(Hue.ink.opacity(0.5))
                }
                .padding(10)
                Spacer()
            }
        }
        .frame(height: height)
        .onAppear {
            pulse = true
            withAnimation(.linear(duration: 4.2).repeatForever(autoreverses: false)) {
                sweep = 2
            }
            Timer.scheduledTimer(withTimeInterval: 0.35, repeats: true) { _ in
                dotsTick = (dotsTick + 1) % 3
            }
        }
    }

    private func dotOpacity(for i: Int) -> Double {
        i == dotsTick ? 1.0 : 0.25
    }
}

private struct PulseRing: View {
    let delay: Double
    @State private var ramp = false

    var body: some View {
        Circle()
            .strokeBorder(Hue.ink, lineWidth: 2)
            .frame(width: 84, height: 84)
            .scaleEffect(ramp ? 1.9 : 1.0)
            .opacity(ramp ? 0 : 0.22)
            .onAppear {
                withAnimation(.easeOut(duration: 2.4).repeatForever(autoreverses: false).delay(delay)) {
                    ramp = true
                }
            }
    }
}
