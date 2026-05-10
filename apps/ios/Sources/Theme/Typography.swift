import SwiftUI

// MARK: - Type scale
//
// Display (titles): system-serif via .serif design (mirrors Newsreader on web).
// Body: system rounded for warmth, but mostly default.
// Mono: caps labels, timestamps, severity ladder.

extension Font {
    static var teHero: Font {
        .system(size: 40, weight: .heavy, design: .serif)
    }
    static var teDisplay: Font {
        .system(size: 32, weight: .black, design: .serif)
    }
    static var teH1: Font {
        .system(size: 28, weight: .black, design: .serif)
    }
    static var teH2: Font {
        .system(size: 22, weight: .bold, design: .default)
    }
    static var teH3: Font {
        .system(size: 17, weight: .semibold, design: .default)
    }
    static var teBody: Font {
        .system(size: 15, weight: .regular, design: .default)
    }
    static var teBodySm: Font {
        .system(size: 13, weight: .regular, design: .default)
    }
    static var teButton: Font {
        .system(size: 16, weight: .bold, design: .default)
    }
    static var teCaps: Font {
        .system(size: 11, weight: .heavy, design: .monospaced)
    }
    static var teMono: Font {
        .system(size: 12, weight: .medium, design: .monospaced)
    }
}
