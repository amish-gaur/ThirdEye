import SwiftUI

// Themed numeric pad for PIN entry/confirmation/unlock.
struct PINPad: View {
    let title: String
    let subtitle: String
    let length: Int
    var error: String? = nil
    var onComplete: (String) -> Void

    @State private var entered: String = ""

    var body: some View {
        VStack(spacing: 22) {
            VStack(spacing: 6) {
                EyeText(text: title, size: 30)
                Text(subtitle.uppercased())
                    .font(.mono(10))
                    .tracking(2)
                    .foregroundStyle(Hue.deep)
                    .multilineTextAlignment(.center)
            }

            HStack(spacing: 14) {
                ForEach(0..<length, id: \.self) { i in
                    Circle()
                        .fill(i < entered.count ? Hue.red : Hue.cream)
                        .overlay(Circle().strokeBorder(Hue.ink, lineWidth: 3))
                        .frame(width: 18, height: 18)
                }
            }

            if let err = error {
                Text(err.uppercased())
                    .font(.mono(10)).tracking(2)
                    .foregroundStyle(Hue.red)
            }

            VStack(spacing: 12) {
                ForEach(0..<3, id: \.self) { row in
                    HStack(spacing: 12) {
                        ForEach(0..<3, id: \.self) { col in
                            let n = row * 3 + col + 1
                            digit("\(n)")
                        }
                    }
                }
                HStack(spacing: 12) {
                    Spacer().frame(width: 70)
                    digit("0")
                    Button(action: backspace) {
                        Image(systemName: "delete.left")
                            .font(.system(size: 22, weight: .semibold))
                            .foregroundStyle(Hue.ink)
                            .frame(width: 70, height: 70)
                    }
                    .buttonStyle(.plain)
                }
            }
        }
        .onChange(of: entered) { _, new in
            if new.count == length {
                let value = new
                // brief delay so the last dot fills before parent transitions
                DispatchQueue.main.asyncAfter(deadline: .now() + 0.15) {
                    onComplete(value)
                    entered = ""
                }
            }
        }
    }

    private func digit(_ d: String) -> some View {
        Button(action: { tap(d) }) {
            Text(d)
                .font(.playfair(28, weight: .heavy))
                .foregroundStyle(Hue.ink)
                .frame(width: 70, height: 70)
                .background(Circle().fill(Hue.cream))
                .overlay(Circle().strokeBorder(Hue.ink, lineWidth: 3))
                .background(Circle().fill(Hue.ink).offset(y: 4))
        }
        .buttonStyle(.plain)
    }

    private func tap(_ d: String) {
        guard entered.count < length else { return }
        entered.append(d)
    }

    private func backspace() {
        guard !entered.isEmpty else { return }
        entered.removeLast()
    }
}
