import SwiftUI

struct SectionHead: View {
    let eyebrow: String
    let title: String
    var accessory: AnyView? = nil

    var body: some View {
        HStack(alignment: .bottom) {
            VStack(alignment: .leading, spacing: 4) {
                Text(eyebrow.uppercased())
                    .font(.system(size: 10.5, weight: .semibold, design: .monospaced))
                    .tracking(2.4)
                    .foregroundStyle(Theme.textMuted)
                Text(title)
                    .font(.system(size: 28, weight: .semibold, design: .serif))
                    .foregroundStyle(Theme.text)
            }
            Spacer()
            accessory
        }
    }
}

struct ShimmerText: View {
    let text: String
    @State private var phase: CGFloat = -1

    var body: some View {
        Text(text)
            .foregroundStyle(
                LinearGradient(
                    stops: [
                        .init(color: Theme.destructive.opacity(0.55), location: 0.0),
                        .init(color: Theme.text,                       location: 0.45),
                        .init(color: Theme.destructive.opacity(0.55), location: 0.65),
                        .init(color: Theme.destructive.opacity(0.45), location: 1.0),
                    ],
                    startPoint: .init(x: phase, y: 0.5),
                    endPoint: .init(x: phase + 1, y: 0.5)
                )
            )
            .onAppear {
                withAnimation(.linear(duration: 3).repeatForever(autoreverses: false)) {
                    phase = 1
                }
            }
    }
}
