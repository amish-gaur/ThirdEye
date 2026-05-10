import SwiftUI

struct SectionHead: View {
    let eyebrow: String
    let title: String
    var accessory: AnyView? = nil

    var body: some View {
        HStack(alignment: .bottom) {
            VStack(alignment: .leading, spacing: 4) {
                Text(eyebrow.uppercased())
                    .font(.teCaps)
                    .tracking(2.4)
                    .foregroundStyle(Maroon.m200)
                Text(title)
                    .font(.teH1)
                    .foregroundStyle(Cream.c50)
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
                        .init(color: Maroon.m100.opacity(0.55), location: 0.0),
                        .init(color: Cream.c100,                location: 0.45),
                        .init(color: Maroon.m100.opacity(0.55), location: 0.65),
                        .init(color: Maroon.m100.opacity(0.45), location: 1.0),
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
