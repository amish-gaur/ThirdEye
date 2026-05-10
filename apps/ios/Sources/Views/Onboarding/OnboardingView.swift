import SwiftUI

struct OnboardingView: View {
    @EnvironmentObject var auth: AuthStore
    @EnvironmentObject var identity: IdentityStore
    @State private var step: Step = .welcome

    enum Step: Hashable {
        case welcome, identity, handoff, faceScan
    }

    var body: some View {
        ZStack {
            Hue.cream.ignoresSafeArea()
            AmbientBg().opacity(0.5)
            decorativeShapes

            VStack {
                ProgressBar(step: step)
                    .padding(.horizontal, 22)
                    .padding(.top, 14)

                Spacer()
                content
                    .padding(.horizontal, 22)
                Spacer()
            }
        }
    }

    @ViewBuilder
    private var content: some View {
        switch step {
        case .welcome:  welcome
        case .identity: IdentityStep(onContinue: { step = .handoff })
        case .handoff:  HandoffStep(onContinue: { step = .faceScan })
        case .faceScan: faceScan
        }
    }

    private var faceScan: some View {
        VStack(spacing: 22) {
            EyeText(text: "Face scan", size: 32)
            Text("FOLLOW THE ARROW · 4 ANGLES")
                .font(.mono(10)).tracking(2)
                .foregroundStyle(Hue.deep)
            FaceScanView { completeOnboarding() }
            Text("Visual only. Frames never leave the device.")
                .font(.system(size: 12))
                .foregroundStyle(Hue.deep.opacity(0.8))
        }
    }

    /// Last step of the demo flow. Web has claimed the code (or the user
    /// tapped "ENTER ANYWAY"), so we mark the device onboarded and unlocked
    /// and drop straight into the home view. PIN/face/permissions are
    /// reserved for a future build — `make run` wipes the app every time
    /// so this fresh-start path is always what we want.
    private func completeOnboarding() {
        if !auth.hasPIN { auth.setPIN("0000") }
        auth.unlocked = true
        auth.onboarded = true
    }

    private var welcome: some View {
        VStack(spacing: 22) {
            SecurityEye(size: 180)
            VStack(spacing: 6) {
                EyeText(text: "Third Eye", size: 36)
                Text("EVERYTHING CALM AT HOME.")
                    .font(.mono(11)).tracking(2)
                    .foregroundStyle(Hue.deep)
            }
            Text("Severity-aware sensors. Frames stay on-device. We escalate only when the world stops being calm.")
                .font(.system(size: 14))
                .foregroundStyle(Hue.deep)
                .multilineTextAlignment(.center)
                .padding(.horizontal, 16)
            primaryCTA("GET STARTED") { step = .identity }
        }
    }

    private var decorativeShapes: some View {
        ZStack {
            Circle()
                .fill(Hue.gold.opacity(0.35))
                .overlay(Circle().strokeBorder(Hue.ink.opacity(0.25), lineWidth: 2))
                .frame(width: 240, height: 240)
                .offset(x: 180, y: -260)
            Circle()
                .fill(Hue.orange.opacity(0.18))
                .overlay(Circle().strokeBorder(Hue.ink.opacity(0.20), lineWidth: 2))
                .frame(width: 280, height: 280)
                .offset(x: -180, y: 360)
        }
        .allowsHitTesting(false)
    }

    private func primaryCTA(_ label: String, action: @escaping () -> Void) -> some View {
        Button(action: action) {
            Text(label)
                .font(.mono(12)).tracking(3)
                .foregroundStyle(Hue.cream)
                .frame(maxWidth: .infinity)
                .padding(.vertical, 14)
                .background(Capsule().fill(Hue.red))
                .overlay(Capsule().strokeBorder(Hue.ink, lineWidth: 3))
                .background(Capsule().fill(Hue.ink).offset(y: 4))
        }
        .buttonStyle(.plain)
    }

}

private struct ProgressBar: View {
    let step: OnboardingView.Step
    private let order: [OnboardingView.Step] = [.welcome, .identity, .handoff, .faceScan]
    var idx: Int { order.firstIndex(of: step) ?? 0 }

    var body: some View {
        HStack(spacing: 4) {
            ForEach(0..<order.count, id: \.self) { i in
                Capsule()
                    .fill(i <= idx ? Hue.red : Hue.cream)
                    .overlay(Capsule().strokeBorder(Hue.ink, lineWidth: 1.5))
                    .frame(height: 6)
            }
        }
    }
}
