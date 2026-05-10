import SwiftUI

/// Cinematic camera tile — kept dark since security feeds are inherently low-light.
/// Now sits on a white card with subtle border (Figma light theme).
struct CameraTile: View {
    let node: CameraNode

    var body: some View {
        VStack(alignment: .leading, spacing: 0) {
            ZStack(alignment: .topLeading) {
                FilmCanvas(toneHot: node.gradient.stops.hot, toneCool: node.gradient.stops.cool)
                ScanlineLayer().opacity(0.18).blendMode(.overlay)
                ScanBeam()
                hud
            }
            .aspectRatio(16.0/10.0, contentMode: .fit)
            .clipShape(RoundedRectangle(cornerRadius: 14, style: .continuous))
            .overlay(
                RoundedRectangle(cornerRadius: 14, style: .continuous)
                    .strokeBorder(Theme.border, lineWidth: 1)
            )

            HStack {
                Text(node.name)
                    .font(.system(size: 15, weight: .semibold))
                    .foregroundStyle(Theme.text)
                Spacer()
                Text(node.online ? "LIVE" : "OFFLINE")
                    .font(.system(size: 10, weight: .heavy, design: .monospaced))
                    .tracking(1.4)
                    .foregroundStyle(node.online ? Theme.destructive : Theme.textSubtle)
            }
            .padding(.top, 10)
            .padding(.horizontal, 4)
        }
    }

    private var hud: some View {
        ZStack(alignment: .topLeading) {
            HStack(spacing: 8) {
                StatusDot(online: node.online)
                Text(node.name.uppercased())
                    .font(.system(size: 10, weight: .heavy, design: .monospaced))
                    .tracking(1.6)
                    .foregroundStyle(.white.opacity(0.85))
            }
            .padding(12)

            HStack {
                Spacer()
                Text(node.online ? "● REC" : "○ OFFLINE")
                    .font(.system(size: 10, weight: .heavy, design: .monospaced))
                    .tracking(2.0)
                    .foregroundStyle(.white.opacity(0.65))
            }
            .padding(12)

            VStack {
                Spacer()
                HStack {
                    Text(node.name.uppercased())
                        .font(.system(size: 10, weight: .heavy, design: .monospaced))
                        .tracking(1.6)
                        .foregroundStyle(.white.opacity(0.6))
                    Spacer()
                    Clock()
                }
                .padding(12)
            }
        }
    }
}

private struct StatusDot: View {
    let online: Bool
    @State private var pulse = false

    var body: some View {
        ZStack {
            if online {
                Circle()
                    .fill(.white.opacity(0.18))
                    .frame(width: 14, height: 14)
                    .scaleEffect(pulse ? 1.3 : 0.9)
                    .opacity(pulse ? 0.0 : 0.7)
                    .animation(.easeInOut(duration: 1.6).repeatForever(autoreverses: false), value: pulse)
            }
            Circle()
                .fill(online ? .white : .white.opacity(0.30))
                .frame(width: 6, height: 6)
        }
        .onAppear { pulse = true }
    }
}

private struct FilmCanvas: View {
    let toneHot: Color
    let toneCool: Color
    @State private var tick: Date = Date()
    private let timer = Timer.publish(every: 1.0/24.0, on: .main, in: .common).autoconnect()

    var body: some View {
        Canvas { ctx, size in
            let w = size.width
            let h = size.height
            let t = tick.timeIntervalSinceReferenceDate

            let radial = Gradient(stops: [
                .init(color: toneHot, location: 0.0),
                .init(color: toneCool, location: 0.55),
                .init(color: Color(hex: "#0A0103"), location: 1.0),
            ])
            ctx.fill(
                Path(CGRect(origin: .zero, size: size)),
                with: .radialGradient(
                    radial,
                    center: CGPoint(x: w * 0.25, y: h * 0.30),
                    startRadius: 0,
                    endRadius: max(w, h) * 0.95
                )
            )

            let dy = h * 0.5 + CGFloat(sin(t * 0.5) * 30)
            let hazeStops = Gradient(stops: [
                .init(color: Color(hex: "#D4183D").opacity(0.0),  location: 0.0),
                .init(color: Color(hex: "#D4183D").opacity(0.10), location: 0.5),
                .init(color: Color(hex: "#D4183D").opacity(0.0),  location: 1.0),
            ])
            ctx.fill(
                Path(CGRect(origin: .zero, size: size)),
                with: .linearGradient(
                    hazeStops,
                    startPoint: CGPoint(x: 0, y: dy),
                    endPoint: CGPoint(x: w, y: dy + 1)
                )
            )

            ctx.opacity = 0.14
            var rng = SystemRandomNumberGenerator()
            for _ in 0..<200 {
                let x = CGFloat.random(in: 0..<w, using: &rng)
                let y = CGFloat.random(in: 0..<h, using: &rng)
                let v = Double.random(in: 0..<1, using: &rng)
                let color: Color
                if v > 0.85 {
                    color = .white.opacity(0.7)
                } else if v > 0.5 {
                    color = .black.opacity(0.7)
                } else {
                    continue
                }
                let dot = Path(CGRect(x: x, y: y, width: 1.4, height: 1.4))
                ctx.fill(dot, with: .color(color))
            }
            ctx.opacity = 1

            let vignette = Gradient(stops: [
                .init(color: .clear, location: 0.0),
                .init(color: .black.opacity(0.55), location: 1.0),
            ])
            ctx.fill(
                Path(CGRect(origin: .zero, size: size)),
                with: .radialGradient(
                    vignette,
                    center: CGPoint(x: w * 0.5, y: h * 0.5),
                    startRadius: min(w, h) * 0.35,
                    endRadius: max(w, h) * 0.7
                )
            )
        }
        .onReceive(timer) { tick = $0 }
        .drawingGroup()
    }
}

private struct ScanlineLayer: View {
    var body: some View {
        Canvas { ctx, size in
            var y: CGFloat = 0
            while y < size.height {
                let rect = CGRect(x: 0, y: y, width: size.width, height: 1.2)
                ctx.fill(Path(rect), with: .color(.black.opacity(0.50)))
                y += 4
            }
        }
        .allowsHitTesting(false)
    }
}

private struct ScanBeam: View {
    @State private var phase: CGFloat = -0.1

    var body: some View {
        GeometryReader { geo in
            let h = geo.size.height
            let band: CGFloat = 60
            LinearGradient(
                colors: [.clear, .white.opacity(0.10), .clear],
                startPoint: .top, endPoint: .bottom
            )
            .frame(height: band)
            .offset(y: phase * (h + band) - band)
            .onAppear {
                withAnimation(.linear(duration: 6).repeatForever(autoreverses: false)) {
                    phase = 1.1
                }
            }
        }
        .allowsHitTesting(false)
    }
}

private struct Clock: View {
    @State private var now = Date()
    private let formatter: DateFormatter = {
        let f = DateFormatter()
        f.dateFormat = "HH:mm:ss"
        return f
    }()

    var body: some View {
        Text("\(formatter.string(from: now)) · 24FPS")
            .font(.system(size: 10, weight: .semibold, design: .monospaced))
            .tracking(1.6)
            .foregroundStyle(.white.opacity(0.6))
            .onReceive(Timer.publish(every: 1, on: .main, in: .common).autoconnect()) { d in
                now = d
            }
    }
}
