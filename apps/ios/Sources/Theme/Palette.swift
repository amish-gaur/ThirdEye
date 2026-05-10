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

// MARK: - Figma tokens
//
// Palette pulled from the published Figma site CSS at
// https://fly-slaw-83829467.figma.site/ — clean light theme.
// Hex values tracked literally so they match the design source.

enum Theme {
    /// Page / body bg — pure white.
    static let bg          = Color(hex: "#FFFFFF")
    /// Card surface — same as bg in Figma's spec.
    static let surface     = Color(hex: "#FFFFFF")
    /// Lightly recessed surface (input bg, secondary cards).
    static let surface2    = Color(hex: "#F3F3F5")
    /// Subtle muted surface (chip backgrounds, dividers).
    static let muted       = Color(hex: "#ECECF0")
    /// Subtle accent surface (hover, focus tints).
    static let accent      = Color(hex: "#E9EBEF")
    /// 10% black border — modern thin-line look.
    static let border      = Color.black.opacity(0.10)

    /// Primary text — near-black with the slightest blue tint.
    static let text        = Color(hex: "#030213")
    /// Secondary text — medium gray.
    static let textMuted   = Color(hex: "#717182")
    /// Tertiary text / placeholder — lighter gray.
    static let textSubtle  = Color(hex: "#B3B3B3")

    /// Dark CTA (Sign in, primary buttons) — same as `text`.
    static let primary     = Color(hex: "#030213")
    /// Text on primary CTA — white.
    static let primaryFg   = Color(hex: "#FFFFFF")

    /// Destructive / Tier 3 alert.
    static let destructive = Color(hex: "#D4183D")
    /// Destructive bg tint (subtle alert chip background).
    static let destructiveSoft = Color(hex: "#D4183D").opacity(0.10)
    /// Warm sand accent — used as the "soft warmth" highlight in the Figma.
    static let warmSand    = Color(hex: "#F1C8A5")

    // ---- Wine accent scale (preserved from previous palette for severity dots
    //      and the dramatic incident hero — Figma still uses these tones).

    static let wine900     = Color(hex: "#0D0204")
    static let wine800     = Color(hex: "#1A0306")
    static let wine700     = Color(hex: "#2A0608")
    static let wine600     = Color(hex: "#5A1520")
    static let wine500     = Color(hex: "#7A1521")
    static let wine400     = Color(hex: "#7A2230")
    static let wineRed     = Color(hex: "#C8333F")
}

/// Convenience aliases so older view code that referenced Cream/Maroon
/// keeps compiling while the migration is in progress.
enum Cream {
    static let c50  = Theme.bg
    static let c100 = Theme.surface2
    static let c200 = Theme.muted
    static let c300 = Theme.accent
}

enum Maroon {
    static let m50  = Color(hex: "#FCE6EA")
    static let m100 = Color(hex: "#F4B8C0")
    static let m200 = Color(hex: "#E58A95")
    static let m300 = Color(hex: "#D4183D") // primary destructive in Figma
    static let m400 = Color(hex: "#C8333F")
    static let m500 = Color(hex: "#7A2230")
    static let m600 = Color(hex: "#7A1521")
    static let m700 = Color(hex: "#5A1520")
    static let m800 = Color(hex: "#2A0608")
    static let m900 = Color(hex: "#1A0306")
    static let m950 = Color(hex: "#0D0204")
}

let Ink = Theme.text

// MARK: - Aurora — softened for light theme
//
// Three radial peach/wine glows at very low opacity over the white body.
struct Aurora: View {
    @State private var drift: CGSize = .zero

    var body: some View {
        ZStack {
            RadialGradient(
                colors: [Theme.warmSand.opacity(0.30), .clear],
                center: UnitPoint(x: 0.18, y: 0.20),
                startRadius: 0, endRadius: 360
            )
            RadialGradient(
                colors: [Color(hex: "#D4183D").opacity(0.10), .clear],
                center: UnitPoint(x: 0.85, y: 0.65),
                startRadius: 0, endRadius: 380
            )
            RadialGradient(
                colors: [Color(hex: "#7A2230").opacity(0.08), .clear],
                center: UnitPoint(x: 0.5, y: 1.0),
                startRadius: 0, endRadius: 420
            )
            // Soft fade-to-bg so aurora doesn't bleed through the bottom UI.
            LinearGradient(
                colors: [.clear, .clear, Theme.bg.opacity(0.85), Theme.bg],
                startPoint: .top, endPoint: .bottom
            )
        }
        .offset(drift)
        .blur(radius: 32)
        .onAppear {
            withAnimation(.easeInOut(duration: 18).repeatForever(autoreverses: true)) {
                drift = CGSize(width: 12, height: -12)
            }
        }
    }
}

// MARK: - Camera tile gradients (per node) — kept dark since security feeds
// are inherently low-light.

enum CameraTileGradient {
    case frontPorch, driveway, backyard, garage

    var stops: (hot: Color, cool: Color) {
        switch self {
        case .frontPorch: return (Color(hex: "#7A2230"), Color(hex: "#1A0306"))
        case .driveway:   return (Color(hex: "#7A1521"), Color(hex: "#0D0204"))
        case .backyard:   return (Color(hex: "#5A1520"), Color(hex: "#1A0306"))
        case .garage:     return (Color(hex: "#2A0608"), Color(hex: "#0D0204"))
        }
    }
}
