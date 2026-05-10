import SwiftUI

struct SettingsView: View {
    @Binding var resetOnboarding: Bool

    var body: some View {
        ZStack {
            Theme.bg.ignoresSafeArea()

            ScrollView(showsIndicators: false) {
                VStack(alignment: .leading, spacing: 18) {
                    SectionHead(eyebrow: "Account", title: "Settings")
                        .padding(.top, 12)

                    settingsCard {
                        row(icon: "person.crop.circle", title: "Aditya Singh", subtitle: "adisin650@gmail.com")
                        Divider().background(Theme.border)
                        row(icon: "phone.fill", title: "Homeowner", subtitle: "+1 510 458 1848")
                        Divider().background(Theme.border)
                        row(icon: "person.2.fill", title: "Davishacks neighbors", subtitle: "3 numbers · all verified")
                    }

                    SectionHead(eyebrow: "Mesh", title: "Cameras")

                    settingsCard {
                        ForEach(CameraNode.mockMesh) { node in
                            HStack {
                                Circle()
                                    .fill(node.online ? Theme.destructive : Theme.textSubtle)
                                    .frame(width: 8, height: 8)
                                Text(node.name)
                                    .font(.system(size: 15, weight: .semibold))
                                    .foregroundStyle(Theme.text)
                                Spacer()
                                Text(node.online ? "ONLINE" : "OFFLINE")
                                    .font(.system(size: 10, weight: .heavy, design: .monospaced))
                                    .tracking(1.4)
                                    .foregroundStyle(node.online ? Theme.destructive : Theme.textSubtle)
                            }
                            .padding(.vertical, 6)
                            if node.id != CameraNode.mockMesh.last?.id {
                                Divider().background(Theme.border)
                            }
                        }
                    }

                    SectionHead(eyebrow: "Privacy", title: "Local-first")

                    settingsCard {
                        privacyRow(icon: "shield.fill",   text: "Frames analyzed on-device. Never uploaded.")
                        Divider().background(Theme.border)
                        privacyRow(icon: "icloud.slash",  text: "0 frames sent to the cloud.")
                        Divider().background(Theme.border)
                        privacyRow(icon: "lock.shield",   text: "Recordings encrypted at rest.")
                    }

                    Button {
                        resetOnboarding = true
                    } label: {
                        Text("Reset onboarding (demo)")
                            .font(.system(size: 14))
                            .foregroundStyle(Theme.textMuted)
                            .frame(maxWidth: .infinity)
                            .padding(.vertical, 14)
                    }

                    Spacer(minLength: 100)
                }
                .padding(.horizontal, 22)
            }
        }
    }

    private func settingsCard<Content: View>(@ViewBuilder content: () -> Content) -> some View {
        VStack(alignment: .leading, spacing: 8) { content() }
            .padding(16)
            .frame(maxWidth: .infinity, alignment: .leading)
            .background(
                RoundedRectangle(cornerRadius: 16, style: .continuous)
                    .fill(Theme.surface)
            )
            .overlay(
                RoundedRectangle(cornerRadius: 16, style: .continuous)
                    .strokeBorder(Theme.border, lineWidth: 1)
            )
    }

    private func row(icon: String, title: String, subtitle: String) -> some View {
        HStack(spacing: 12) {
            Image(systemName: icon)
                .foregroundStyle(Theme.text)
                .frame(width: 22)
            VStack(alignment: .leading, spacing: 2) {
                Text(title).font(.system(size: 15, weight: .semibold)).foregroundStyle(Theme.text)
                Text(subtitle).font(.system(size: 12)).foregroundStyle(Theme.textMuted)
            }
            Spacer()
        }
        .padding(.vertical, 6)
    }

    private func privacyRow(icon: String, text: String) -> some View {
        HStack(spacing: 12) {
            Image(systemName: icon).foregroundStyle(Theme.destructive).frame(width: 22)
            Text(text).font(.system(size: 14)).foregroundStyle(Theme.text)
            Spacer()
        }
        .padding(.vertical, 6)
    }
}
