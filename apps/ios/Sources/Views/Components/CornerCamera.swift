import SwiftUI

// Mirrors apps/figma-ui/src/app/components/CornerCamera.tsx (simplified static iOS version).
struct CornerCamera: View {
    var size: CGFloat = 110
    @State private var pan: Double = -6

    var body: some View {
        let W = size
        let H = size * 0.95
        ZStack(alignment: .topTrailing) {
            // wall plate
            RoundedRectangle(cornerRadius: 6, style: .continuous)
                .fill(Hue.cream)
                .overlay(
                    RoundedRectangle(cornerRadius: 6, style: .continuous)
                        .strokeBorder(Hue.ink, lineWidth: 3)
                )
                .frame(width: 22, height: 22)
                .background(
                    RoundedRectangle(cornerRadius: 6).fill(Hue.ink)
                        .offset(x: 2, y: 3)
                )

            // mount arm
            RoundedRectangle(cornerRadius: 4)
                .fill(Hue.shellShadow)
                .overlay(RoundedRectangle(cornerRadius: 4).strokeBorder(Hue.ink, lineWidth: 3))
                .frame(width: 28, height: 8)
                .rotationEffect(.degrees(-18), anchor: .trailing)
                .offset(x: -22, y: 18)

            // body
            ZStack {
                Capsule().fill(Hue.ink).offset(x: 4, y: 5)
                Capsule().fill(Hue.cream)
                    .overlay(Capsule().strokeBorder(Hue.ink, lineWidth: 3))
                // sun-shade lip
                Capsule().fill(Hue.shellShadow)
                    .frame(width: W * 0.18)
                    .frame(maxWidth: .infinity, alignment: .leading)
                    .clipShape(Capsule())

                // lens
                ZStack {
                    Circle().fill(Hue.ring)
                        .overlay(Circle().strokeBorder(Hue.ink, lineWidth: 3))
                    Circle().fill(Hue.lens)
                        .overlay(Circle().strokeBorder(Hue.ink, lineWidth: 2))
                        .padding(4)
                    Circle().fill(Hue.hotRed)
                        .shadow(color: Hue.redHi, radius: 4)
                        .frame(width: H * 0.16, height: H * 0.16)
                }
                .frame(width: H * 0.42, height: H * 0.42)
                .frame(maxWidth: .infinity, alignment: .leading)
                .offset(x: -2)

                // tiny REC LED
                Circle().fill(Hue.hotRed)
                    .overlay(Circle().strokeBorder(Hue.ink, lineWidth: 1.5))
                    .frame(width: 6, height: 6)
                    .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .topTrailing)
                    .offset(x: -W * 0.22, y: 4)
            }
            .frame(width: W * 0.78, height: H * 0.5)
            .rotationEffect(.degrees(pan), anchor: .trailing)
            .offset(x: -4, y: 28)
        }
        .frame(width: W, height: H)
        .onAppear {
            withAnimation(.easeInOut(duration: 5).repeatForever(autoreverses: true)) {
                pan = 6
            }
        }
    }
}
