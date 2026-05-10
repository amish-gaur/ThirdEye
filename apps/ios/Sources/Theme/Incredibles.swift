import SwiftUI

// Mirrors the `C` palette in apps/figma-ui/src/app/App.tsx.
enum Hue {
    static let cream  = Color(hex: "#f4ead8")
    static let ink    = Color(hex: "#1a0306")
    static let red    = Color(hex: "#c8222d")
    static let orange = Color(hex: "#e85a3c")
    static let gold   = Color(hex: "#f4c97a")
    static let wine   = Color(hex: "#7a2230")
    static let deep   = Color(hex: "#3a1014")
    static let sand   = Color(hex: "#e6d2a8")
    static let shellLight  = Color(hex: "#fff6e2")
    static let shellShadow = Color(hex: "#c89a5e")
    static let lens   = Color(hex: "#0d0204")
    static let ring   = Color(hex: "#1a1417")
    static let redHi  = Color(hex: "#ffb070")
    static let hotRed = Color(hex: "#ff3146")
}

// Type aliases mirroring App.tsx's font choices.
extension Font {
    static func playfair(_ size: CGFloat, weight: Font.Weight = .bold) -> Font {
        .system(size: size, weight: weight, design: .serif)
    }
    static func mono(_ size: CGFloat, weight: Font.Weight = .semibold) -> Font {
        .system(size: size, weight: weight, design: .monospaced)
    }
}
