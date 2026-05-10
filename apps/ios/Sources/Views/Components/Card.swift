import SwiftUI

// Mirrors the `Card` helper in apps/figma-ui/src/app/App.tsx.
struct Card<Content: View>: View {
    var corner: CGFloat = 18
    var padding: CGFloat = 0
    @ViewBuilder var content: () -> Content

    var body: some View {
        ZStack {
            RoundedRectangle(cornerRadius: corner, style: .continuous)
                .fill(Hue.ink)
                .offset(y: 8)
            RoundedRectangle(cornerRadius: corner, style: .continuous)
                .fill(Hue.cream)
                .overlay(
                    RoundedRectangle(cornerRadius: corner, style: .continuous)
                        .strokeBorder(Hue.ink, lineWidth: 4)
                )
            content()
                .padding(padding)
        }
        .fixedSize(horizontal: false, vertical: true)
    }
}
