import SwiftUI

/// Sticky brand header — light theme matching the Figma.
struct SafeWatchTopBar: View {
    var body: some View {
        HStack(alignment: .center, spacing: 12) {
            HStack(spacing: 5) {
                Text("SafeWatch")
                    .font(.system(size: 22, weight: .semibold, design: .serif))
                    .foregroundStyle(Theme.text)
                Circle()
                    .fill(Theme.destructive)
                    .frame(width: 4, height: 4)
                    .padding(.leading, 2)
            }
            Spacer()
            LocalInferencePill()
        }
        .padding(.horizontal, 22)
        .padding(.vertical, 12)
        .background(
            Theme.bg.opacity(0.85)
                .background(.ultraThinMaterial)
                .ignoresSafeArea(edges: .top)
        )
        .overlay(alignment: .bottom) {
            Rectangle()
                .fill(Theme.border)
                .frame(height: 1)
        }
    }
}

private struct LocalInferencePill: View {
    @State private var pulse = false

    var body: some View {
        HStack(spacing: 6) {
            Circle()
                .fill(Theme.destructive)
                .frame(width: 6, height: 6)
                .opacity(pulse ? 0.45 : 1.0)
                .animation(.easeInOut(duration: 1.2).repeatForever(autoreverses: true), value: pulse)
            Text("LOCAL INFERENCE")
                .font(.system(size: 10, weight: .heavy, design: .monospaced))
                .tracking(1.6)
                .foregroundStyle(Theme.textMuted)
        }
        .padding(.horizontal, 10)
        .padding(.vertical, 5)
        .background(Capsule().fill(Theme.muted))
        .overlay(Capsule().strokeBorder(Theme.border, lineWidth: 0.5))
        .onAppear { pulse = true }
    }
}
