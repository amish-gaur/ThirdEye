import SwiftUI

struct OnboardingView: View {
    @Binding var done: Bool
    @State private var step: Int = 0
    @State private var pairCode: String? = nil
    @State private var phone: String = "+1 510 458 1848"
    @State private var emergency: String = "+1 650 483 9625"
    @State private var consentLocation: Bool = true
    @State private var consentLocal: Bool = true

    private let stepLabels = ["Welcome", "Pair node", "Contacts", "Consents", "Done"]

    var body: some View {
        ZStack {
            Maroon.m950.ignoresSafeArea()
            Aurora().opacity(0.95)

            ScrollView(showsIndicators: false) {
                VStack(alignment: .leading, spacing: 24) {
                    hero
                    stepper
                    Group {
                        switch step {
                        case 0: WelcomeStep(onContinue: { advance() })
                        case 1: PairStep(pairCode: $pairCode, onContinue: { advance() })
                        case 2: ContactsStep(phone: $phone, emergency: $emergency, onContinue: { advance() })
                        case 3: ConsentsStep(consentLocation: $consentLocation, consentLocal: $consentLocal, onContinue: { advance() })
                        default: DoneStep(onOpen: { done = true })
                        }
                    }
                    .transition(.opacity.combined(with: .move(edge: .trailing)))
                    Spacer(minLength: 32)
                }
                .padding(.horizontal, 22)
                .padding(.top, 18)
            }
        }
    }

    private func advance() {
        withAnimation(.easeInOut(duration: 0.25)) {
            step = min(step + 1, stepLabels.count - 1)
        }
    }

    // MARK: - Hero
    private var hero: some View {
        VStack(alignment: .leading, spacing: 12) {
            Text("SETUP")
                .font(.teCaps).tracking(2.4)
                .foregroundStyle(Maroon.m200)
            (
                Text("Stand up your home ")
                    .font(.teDisplay)
                    .foregroundStyle(Cream.c50)
                +
                Text("in five minutes.")
                    .font(.teDisplay)
                    .foregroundStyle(Maroon.m100)
            )
            .lineLimit(3)
            .fixedSize(horizontal: false, vertical: true)
        }
        .padding(22)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(
            RoundedRectangle(cornerRadius: 24, style: .continuous)
                .fill(
                    LinearGradient(
                        colors: [Maroon.m700.opacity(0.55), Maroon.m900.opacity(0.85)],
                        startPoint: .topLeading, endPoint: .bottomTrailing
                    )
                )
        )
        .overlay(
            RoundedRectangle(cornerRadius: 24, style: .continuous)
                .strokeBorder(Maroon.m100.opacity(0.18), lineWidth: 1)
        )
    }

    // MARK: - Stepper
    private var stepper: some View {
        HStack(spacing: 8) {
            ForEach(0..<stepLabels.count, id: \.self) { i in
                stepDot(index: i)
            }
        }
    }

    @ViewBuilder
    private func stepDot(index i: Int) -> some View {
        let active = i <= step
        HStack(spacing: 6) {
            ZStack {
                Circle()
                    .fill(active ? Cream.c50 : Maroon.m700)
                    .frame(width: 22, height: 22)
                Text("\(i + 1)")
                    .font(.system(size: 11, weight: .bold, design: .monospaced))
                    .foregroundStyle(active ? Ink : Maroon.m200)
            }
            if i == step {
                Text(stepLabels[i])
                    .font(.system(size: 12, weight: .semibold))
                    .foregroundStyle(Cream.c50)
            }
            if i < stepLabels.count - 1 {
                Text("·").foregroundStyle(Maroon.m700)
            }
        }
    }
}

// MARK: - Step views

private struct WelcomeStep: View {
    let onContinue: () -> Void
    var body: some View {
        Card {
            Text("Sign in")
                .font(.teH2)
                .foregroundStyle(Cream.c50)
            Text("Production auth — works the same on web and mobile. We never store passwords ourselves.")
                .font(.teBody)
                .foregroundStyle(Maroon.m100)
                .fixedSize(horizontal: false, vertical: true)
            PrimaryButton(title: "Continue", action: onContinue)
        }
    }
}

private struct PairStep: View {
    @Binding var pairCode: String?
    let onContinue: () -> Void

    var body: some View {
        Card {
            Text("Pair your first camera node")
                .font(.teH2)
                .foregroundStyle(Cream.c50)
            Text("Open ThirdEye on the device that will run inference (your laptop, an old phone), and scan this code. Joins the home mesh — no router config.")
                .font(.teBody)
                .foregroundStyle(Maroon.m100)
                .fixedSize(horizontal: false, vertical: true)

            if pairCode == nil {
                PrimaryButton(title: "Generate pairing code") {
                    pairCode = randomPairCode()
                }
            } else if let code = pairCode {
                HStack(alignment: .top, spacing: 18) {
                    FauxQR(seed: code)
                    VStack(alignment: .leading, spacing: 8) {
                        Text("OR TYPE THIS CODE")
                            .font(.teCaps).tracking(1.6)
                            .foregroundStyle(Maroon.m200)
                        Text(code)
                            .font(.system(size: 28, weight: .heavy, design: .monospaced))
                            .tracking(8)
                            .foregroundStyle(Cream.c50)
                    }
                    Spacer()
                }
                PrimaryButton(title: "Node paired — continue", action: onContinue)
            }
        }
    }

    private func randomPairCode() -> String {
        let chars = Array("ABCDEFGHJKLMNPQRSTUVWXYZ23456789")
        return String((0..<6).map { _ in chars.randomElement()! })
    }
}

private struct ContactsStep: View {
    @Binding var phone: String
    @Binding var emergency: String
    let onContinue: () -> Void

    var body: some View {
        Card {
            Text("Who should we reach?")
                .font(.teH2)
                .foregroundStyle(Cream.c50)
            Text("We ring this number first on Tier 3 alerts and fan out to family on Tier 4.")
                .font(.teBody)
                .foregroundStyle(Maroon.m100)
                .fixedSize(horizontal: false, vertical: true)
            FieldInput(label: "Your phone", value: $phone)
            FieldInput(label: "Family / emergency", value: $emergency)
            PrimaryButton(title: "Continue", action: onContinue)
        }
    }
}

private struct ConsentsStep: View {
    @Binding var consentLocation: Bool
    @Binding var consentLocal: Bool
    let onContinue: () -> Void

    var body: some View {
        Card {
            Text("A few consents")
                .font(.teH2)
                .foregroundStyle(Cream.c50)
            Text("Recording laws vary by state. Tell us about this camera so the system stays on the right side of the line.")
                .font(.teBody)
                .foregroundStyle(Maroon.m100)
                .fixedSize(horizontal: false, vertical: true)
            ConsentRow(text: "I'm permitted to record at this location.", checked: $consentLocation)
            ConsentRow(text: "Run inference locally on this device. Frames don't leave my home network.", checked: $consentLocal)
            PrimaryButton(title: "Continue", action: onContinue, enabled: consentLocation && consentLocal)
        }
    }
}

private struct DoneStep: View {
    let onOpen: () -> Void
    var body: some View {
        Card {
            HStack {
                Image(systemName: "checkmark.shield.fill")
                    .font(.system(size: 30))
                    .foregroundStyle(Cream.c50)
                Text("You're set.")
                    .font(.teH1)
                    .foregroundStyle(Cream.c50)
            }
            Text("Your camera mesh is live. Add more nodes anytime from Settings.")
                .font(.teBody)
                .foregroundStyle(Maroon.m100)
                .fixedSize(horizontal: false, vertical: true)
            PrimaryButton(title: "Open the dashboard", action: onOpen)
        }
    }
}

// MARK: - Shared bits

private struct Card<Content: View>: View {
    @ViewBuilder let content: () -> Content
    var body: some View {
        VStack(alignment: .leading, spacing: 14) {
            content()
        }
        .padding(22)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(
            RoundedRectangle(cornerRadius: 22, style: .continuous)
                .fill(
                    LinearGradient(
                        colors: [Maroon.m700.opacity(0.55), Maroon.m900.opacity(0.85)],
                        startPoint: .topLeading, endPoint: .bottomTrailing
                    )
                )
        )
        .overlay(
            RoundedRectangle(cornerRadius: 22, style: .continuous)
                .strokeBorder(Maroon.m100.opacity(0.14), lineWidth: 1)
        )
    }
}

private struct PrimaryButton: View {
    let title: String
    let action: () -> Void
    var enabled: Bool = true
    var body: some View {
        Button(action: action) {
            Text(title)
                .font(.teButton)
                .foregroundStyle(enabled ? Ink : Ink.opacity(0.5))
                .padding(.vertical, 12)
                .padding(.horizontal, 22)
                .background(
                    Capsule().fill(enabled ? Cream.c50 : Cream.c50.opacity(0.4))
                )
        }
        .disabled(!enabled)
    }
}

private struct FieldInput: View {
    let label: String
    @Binding var value: String
    var body: some View {
        VStack(alignment: .leading, spacing: 6) {
            Text(label.uppercased())
                .font(.teCaps).tracking(1.4)
                .foregroundStyle(Maroon.m200)
            TextField("", text: $value)
                .font(.teBody)
                .foregroundStyle(Cream.c50)
                .padding(.horizontal, 14)
                .padding(.vertical, 12)
                .background(
                    RoundedRectangle(cornerRadius: 12, style: .continuous)
                        .fill(Maroon.m900.opacity(0.6))
                )
                .overlay(
                    RoundedRectangle(cornerRadius: 12, style: .continuous)
                        .strokeBorder(Maroon.m300.opacity(0.25), lineWidth: 1)
                )
                .keyboardType(.phonePad)
                .autocorrectionDisabled()
        }
    }
}

private struct ConsentRow: View {
    let text: String
    @Binding var checked: Bool
    var body: some View {
        Button(action: { checked.toggle() }) {
            HStack(alignment: .top, spacing: 10) {
                Image(systemName: checked ? "checkmark.square.fill" : "square")
                    .foregroundStyle(checked ? Cream.c50 : Maroon.m200)
                    .font(.system(size: 18))
                Text(text)
                    .font(.teBody)
                    .foregroundStyle(Cream.c50.opacity(0.9))
                    .multilineTextAlignment(.leading)
                Spacer()
            }
        }
        .buttonStyle(.plain)
    }
}

private struct FauxQR: View {
    let seed: String
    private let cells = 17

    var body: some View {
        let grid = generate()
        return VStack(spacing: 1) {
            ForEach(0..<cells, id: \.self) { row in
                HStack(spacing: 1) {
                    ForEach(0..<cells, id: \.self) { col in
                        Rectangle()
                            .fill(grid[row * cells + col] ? Ink : Color.clear)
                            .aspectRatio(1, contentMode: .fit)
                    }
                }
            }
        }
        .padding(8)
        .frame(width: 168, height: 168)
        .background(
            RoundedRectangle(cornerRadius: 12, style: .continuous)
                .fill(Cream.c50)
        )
    }

    private func generate() -> [Bool] {
        var h: UInt64 = 0
        for ch in seed.unicodeScalars {
            h = (h &* 33 &+ UInt64(ch.value))
        }
        var s = h
        var out: [Bool] = []
        for _ in 0..<(cells * cells) {
            s = s &* 1664525 &+ 1013904223
            out.append((s & 1) == 1)
        }
        return out
    }
}
