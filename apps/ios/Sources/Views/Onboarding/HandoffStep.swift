import SwiftUI

/// Shows the 6-char identity code on the phone with the URL to type it on
/// the web console. Polls /api/identity/by-code/{code}; when the web side
/// claims, switches to "linked" and auto-advances. The user can also tap
/// "skip for now" to keep onboarding flowing — claim can happen later
/// (Settings shows the code until claimed).
struct HandoffStep: View {
    @EnvironmentObject var identity: IdentityStore
    @EnvironmentObject var backend: BackendStatus
    let onContinue: () -> Void

    var body: some View {
        VStack(spacing: 22) {
            EyeText(text: identity.identity?.isClaimed == true ? "Linked" : "Pair web", size: 32)

            Text(identity.identity?.isClaimed == true
                 ? "WEB CONSOLE NOW SIGNED IN"
                 : "TYPE THIS CODE ON THE WEB APP")
                .font(.mono(10)).tracking(2)
                .foregroundStyle(Hue.deep)

            codeCard

            stepInstructions

            primaryCTA(
                identity.identity?.isClaimed == true ? "ENTER" : "ENTER WITHOUT WEB",
                action: onContinue
            )
        }
        .onAppear { identity.startPolling() }
        .onChange(of: identity.identity?.isClaimed ?? false) { _, claimed in
            // Web side just claimed → auto-drop into the home view after a
            // half-second so the user registers the "LINKED" flash.
            if claimed {
                DispatchQueue.main.asyncAfter(deadline: .now() + 0.6) {
                    onContinue()
                }
            }
        }
        .animation(.easeInOut(duration: 0.25), value: identity.identity?.status)
    }

    private var codeCard: some View {
        VStack(spacing: 8) {
            Text(identity.identity?.code ?? "------")
                .font(.system(size: 44, weight: .black, design: .monospaced))
                .tracking(8)
                .foregroundStyle(Hue.ink)
                .padding(.horizontal, 22)
                .padding(.vertical, 18)
                .frame(maxWidth: .infinity)
                .background(RoundedRectangle(cornerRadius: 16).fill(Hue.gold))
                .overlay(RoundedRectangle(cornerRadius: 16).strokeBorder(Hue.ink, lineWidth: 3))
                .background(RoundedRectangle(cornerRadius: 16).fill(Hue.ink).offset(y: 4))

            HStack(spacing: 8) {
                Circle()
                    .fill(identity.identity?.isClaimed == true ? Color.green : Hue.red)
                    .frame(width: 8, height: 8)
                    .overlay(Circle().strokeBorder(Hue.ink, lineWidth: 1.2))
                Text(statusLabel)
                    .font(.mono(10)).tracking(1.4)
                    .foregroundStyle(Hue.deep)
            }
            .padding(.top, 4)
        }
    }

    private var stepInstructions: some View {
        VStack(alignment: .leading, spacing: 8) {
            instruction(num: "1", text: "Open localhost:5173 on your laptop")
            instruction(num: "2", text: "Type the code above")
            instruction(num: "3", text: "This phone drops into home automatically")
        }
        .padding(.horizontal, 14).padding(.vertical, 12)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(RoundedRectangle(cornerRadius: 12).fill(Hue.cream))
        .overlay(RoundedRectangle(cornerRadius: 12).strokeBorder(Hue.ink, lineWidth: 2))
    }

    private var statusLabel: String {
        if identity.identity?.isClaimed == true {
            return "WEB CLAIMED · CONTINUING…"
        }
        return backend.state == .live ? "WAITING FOR WEB…" : "BACKEND OFFLINE"
    }

    private func instruction(num: String, text: String) -> some View {
        HStack(alignment: .top, spacing: 10) {
            Text(num)
                .font(.mono(11)).bold()
                .foregroundStyle(Hue.cream)
                .frame(width: 22, height: 22)
                .background(Circle().fill(Hue.red))
                .overlay(Circle().strokeBorder(Hue.ink, lineWidth: 1.5))
            Text(text)
                .font(.system(size: 13))
                .foregroundStyle(Hue.ink)
            Spacer()
        }
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
