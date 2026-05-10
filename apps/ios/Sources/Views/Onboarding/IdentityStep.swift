import SwiftUI

/// Step 1.5 of onboarding — collect name + email and POST /api/identity so
/// the action_router can mint a 6-char code the web app uses to log in.
/// Mirrors apps/figma-ui's identity flow but without the QR fallback —
/// the user types the code into /login on web.
struct IdentityStep: View {
    @EnvironmentObject var identity: IdentityStore
    @EnvironmentObject var backend: BackendStatus
    let onContinue: () -> Void

    @State private var name: String = ""
    @State private var email: String = ""
    @FocusState private var focused: Field?
    enum Field: Hashable { case name, email }

    var body: some View {
        VStack(alignment: .leading, spacing: 18) {
            EyeText(text: "Hi there", size: 32)
            Text("WHO'S MOUNTING THE CAMERAS?")
                .font(.mono(10)).tracking(2)
                .foregroundStyle(Hue.deep)

            VStack(spacing: 12) {
                fieldRow(icon: "person.fill", placeholder: "Your name", text: $name, field: .name, autocap: .words)
                fieldRow(icon: "envelope.fill", placeholder: "you@example.com", text: $email, field: .email, autocap: .never, keyboard: .emailAddress)
            }

            // Backend liveness: tell user up-front if the desk Mac is unreachable
            // so they don't wonder why "Continue" hangs.
            HStack(spacing: 6) {
                Circle().fill(backend.state == .live ? Color.green : Hue.red).frame(width: 8, height: 8)
                    .overlay(Circle().strokeBorder(Hue.ink, lineWidth: 1.2))
                Text(backendLabel)
                    .font(.mono(10)).tracking(1.4)
                    .foregroundStyle(Hue.deep)
            }
            .padding(.top, 2)

            if let err = identity.error {
                Text(err)
                    .font(.system(size: 12, weight: .semibold))
                    .foregroundStyle(Hue.red)
            }

            primaryCTA(identity.submitting ? "SIGNING UP…" : "CONTINUE", enabled: canSubmit) {
                Task {
                    let ok = await identity.submit(name: name, email: email)
                    if ok { onContinue() }
                }
            }

            Text("Stays on the action router. Your phone will show a 6-character code that signs you into the web console.")
                .font(.system(size: 11))
                .foregroundStyle(Hue.deep.opacity(0.85))
                .padding(.top, 4)
        }
        .onAppear {
            // Pre-warm the engine while the user types.
            identity.startWarmup()
        }
    }

    private var canSubmit: Bool {
        !name.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
        && email.contains("@")
        && !identity.submitting
    }

    private var backendLabel: String {
        switch backend.state {
        case .live:       return "BACKEND READY"
        case .connecting: return "CONNECTING TO BACKEND…"
        case .offline:    return "BACKEND OFFLINE — IS `make run` UP?"
        }
    }

    private func fieldRow(
        icon: String,
        placeholder: String,
        text: Binding<String>,
        field: Field,
        autocap: TextInputAutocapitalization,
        keyboard: UIKeyboardType = .default
    ) -> some View {
        HStack(spacing: 10) {
            Image(systemName: icon)
                .foregroundStyle(Hue.red)
                .frame(width: 22)
            TextField(placeholder, text: text)
                .textInputAutocapitalization(autocap)
                .autocorrectionDisabled()
                .keyboardType(keyboard)
                .focused($focused, equals: field)
                .submitLabel(field == .name ? .next : .done)
                .onSubmit { focused = (field == .name) ? .email : nil }
        }
        .padding(.horizontal, 14).padding(.vertical, 12)
        .background(RoundedRectangle(cornerRadius: 12).fill(Hue.cream))
        .overlay(RoundedRectangle(cornerRadius: 12).strokeBorder(Hue.ink, lineWidth: 2))
    }

    private func primaryCTA(_ label: String, enabled: Bool, action: @escaping () -> Void) -> some View {
        Button(action: action) {
            Text(label)
                .font(.mono(12)).tracking(3)
                .foregroundStyle(Hue.cream)
                .frame(maxWidth: .infinity)
                .padding(.vertical, 14)
                .background(Capsule().fill(enabled ? Hue.red : Hue.red.opacity(0.45)))
                .overlay(Capsule().strokeBorder(Hue.ink, lineWidth: 3))
                .background(Capsule().fill(Hue.ink).offset(y: 4))
        }
        .buttonStyle(.plain)
        .disabled(!enabled)
    }
}
