import SwiftUI

// Plain Playfair display text. (Eye accent on every "e" was removed —
// the SwiftUI port couldn't position it cleanly inside the letter counter.)
struct EyeText: View {
    let text: String
    var size: CGFloat = 56

    var body: some View {
        Text(text)
            .font(.playfair(size, weight: .heavy))
            .foregroundStyle(Hue.ink)
    }
}
