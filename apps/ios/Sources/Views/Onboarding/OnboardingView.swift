import SwiftUI

struct OnboardingView: View {
    @EnvironmentObject var auth: AuthStore
    @State private var step: Step = .welcome
    @State private var firstPIN: String = ""
    @State private var pinError: String? = nil

    enum Step: Hashable {
        case welcome, permissions, faceScan, setPIN, confirmPIN
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
        case .welcome:    welcome
        case .permissions: permissions
        case .faceScan:   faceScan
        case .setPIN:     setPIN
        case .confirmPIN: confirmPIN
        }
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
            primaryCTA("GET STARTED") { step = .permissions }
        }
    }

    private var permissions: some View {
        VStack(alignment: .leading, spacing: 16) {
            EyeText(text: "Access", size: 32)
            Text("THIRD EYE NEEDS A FEW THINGS — ALL LOCAL.")
                .font(.mono(10)).tracking(2)
                .foregroundStyle(Hue.deep)

            VStack(spacing: 10) {
                permRow(icon: "camera.fill",         title: "Camera",        sub: "for the live feed")
                permRow(icon: "mic.fill",            title: "Microphone",    sub: "for incident calls")
                permRow(icon: "wifi",                title: "Local network", sub: "for LAN cameras")
                permRow(icon: "bell.fill",           title: "Notifications", sub: "for tier alerts")
            }

            primaryCTA("ALLOW & CONTINUE") {
                Task {
                    _ = await Permissions.requestCamera()
                    _ = await Permissions.requestMic()
                    _ = await Permissions.requestNotifications()
                    Permissions.nudgeLocalNetwork()
                    await MainActor.run { step = .faceScan }
                }
            }
        }
    }

    private var faceScan: some View {
        VStack(spacing: 22) {
            EyeText(text: "Face scan", size: 32)
            Text("HOLD STILL · SCANNING")
                .font(.mono(10)).tracking(2)
                .foregroundStyle(Hue.deep)
            FaceScanView { step = .setPIN }
            Text("Stored locally. Frames never leave the device.")
                .font(.system(size: 12))
                .foregroundStyle(Hue.deep.opacity(0.8))
        }
    }

    private var setPIN: some View {
        PINPad(
            title: "Set unlock PIN",
            subtitle: "4 digits · used to enter the console",
            length: 4
        ) { value in
            firstPIN = value
            step = .confirmPIN
        }
    }

    private var confirmPIN: some View {
        PINPad(
            title: "Confirm PIN",
            subtitle: "Enter it once more",
            length: 4,
            error: pinError
        ) { value in
            if value == firstPIN {
                auth.setPIN(value)
                auth.unlocked = true
                auth.onboarded = true
            } else {
                pinError = "Pins did not match. Try again."
                firstPIN = ""
                step = .setPIN
            }
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

    private func permRow(icon: String, title: String, sub: String) -> some View {
        HStack(spacing: 12) {
            Image(systemName: icon)
                .font(.system(size: 16, weight: .bold))
                .foregroundStyle(Hue.red)
                .frame(width: 28, height: 28)
                .background(Circle().fill(Hue.cream))
                .overlay(Circle().strokeBorder(Hue.ink, lineWidth: 2))
            VStack(alignment: .leading, spacing: 1) {
                Text(title).font(.system(size: 14, weight: .semibold)).foregroundStyle(Hue.ink)
                Text(sub).font(.mono(10)).foregroundStyle(Hue.deep.opacity(0.8))
            }
            Spacer()
        }
        .padding(.horizontal, 14).padding(.vertical, 10)
        .background(RoundedRectangle(cornerRadius: 12).fill(Hue.cream))
        .overlay(RoundedRectangle(cornerRadius: 12).strokeBorder(Hue.ink, lineWidth: 2))
    }

}

private struct ProgressBar: View {
    let step: OnboardingView.Step
    private let order: [OnboardingView.Step] = [
        .welcome, .permissions, .faceScan, .setPIN, .confirmPIN
    ]
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
