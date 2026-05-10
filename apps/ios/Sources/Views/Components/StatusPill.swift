import SwiftUI

// Brand pill in the top-right corner. Reads BackendStatus from the
// environment so the UI tells the user at a glance whether the action
// router is reachable.
struct StatusPill: View {
    @EnvironmentObject var backend: BackendStatus
    @State private var now = Date()
    private let timer = Timer.publish(every: 1, on: .main, in: .common).autoconnect()

    var body: some View {
        HStack(spacing: 6) {
            Circle()
                .fill(dotColor)
                .frame(width: 8, height: 8)
                .overlay(Circle().strokeBorder(Hue.ink, lineWidth: 1.5))
            Text(label)
                .font(.mono(10))
                .tracking(1.5)
                .foregroundStyle(Hue.ink)
            Text("·")
                .font(.mono(10))
                .foregroundStyle(Hue.ink.opacity(0.45))
            Text(formatted(now))
                .font(.mono(10))
                .tracking(1.4)
                .foregroundStyle(Hue.ink)
        }
        .padding(.horizontal, 10).padding(.vertical, 5)
        .background(Capsule().fill(Hue.gold))
        .overlay(Capsule().strokeBorder(Hue.ink, lineWidth: 3))
        .background(Capsule().fill(Hue.ink).offset(y: 3))
        .onReceive(timer) { now = $0 }
        .animation(.easeInOut(duration: 0.18), value: backend.state)
    }

    private var label: String {
        switch backend.state {
        case .live:       return "READY"
        case .connecting: return "CONNECT…"
        case .offline:    return "OFFLINE"
        }
    }

    private var dotColor: Color {
        switch backend.state {
        case .live:       return Color(red: 0.18, green: 0.78, blue: 0.36)
        case .connecting: return Hue.gold
        case .offline:    return Hue.red
        }
    }

    private func formatted(_ d: Date) -> String {
        let f = DateFormatter()
        f.dateFormat = "HH:mm:ss"
        return f.string(from: d)
    }
}
