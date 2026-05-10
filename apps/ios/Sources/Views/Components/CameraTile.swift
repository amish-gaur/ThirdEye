import SwiftUI

// Mirrors apps/figma-ui/src/app/components/CameraTile.tsx.
struct CameraTile: View {
    let name: String
    var status: NodeStatus = .idle
    var delay: Double = 0
    var large: Bool = false
    var streamUrl: String? = nil

    @State private var visible = false
    @State private var pulse = false

    private var dot: Color {
        switch status {
        case .alert: return Hue.red
        case .live:  return Hue.orange
        case .idle:  return Color(hex: "#7a6a55")
        }
    }
    private var statusLabel: String {
        switch status {
        case .alert: return "ALERT"
        case .live:  return "LIVE"
        case .idle:  return "IDLE"
        }
    }

    var body: some View {
        ZStack(alignment: .topLeading) {
            // shadow block
            RoundedRectangle(cornerRadius: 14, style: .continuous)
                .fill(Hue.ink)
                .offset(x: 6, y: 8)

            VStack(spacing: 0) {
                // header strip
                HStack {
                    HStack(spacing: 6) {
                        Circle()
                            .fill(dot)
                            .frame(width: 8, height: 8)
                            .opacity(pulse ? 0.3 : 1)
                        Text(name)
                            .font(.mono(10))
                            .tracking(2)
                            .foregroundStyle(Hue.ink)
                            .lineLimit(1)
                    }
                    Spacer()
                    Text(statusLabel)
                        .font(.mono(10))
                        .tracking(2)
                        .foregroundStyle(Hue.cream)
                        .padding(.horizontal, 6).padding(.vertical, 2)
                        .background(Rectangle().fill(status == .alert ? Hue.red : Hue.ink))
                }
                .padding(.horizontal, 10).padding(.vertical, 6)
                .background(Hue.cream)
                .overlay(alignment: .bottom) {
                    Rectangle().fill(Hue.ink).frame(height: 3)
                }

                // feed mount
                ZStack {
                    Rectangle().fill(Hue.sand)
                    if let url = streamUrl, let _ = URL(string: url) {
                        AsyncImage(url: URL(string: url)!) { phase in
                            switch phase {
                            case .empty: RobberWaiting(height: large ? 280 : 180)
                            case .success(let img): img.resizable().scaledToFill()
                            case .failure: RobberWaiting(height: large ? 280 : 180)
                            @unknown default: EmptyView()
                            }
                        }
                    } else {
                        RobberWaiting(height: large ? 280 : 180)
                    }
                }
                .clipped()
            }
            .background(
                RoundedRectangle(cornerRadius: 14, style: .continuous).fill(Hue.sand)
            )
            .overlay(
                RoundedRectangle(cornerRadius: 14, style: .continuous)
                    .strokeBorder(Hue.ink, lineWidth: 4)
            )
            .clipShape(RoundedRectangle(cornerRadius: 14, style: .continuous))
        }
        .aspectRatio(large ? 16.0/9.0 : 4.0/3.0, contentMode: .fit)
        .opacity(visible ? 1 : 0)
        .offset(y: visible ? 0 : 8)
        .onAppear {
            withAnimation(.easeOut(duration: 0.45).delay(delay)) { visible = true }
            pulse = true
        }
    }
}
