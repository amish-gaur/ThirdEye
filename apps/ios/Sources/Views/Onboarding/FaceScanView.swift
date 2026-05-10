import SwiftUI

// Themed Face-ID-style scanner. Visual only — always succeeds after `duration`.
// Mimics Apple's circular progress ring + face silhouette.
struct FaceScanView: View {
    var duration: Double = 2.4
    var onSuccess: () -> Void

    @State private var progress: CGFloat = 0
    @State private var beam: CGFloat = -1
    @State private var pulse = false
    @State private var done = false

    var body: some View {
        ZStack {
            // outer dotted ring (Apple Face-ID lookalike, themed in ink)
            DottedRing(count: 60, lineWidth: 3, length: 8, radius: 130)
                .foregroundStyle(Hue.ink.opacity(0.35))

            // animated progress arc — sweeps as scan proceeds
            Circle()
                .trim(from: 0, to: progress)
                .stroke(Hue.red, style: StrokeStyle(lineWidth: 5, lineCap: .round))
                .frame(width: 268, height: 268)
                .rotationEffect(.degrees(-90))

            // face silhouette
            FaceSilhouette()
                .stroke(Hue.ink, lineWidth: 3.5)
                .frame(width: 150, height: 180)
                .opacity(done ? 0.0 : 0.9)

            // checkmark on success
            if done {
                Image(systemName: "checkmark")
                    .font(.system(size: 80, weight: .bold))
                    .foregroundStyle(Hue.red)
                    .transition(.scale.combined(with: .opacity))
            }

            // horizontal scan beam, masked to the inner circle
            Rectangle()
                .fill(LinearGradient(
                    colors: [.clear, Hue.red.opacity(0.55), .clear],
                    startPoint: .top, endPoint: .bottom
                ))
                .frame(height: 18)
                .offset(y: beam * 110)
                .mask(Circle().frame(width: 240, height: 240))
                .opacity(done ? 0 : 1)

            // pulsing reticle dots in the corners
            ForEach(0..<4, id: \.self) { i in
                let a = Double(i) * 90 + 45
                Reticle(scale: pulse ? 1.0 : 0.85)
                    .offset(x: cos(a * .pi / 180) * 152, y: sin(a * .pi / 180) * 152)
            }
        }
        .frame(width: 320, height: 320)
        .onAppear {
            withAnimation(.linear(duration: duration)) { progress = 1 }
            withAnimation(.easeInOut(duration: 0.9).repeatForever(autoreverses: true)) {
                beam = 1
            }
            withAnimation(.easeInOut(duration: 0.7).repeatForever(autoreverses: true)) {
                pulse = true
            }
            DispatchQueue.main.asyncAfter(deadline: .now() + duration) {
                withAnimation(.spring(response: 0.4, dampingFraction: 0.7)) { done = true }
                DispatchQueue.main.asyncAfter(deadline: .now() + 0.6) { onSuccess() }
            }
        }
    }
}

private struct DottedRing: View {
    let count: Int
    let lineWidth: CGFloat
    let length: CGFloat
    let radius: CGFloat

    var body: some View {
        ZStack {
            ForEach(0..<count, id: \.self) { i in
                let a = Double(i) / Double(count) * .pi * 2
                Capsule()
                    .frame(width: lineWidth, height: length)
                    .offset(y: -radius)
                    .rotationEffect(.radians(a))
            }
        }
        .frame(width: radius * 2, height: radius * 2)
    }
}

private struct FaceSilhouette: Shape {
    func path(in rect: CGRect) -> Path {
        var p = Path()
        let r = rect
        // oval head
        p.addEllipse(in: r.insetBy(dx: r.width * 0.05, dy: 0))
        // eyes
        p.addEllipse(in: CGRect(x: r.width * 0.30, y: r.height * 0.38,
                                width: r.width * 0.12, height: r.height * 0.05))
        p.addEllipse(in: CGRect(x: r.width * 0.58, y: r.height * 0.38,
                                width: r.width * 0.12, height: r.height * 0.05))
        // mouth
        p.move(to: CGPoint(x: r.width * 0.36, y: r.height * 0.66))
        p.addQuadCurve(
            to: CGPoint(x: r.width * 0.64, y: r.height * 0.66),
            control: CGPoint(x: r.width * 0.5, y: r.height * 0.74)
        )
        return p
    }
}

private struct Reticle: View {
    let scale: CGFloat
    var body: some View {
        Path { p in
            p.move(to: .zero); p.addLine(to: CGPoint(x: 8, y: 0))
            p.move(to: .zero); p.addLine(to: CGPoint(x: 0, y: 8))
        }
        .stroke(Hue.ink.opacity(0.7), lineWidth: 2)
        .frame(width: 10, height: 10)
        .scaleEffect(scale)
    }
}
