import SwiftUI

// MARK: - Hex init

extension Color {
    init(hex: String) {
        let trimmed = hex.trimmingCharacters(in: CharacterSet.alphanumerics.inverted)
        var int: UInt64 = 0
        Scanner(string: trimmed).scanHexInt64(&int)
        let r = Double((int >> 16) & 0xFF) / 255
        let g = Double((int >> 8)  & 0xFF) / 255
        let b = Double(int         & 0xFF) / 255
        self.init(red: r, green: g, blue: b)
    }
}

// MARK: - Palette
//
// Wine + cream stack. Cream surfaces, dark wine accents and severity.
// Hex values match `packages/ui/src/tokens.ts` exactly.

enum Cream {
    static let c50  = Color(hex: "#FBF1E7") // body text on dark, primary CTA bg
    static let c100 = Color(hex: "#F5E6D3") // hover state on cream CTA
    static let c200 = Color(hex: "#E8D4BC") // lighter cards
    static let c300 = Color(hex: "#D4B896") // reserved
}

enum Maroon {
    static let m50  = Color(hex: "#F2D9DC") // severity-4 badge text
    static let m100 = Color(hex: "#E5B4BB") // shimmer accent, severity-4 dot
    static let m200 = Color(hex: "#C98A93") // eyebrows, severity-1 dot
    static let m300 = Color(hex: "#B85968") // severity-3 dot, focus rings
    static let m400 = Color(hex: "#9A3142") // severity-2 dot
    static let m500 = Color(hex: "#7A1F2B") // driveway tile hot
    static let m600 = Color(hex: "#5E1521") // severity-3 base
    static let m700 = Color(hex: "#4A0E18") // active-incident gradient
    static let m800 = Color(hex: "#330810") // garage tile hot
    static let m900 = Color(hex: "#1F050A") // severity-4 base, ink
    static let m950 = Color(hex: "#120308") // body background, deepest cool
}

let Ink = Maroon.m900

// MARK: - Aurora gradient (animated hero bg)
struct Aurora: View {
    @State private var drift: CGSize = .zero

    var body: some View {
        ZStack {
            RadialGradient(
                colors: [Color(hex: "#B85968").opacity(0.30), .clear],
                center: UnitPoint(x: 0.2, y: 0.2),
                startRadius: 0, endRadius: 360
            )
            RadialGradient(
                colors: [Color(hex: "#4A0E18").opacity(0.45), .clear],
                center: UnitPoint(x: 0.8, y: 0.6),
                startRadius: 0, endRadius: 400
            )
            RadialGradient(
                colors: [Color(hex: "#9A3142").opacity(0.35), .clear],
                center: UnitPoint(x: 0.5, y: 1.0),
                startRadius: 0, endRadius: 420
            )
            // Subtle grid mask — cream lines at low opacity, faded toward edges
            GridMask().opacity(0.35)
            // Fade-to-bottom (matches web: bg-gradient-to-b ... to-maroon-950)
            LinearGradient(
                colors: [.clear, .clear, Maroon.m950.opacity(0.85), Maroon.m950],
                startPoint: .top, endPoint: .bottom
            )
        }
        .offset(drift)
        .blur(radius: 18)
        .onAppear {
            withAnimation(.easeInOut(duration: 18).repeatForever(autoreverses: true)) {
                drift = CGSize(width: 12, height: -12)
            }
        }
    }
}

private struct GridMask: View {
    var body: some View {
        Canvas { ctx, size in
            let step: CGFloat = 56
            let lineColor = Color(hex: "#F5E6D3").opacity(0.06)
            var x: CGFloat = 0
            while x < size.width {
                ctx.fill(Path(CGRect(x: x, y: 0, width: 1, height: size.height)), with: .color(lineColor))
                x += step
            }
            var y: CGFloat = 0
            while y < size.height {
                ctx.fill(Path(CGRect(x: 0, y: y, width: size.width, height: 1)), with: .color(lineColor))
                y += step
            }
        }
        .mask(
            RadialGradient(
                colors: [.black, .black.opacity(0.6), .clear],
                center: UnitPoint(x: 0.5, y: 0.4),
                startRadius: 80, endRadius: 420
            )
        )
        .allowsHitTesting(false)
    }
}

// MARK: - Camera tile gradients (per node)
enum CameraTileGradient {
    case frontPorch, driveway, backyard, garage

    var stops: (hot: Color, cool: Color) {
        switch self {
        case .frontPorch: return (Color(hex: "#9A3142"), Color(hex: "#1F050A"))
        case .driveway:   return (Color(hex: "#7A1F2B"), Color(hex: "#120308"))
        case .backyard:   return (Color(hex: "#5E1521"), Color(hex: "#1F050A"))
        case .garage:     return (Color(hex: "#330810"), Color(hex: "#0A0103"))
        }
    }
}
