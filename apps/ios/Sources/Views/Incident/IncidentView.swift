import SwiftUI

/// Active incident takeover — Tier 3+ is intentionally dramatic on a deep
/// destructive-red bg with cream type. Mirrors the Figma's dark/destructive moment.
struct IncidentView: View {
    let incident: Incident
    let onDispatch: () -> Void
    let onAcknowledge: () -> Void
    let onStandDown: () -> Void

    @State private var ringPulse = false

    var body: some View {
        ZStack {
            Color(hex: "#1A0306").ignoresSafeArea() // wine-900-ish base
            // soft destructive-red glow
            RadialGradient(
                colors: [Color(hex: "#D4183D").opacity(0.25), .clear],
                center: UnitPoint(x: 0.2, y: 0.2),
                startRadius: 0, endRadius: 320
            )
            .ignoresSafeArea()
            RadialGradient(
                colors: [Color(hex: "#7A1521").opacity(0.45), .clear],
                center: UnitPoint(x: 0.85, y: 0.65),
                startRadius: 0, endRadius: 360
            )
            .ignoresSafeArea()

            ScrollView(showsIndicators: false) {
                VStack(alignment: .leading, spacing: 22) {
                    Spacer().frame(height: 8)
                    SeverityBadge(tier: incident.tier, pulsing: true)
                    Text("ACTIVE INCIDENT")
                        .font(.system(size: 11, weight: .heavy, design: .monospaced))
                        .tracking(2.4)
                        .foregroundStyle(Color(hex: "#F4B8C0"))
                    Text("at \(incident.scene)")
                        .font(.system(size: 36, weight: .semibold, design: .serif))
                        .foregroundStyle(.white)
                        .lineLimit(3)
                        .fixedSize(horizontal: false, vertical: true)

                    suspectCard
                    callRing
                    actionStack

                    Spacer(minLength: 24)
                }
                .padding(.horizontal, 22)
                .padding(.bottom, 30)
            }
        }
        .onAppear { ringPulse = true }
    }

    private var suspectCard: some View {
        VStack(alignment: .leading, spacing: 10) {
            Text("SUSPECT")
                .font(.system(size: 10.5, weight: .heavy, design: .monospaced))
                .tracking(1.6)
                .foregroundStyle(Color(hex: "#F4B8C0"))
            Text(incident.suspectDescription)
                .font(.system(size: 22, weight: .semibold))
                .foregroundStyle(.white)
                .lineLimit(4)
                .fixedSize(horizontal: false, vertical: true)
            Divider().background(Color.white.opacity(0.08))
            Text("BEHAVIOR")
                .font(.system(size: 10.5, weight: .heavy, design: .monospaced))
                .tracking(1.6)
                .foregroundStyle(Color(hex: "#F4B8C0"))
            Text(incident.summary)
                .font(.system(size: 16))
                .foregroundStyle(Color(hex: "#FCE6EA"))
                .lineLimit(4)
                .fixedSize(horizontal: false, vertical: true)
            HStack(spacing: 6) {
                Image(systemName: "video.fill")
                    .foregroundStyle(Color(hex: "#F4B8C0"))
                Text(incident.cameraNode)
                    .font(.system(size: 13))
                    .foregroundStyle(Color(hex: "#FCE6EA"))
                Text("·")
                    .foregroundStyle(Color(hex: "#F4B8C0").opacity(0.6))
                Text(incident.timeElapsed)
                    .font(.system(size: 13))
                    .foregroundStyle(Color(hex: "#FCE6EA"))
            }
            .padding(.top, 4)
        }
        .padding(20)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(
            RoundedRectangle(cornerRadius: 20, style: .continuous)
                .fill(Color.white.opacity(0.06))
        )
        .overlay(
            RoundedRectangle(cornerRadius: 20, style: .continuous)
                .strokeBorder(Color.white.opacity(0.10), lineWidth: 1)
        )
    }

    private var callRing: some View {
        HStack(spacing: 12) {
            ZStack {
                Circle()
                    .strokeBorder(Color(hex: "#D4183D").opacity(0.6), lineWidth: 2)
                    .frame(width: 44, height: 44)
                    .scaleEffect(ringPulse ? 1.5 : 1.0)
                    .opacity(ringPulse ? 0.0 : 0.7)
                    .animation(.easeOut(duration: 1.4).repeatForever(autoreverses: false), value: ringPulse)
                Image(systemName: "phone.fill.arrow.up.right")
                    .foregroundStyle(.white)
                    .padding(12)
                    .background(Circle().fill(Color(hex: "#D4183D")))
            }
            VStack(alignment: .leading, spacing: 2) {
                Text("4 calls active")
                    .font(.system(size: 17, weight: .semibold))
                    .foregroundStyle(.white)
                Text("Homeowner + 3 neighbors • ringing")
                    .font(.system(size: 13))
                    .foregroundStyle(Color(hex: "#F4B8C0"))
            }
            Spacer()
        }
        .padding(.vertical, 6)
    }

    private var actionStack: some View {
        VStack(spacing: 12) {
            Button(action: onDispatch) {
                HStack {
                    Image(systemName: "exclamationmark.shield.fill")
                    Text("Dispatch 911")
                }
                .font(.system(size: 16, weight: .bold))
                .foregroundStyle(.white)
                .frame(maxWidth: .infinity)
                .padding(.vertical, 16)
                .background(
                    RoundedRectangle(cornerRadius: 14, style: .continuous)
                        .fill(Color(hex: "#D4183D"))
                )
            }
            Button(action: onAcknowledge) {
                HStack {
                    Image(systemName: "eye.fill")
                    Text("I'm watching it")
                }
                .font(.system(size: 16, weight: .bold))
                .foregroundStyle(.white)
                .frame(maxWidth: .infinity)
                .padding(.vertical, 16)
                .background(
                    RoundedRectangle(cornerRadius: 14, style: .continuous)
                        .fill(Color.white.opacity(0.10))
                )
                .overlay(
                    RoundedRectangle(cornerRadius: 14, style: .continuous)
                        .strokeBorder(Color.white.opacity(0.20), lineWidth: 1)
                )
            }
            Button(action: onStandDown) {
                Text("Stand down (false alarm)")
                    .font(.system(size: 15))
                    .foregroundStyle(Color(hex: "#F4B8C0"))
                    .frame(maxWidth: .infinity)
                    .padding(.vertical, 12)
            }
        }
    }
}
