import SwiftUI

struct IncidentView: View {
    let incident: Incident
    let onDispatch: () -> Void
    let onAcknowledge: () -> Void
    let onStandDown: () -> Void

    @State private var ringPulse = false

    var body: some View {
        ZStack {
            Maroon.m950.ignoresSafeArea()
            Aurora().opacity(0.95)

            ScrollView(showsIndicators: false) {
                VStack(alignment: .leading, spacing: 22) {
                    Spacer().frame(height: 8)
                    SeverityBadge(tier: incident.tier, pulsing: true)
                    Text("ACTIVE INCIDENT")
                        .font(.teCaps)
                        .tracking(2.4)
                        .foregroundStyle(Maroon.m100)
                    Text("at \(incident.scene)")
                        .font(.teDisplay)
                        .foregroundStyle(Cream.c50)
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
                .font(.teCaps)
                .tracking(1.6)
                .foregroundStyle(Maroon.m200)
            Text(incident.suspectDescription)
                .font(.teH2)
                .foregroundStyle(Cream.c50)
                .lineLimit(4)
                .fixedSize(horizontal: false, vertical: true)
            Divider().background(Maroon.m800)
            Text("BEHAVIOR")
                .font(.teCaps)
                .tracking(1.6)
                .foregroundStyle(Maroon.m200)
            Text(incident.summary)
                .font(.teH3)
                .foregroundStyle(Maroon.m50)
                .lineLimit(4)
                .fixedSize(horizontal: false, vertical: true)
            HStack(spacing: 6) {
                Image(systemName: "video.fill")
                    .foregroundStyle(Maroon.m200)
                Text(incident.cameraNode)
                    .font(.teBodySm)
                    .foregroundStyle(Maroon.m100)
                Text("•")
                    .foregroundStyle(Maroon.m200)
                Text(incident.timeElapsed)
                    .font(.teBodySm)
                    .foregroundStyle(Maroon.m100)
            }
            .padding(.top, 4)
        }
        .padding(20)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(
            RoundedRectangle(cornerRadius: 20, style: .continuous)
                .fill(
                    LinearGradient(
                        colors: [Maroon.m700, Maroon.m900],
                        startPoint: .topLeading,
                        endPoint: .bottomTrailing
                    )
                )
        )
        .overlay(
            RoundedRectangle(cornerRadius: 20, style: .continuous)
                .strokeBorder(Maroon.m100.opacity(0.18), lineWidth: 1)
        )
    }

    private var callRing: some View {
        HStack(spacing: 12) {
            ZStack {
                Circle()
                    .strokeBorder(Maroon.m300.opacity(0.6), lineWidth: 2)
                    .frame(width: 44, height: 44)
                    .scaleEffect(ringPulse ? 1.5 : 1.0)
                    .opacity(ringPulse ? 0.0 : 0.7)
                    .animation(
                        .easeOut(duration: 1.4).repeatForever(autoreverses: false),
                        value: ringPulse
                    )
                Image(systemName: "phone.fill.arrow.up.right")
                    .foregroundStyle(Cream.c50)
                    .padding(12)
                    .background(Circle().fill(Maroon.m600))
            }
            VStack(alignment: .leading, spacing: 2) {
                Text("4 calls active")
                    .font(.teH3)
                    .foregroundStyle(Cream.c50)
                Text("Homeowner + 3 neighbors • ringing")
                    .font(.teBodySm)
                    .foregroundStyle(Maroon.m200)
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
                .font(.teButton)
                .foregroundStyle(Ink)
                .frame(maxWidth: .infinity)
                .padding(.vertical, 16)
                .background(
                    RoundedRectangle(cornerRadius: 14, style: .continuous)
                        .fill(Cream.c50)
                )
            }
            Button(action: onAcknowledge) {
                HStack {
                    Image(systemName: "eye.fill")
                    Text("I'm watching it")
                }
                .font(.teButton)
                .foregroundStyle(Cream.c50)
                .frame(maxWidth: .infinity)
                .padding(.vertical, 16)
                .background(
                    RoundedRectangle(cornerRadius: 14, style: .continuous)
                        .fill(Maroon.m700)
                )
                .overlay(
                    RoundedRectangle(cornerRadius: 14, style: .continuous)
                        .strokeBorder(Maroon.m300.opacity(0.5), lineWidth: 1)
                )
            }
            Button(action: onStandDown) {
                Text("Stand down (false alarm)")
                    .font(.teBody)
                    .foregroundStyle(Maroon.m200)
                    .frame(maxWidth: .infinity)
                    .padding(.vertical, 12)
            }
        }
    }
}
