import SwiftUI

// Mirrors the SectionHeader function in apps/figma-ui/src/app/App.tsx.
struct SectionHeader: View {
    let title: String
    let sub: String

    var body: some View {
        VStack(alignment: .leading, spacing: 6) {
            EyeText(text: title, size: 44)
            Text(sub.uppercased())
                .font(.mono(11))
                .tracking(2.5)
                .foregroundStyle(Hue.deep)
        }
    }
}
