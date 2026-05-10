import SwiftUI

// Mirrors apps/figma-ui/src/app/components/SecurityEye.tsx (simplified — no cursor tracking on iOS).
struct SecurityEye: View {
    var size: CGFloat = 320
    @State private var pulse = false
    @State private var rec = true

    var body: some View {
        let W = size
        let H = size * 0.95
        ZStack {
            // rays bloom
            Circle()
                .fill(Hue.red.opacity(0.18))
                .frame(width: W * 1.6, height: W * 1.6)
                .blur(radius: 30)
                .scaleEffect(pulse ? 1.05 : 0.95)

            VStack(spacing: 0) {
                // ceiling plate
                ZStack {
                    Capsule().fill(Hue.ink).offset(y: 4)
                    Capsule().fill(Hue.cream)
                        .overlay(Capsule().strokeBorder(Hue.ink, lineWidth: 4))
                    Capsule().fill(Hue.shellLight)
                        .frame(width: W * 0.65, height: 5)
                        .offset(y: -2)
                }
                .frame(width: W * 0.9, height: H * 0.16)

                // dome body
                ZStack {
                    Circle().fill(Hue.ink)
                        .offset(x: 8, y: 12)
                    Circle().fill(Hue.cream)
                        .overlay(Circle().strokeBorder(Hue.ink, lineWidth: 5))
                    // bottom shadow plate
                    Ellipse()
                        .fill(Hue.shellShadow)
                        .frame(width: W * 0.6, height: W * 0.32)
                        .offset(y: W * 0.18)
                        .clipShape(Circle().offset(x: 0, y: 0))
                    // top highlight
                    Capsule()
                        .fill(Hue.shellLight)
                        .frame(width: W * 0.34, height: W * 0.10)
                        .rotationEffect(.degrees(-12))
                        .offset(x: -W * 0.1, y: -W * 0.2)

                    // IR LED ring
                    ForEach(0..<16, id: \.self) { i in
                        let a = Double(i) / 16 * .pi * 2
                        let r = W * 0.78 / 2 - 28
                        Circle()
                            .fill(Color(hex: "#5a1520"))
                            .overlay(Circle().strokeBorder(Hue.ink, lineWidth: 1.5))
                            .frame(width: 6, height: 6)
                            .offset(x: cos(a) * r, y: sin(a) * r)
                    }

                    // lens housing
                    ZStack {
                        Circle().fill(Hue.ring)
                            .overlay(Circle().strokeBorder(Hue.ink, lineWidth: 4))
                            .frame(width: W * 0.4, height: W * 0.4)
                        // black lens
                        Circle().fill(Hue.lens)
                            .overlay(Circle().strokeBorder(Hue.ink, lineWidth: 3))
                            .frame(width: W * 0.33, height: W * 0.33)
                        // red dot
                        ZStack {
                            Circle().fill(Hue.hotRed)
                                .shadow(color: Hue.redHi, radius: 8)
                                .shadow(color: Hue.hotRed, radius: 16)
                                .frame(width: W * 0.10, height: W * 0.10)
                            Circle().fill(Hue.redHi)
                                .frame(width: W * 0.045, height: W * 0.045)
                        }
                        // glass crescent
                        Capsule()
                            .fill(Color(hex: "#3a2f33").opacity(0.85))
                            .frame(width: W * 0.13, height: W * 0.05)
                            .rotationEffect(.degrees(-18))
                            .offset(x: -W * 0.05, y: -W * 0.08)
                    }
                }
                .frame(width: W * 0.78, height: W * 0.78)
                .offset(y: -H * 0.04)
            }

        }
        .frame(width: W, height: H)
        .onAppear {
            withAnimation(.easeInOut(duration: 4).repeatForever(autoreverses: true)) {
                pulse.toggle()
            }
            Timer.scheduledTimer(withTimeInterval: 0.9, repeats: true) { _ in
                rec.toggle()
            }
        }
    }
}
