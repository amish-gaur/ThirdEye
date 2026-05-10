import SwiftUI

// Mirrors the NodeRow function in apps/figma-ui/src/app/App.tsx.
struct NodeRow: View {
    let id: String
    let loc: String
    let status: NodeStatus
    var delay: Double = 0
    @State private var visible = false
    @State private var pulse = false

    private var dot: Color {
        switch status {
        case .alert: return Hue.red
        case .live:  return Hue.orange
        case .idle:  return Color(hex: "#7a6a55")
        }
    }

    var body: some View {
        HStack {
            HStack(spacing: 10) {
                Circle()
                    .fill(dot)
                    .overlay(Circle().strokeBorder(Hue.ink, lineWidth: 2))
                    .frame(width: 10, height: 10)
                    .opacity(pulse ? 0.3 : 1)
                    .animation(.easeInOut(duration: 0.7).repeatForever(autoreverses: true), value: pulse)
                Text("\(id) · \(loc)")
                    .font(.mono(11))
                    .tracking(1.6)
                    .foregroundStyle(Hue.ink)
            }
            Spacer()
            Text(label.uppercased())
                .font(.mono(9))
                .tracking(2)
                .foregroundStyle(Hue.cream)
                .padding(.horizontal, 8).padding(.vertical, 2)
                .background(Rectangle().fill(status == .alert ? Hue.red : Hue.ink))
        }
        .padding(.horizontal, 12).padding(.vertical, 8)
        .background(
            RoundedRectangle(cornerRadius: 8, style: .continuous)
                .fill(Hue.cream)
        )
        .overlay(
            RoundedRectangle(cornerRadius: 8, style: .continuous)
                .strokeBorder(Hue.ink, lineWidth: 3)
        )
        .opacity(visible ? 1 : 0)
        .offset(x: visible ? 0 : -8)
        .onAppear {
            withAnimation(.easeOut(duration: 0.3).delay(delay)) { visible = true }
            pulse = true
        }
    }

    private var label: String {
        switch status {
        case .alert: return "alert"
        case .live:  return "live"
        case .idle:  return "idle"
        }
    }
}
