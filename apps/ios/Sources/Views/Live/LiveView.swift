import SwiftUI

// Mirrors the LiveView function in apps/figma-ui/src/app/App.tsx.
struct LiveView: View {
    @EnvironmentObject var cameras: CamerasStore

    var body: some View {
        VStack(alignment: .leading, spacing: 24) {
            SectionHeader(title: "Live View", sub: "Streams mount here when nodes connect")

            if cameras.cameras.isEmpty {
                RobberWaiting(height: 360)
            } else {
                LazyVGrid(columns: [GridItem(.flexible(), spacing: 16)], spacing: 16) {
                    ForEach(Array(cameras.cameras.enumerated()), id: \.element.id) { idx, c in
                        CameraTile(
                            name: "\(c.node_id.uppercased()) · \(c.name.uppercased())",
                            status: statusFromEntry(c.status),
                            delay: 0.05 * Double(idx),
                            large: true,
                            streamUrl: c.stream_url
                        )
                    }
                }
            }
        }
    }
}
