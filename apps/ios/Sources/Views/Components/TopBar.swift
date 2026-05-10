import SwiftUI

// Mirrors the TopBar function in apps/figma-ui/src/app/App.tsx.
struct TopBar: View {
    @Binding var tab: AppTab

    var body: some View {
        VStack(spacing: 8) {
            HStack(alignment: .center) {
                HStack(spacing: 3) {
                    Text("Third")
                        .font(.playfair(20, weight: .black))
                        .foregroundStyle(Hue.ink)
                    Text("Eye")
                        .font(.playfair(20, weight: .black))
                        .italic()
                        .foregroundStyle(Hue.red)
                }
                Spacer()
                StatusPill()
            }
            NavPill(tab: $tab)
        }
    }
}

private struct NavPill: View {
    @Binding var tab: AppTab
    @Namespace private var ns

    var body: some View {
        HStack(spacing: 2) {
            ForEach(AppTab.allCases) { t in
                Button {
                    withAnimation(.spring(response: 0.32, dampingFraction: 0.78)) { tab = t }
                } label: {
                    HStack(spacing: 5) {
                        Image(systemName: t.icon)
                            .font(.system(size: 10, weight: .semibold))
                        Text(t.label.uppercased())
                            .font(.mono(9.5))
                            .tracking(1.0)
                    }
                    .foregroundStyle(tab == t ? Hue.cream : Hue.ink)
                    .frame(maxWidth: .infinity)
                    .padding(.vertical, 7)
                    .background {
                        if tab == t {
                            Capsule().fill(Hue.red)
                                .overlay(Capsule().strokeBorder(Hue.ink, lineWidth: 2))
                                .matchedGeometryEffect(id: "nav-pill", in: ns)
                        }
                    }
                }
                .buttonStyle(.plain)
            }
        }
        .padding(4)
        .background(Capsule().fill(Hue.cream))
        .overlay(Capsule().strokeBorder(Hue.ink, lineWidth: 3))
        .background(Capsule().fill(Hue.ink).offset(y: 4))
    }
}
