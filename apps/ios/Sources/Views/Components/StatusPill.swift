import SwiftUI

// Mirrors the StatusPill function in apps/figma-ui/src/app/App.tsx.
struct StatusPill: View {
    @State private var now = Date()
    private let timer = Timer.publish(every: 1, on: .main, in: .common).autoconnect()

    var body: some View {
        HStack(spacing: 6) {
            Image(systemName: "shield.checkered")
                .font(.system(size: 12, weight: .bold))
                .foregroundStyle(Hue.ink)
            Text(formatted(now))
                .font(.mono(10))
                .tracking(1.5)
                .foregroundStyle(Hue.ink)
        }
        .padding(.horizontal, 10).padding(.vertical, 5)
        .background(Capsule().fill(Hue.gold))
        .overlay(Capsule().strokeBorder(Hue.ink, lineWidth: 3))
        .background(Capsule().fill(Hue.ink).offset(y: 3))
        .onReceive(timer) { now = $0 }
    }

    private func formatted(_ d: Date) -> String {
        let f = DateFormatter()
        f.dateFormat = "HH:mm:ss"
        return f.string(from: d)
    }
}
