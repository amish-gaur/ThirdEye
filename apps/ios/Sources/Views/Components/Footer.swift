import SwiftUI

// Mirrors the Footer function in apps/figma-ui/src/app/App.tsx.
struct AppFooter: View {
    var body: some View {
        VStack(spacing: 8) {
            Rectangle().fill(Hue.ink).frame(height: 3)
            HStack {
                Text("THIRD EYE · LOCAL-FIRST")
                Spacer()
                Text("FRAMES NEVER LEAVE THE NODE")
                Spacer()
                Text("BUILD 0.4.2 · \(yearString)")
            }
            .font(.mono(9))
            .tracking(2.5)
            .foregroundStyle(Hue.deep)
        }
        .padding(.top, 12)
    }

    private var yearString: String {
        let f = DateFormatter()
        f.dateFormat = "yyyy"
        return f.string(from: Date())
    }
}
