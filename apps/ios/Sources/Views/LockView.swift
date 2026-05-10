import SwiftUI

// Launch lock screen — themed face-scan animation, then PIN.
// The face-scan is theatre (always succeeds), but the PIN is real.
struct LockView: View {
    @EnvironmentObject var auth: AuthStore
    @State private var phase: Phase = .scanning
    @State private var pinError: String? = nil

    enum Phase { case scanning, pin }

    var body: some View {
        ZStack {
            Hue.cream.ignoresSafeArea()
            AmbientBg().opacity(0.4)

            VStack(spacing: 28) {
                Spacer()
                if phase == .scanning {
                    EyeText(text: "Welcome back", size: 30)
                    Text("HOLD STILL · SCANNING")
                        .font(.mono(11)).tracking(2.5)
                        .foregroundStyle(Hue.deep)
                    // Re-unlock scan: shorter than first-run enrollment (one
                    // pose's worth) — just enough to feel like a Face ID hit
                    // before the PIN screen takes over.
                    FaceScanView(perPose: 0.6) {
                        // Face scan succeeds visually; we still gate on the PIN.
                        withAnimation(.easeOut(duration: 0.35)) { phase = .pin }
                    }
                } else {
                    PINPad(
                        title: "Enter PIN",
                        subtitle: "to unlock the console",
                        length: 4,
                        error: pinError
                    ) { value in
                        if auth.verify(value) {
                            withAnimation(.easeOut(duration: 0.3)) { auth.unlocked = true }
                        } else {
                            pinError = "Incorrect. Try again."
                        }
                    }
                }
                Spacer()
            }
            .padding(.horizontal, 22)
        }
    }
}
