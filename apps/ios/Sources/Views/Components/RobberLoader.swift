import SwiftUI

// Mirrors apps/figma-ui/src/app/components/RobberLoader.tsx.
struct RobberLoader: View {
    let onDone: () -> Void
    @State private var phase = 0
    @State private var robberX: CGFloat = -60
    @State private var progress: CGFloat = 0

    private let lines = [
        "INITIALIZING NODES",
        "SYNCING EDGE INFERENCE",
        "CALIBRATING THIRD EYE",
        "ALL SYSTEMS LOCAL",
    ]

    var body: some View {
        ZStack {
            Hue.ink.ignoresSafeArea()

            VStack(spacing: 30) {
                // moonlit ground panel
                ZStack(alignment: .bottomLeading) {
                    Rectangle().fill(Color.clear).frame(height: 180)
                    // fence
                    Rectangle().fill(Hue.lens).frame(height: 40)
                        .frame(maxWidth: .infinity, alignment: .bottom)
                    // fence posts
                    GeometryReader { geo in
                        ForEach(0..<24, id: \.self) { i in
                            Rectangle()
                                .fill(Hue.lens)
                                .frame(width: 6, height: 56)
                                .position(x: CGFloat(i) * 22 + 4, y: geo.size.height - 28)
                        }
                    }
                    .frame(height: 180)
                    // robber
                    Robber()
                        .offset(x: robberX, y: -40)
                }
                .frame(width: 520, height: 180)
                .frame(maxWidth: 520)
                .clipped()
                .overlay(
                    Rectangle()
                        .strokeBorder(Hue.wine.opacity(0.4), lineWidth: 1)
                )

                // progress + caption
                VStack(spacing: 10) {
                    GeometryReader { geo in
                        ZStack(alignment: .leading) {
                            Capsule().fill(Hue.deep).frame(height: 4)
                            Capsule()
                                .fill(LinearGradient(
                                    colors: [Hue.wine, Hue.red, Hue.gold],
                                    startPoint: .leading, endPoint: .trailing
                                ))
                                .frame(width: geo.size.width * progress, height: 4)
                        }
                    }
                    .frame(width: 280, height: 4)
                    Text(lines[min(phase, lines.count - 1)])
                        .font(.mono(11))
                        .tracking(3)
                        .foregroundStyle(Hue.gold.opacity(0.7))
                }
            }
        }
        .onAppear {
            withAnimation(.linear(duration: 3.6)) { progress = 1 }
            withAnimation(.linear(duration: 3.8)) { robberX = 540 }
            Timer.scheduledTimer(withTimeInterval: 0.9, repeats: true) { t in
                phase += 1
                if phase >= 4 { t.invalidate() }
            }
            DispatchQueue.main.asyncAfter(deadline: .now() + 3.8) { onDone() }
        }
        .transition(.opacity)
    }
}

private struct Robber: View {
    var body: some View {
        ZStack {
            // body
            Ellipse().fill(Hue.lens).frame(width: 28, height: 36).offset(y: 16)
            // head
            Circle().fill(Hue.lens).frame(width: 22, height: 22).offset(y: -8)
            // mask band
            Rectangle().fill(Color(hex: "#2a0608"))
                .frame(width: 24, height: 6).offset(y: -12)
            // eyes
            HStack(spacing: 7) {
                Circle().fill(Color(hex: "#f1c8a5")).frame(width: 3, height: 3)
                Circle().fill(Color(hex: "#f1c8a5")).frame(width: 3, height: 3)
            }
            .offset(y: -12)
            // loot bag
            Circle()
                .fill(Hue.wine)
                .overlay(Circle().strokeBorder(Color(hex: "#f1c8a5"), lineWidth: 1))
                .frame(width: 18, height: 18)
                .offset(x: 16, y: 14)
        }
        .frame(width: 56, height: 68)
    }
}
