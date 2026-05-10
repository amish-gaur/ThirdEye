import SwiftUI

/// Sticky brand header — mirrors apps/web/src/components/Nav.tsx
/// (without the page-level nav items, since iOS uses the bottom TabBar).
struct SafeWatchTopBar: View {
    var body: some View {
        HStack(alignment: .center, spacing: 12) {
            HStack(spacing: 4) {
                Text("SafeWatch")
                    .font(.system(size: 22, weight: .semibold, design: .serif))
                    .foregroundStyle(Cream.c50)
                Circle()
                    .fill(Maroon.m300)
                    .frame(width: 4, height: 4)
                    .padding(.leading, 2)
            }
            Spacer()
            LocalInferencePill()
        }
        .padding(.horizontal, 22)
        .padding(.vertical, 12)
        .background(
            ZStack {
                Maroon.m950.opacity(0.70)
                Rectangle()
                    .fill(.ultraThinMaterial)
            }
            .ignoresSafeArea(edges: .top)
        )
        .overlay(alignment: .bottom) {
            Rectangle()
                .fill(Maroon.m300.opacity(0.10))
                .frame(height: 1)
        }
    }
}

private struct LocalInferencePill: View {
    @State private var pulse = false

    var body: some View {
        HStack(spacing: 6) {
            Circle()
                .fill(Maroon.m200)
                .frame(width: 6, height: 6)
                .opacity(pulse ? 0.45 : 1.0)
                .animation(.easeInOut(duration: 1.2).repeatForever(autoreverses: true), value: pulse)
            Text("LOCAL INFERENCE")
                .font(.teCaps).tracking(1.8)
                .foregroundStyle(Maroon.m100)
        }
        .padding(.horizontal, 10)
        .padding(.vertical, 5)
        .background(
            Capsule().fill(Maroon.m900.opacity(0.40))
        )
        .overlay(
            Capsule().strokeBorder(Maroon.m300.opacity(0.20), lineWidth: 0.5)
        )
        .onAppear { pulse = true }
    }
}
