import SwiftUI

struct SettingsView: View {
    @Binding var resetOnboarding: Bool

    var body: some View {
        ZStack {
            Maroon.m950.ignoresSafeArea()
            Aurora().opacity(0.30)

            ScrollView(showsIndicators: false) {
                VStack(alignment: .leading, spacing: 18) {
                    SectionHead(eyebrow: "Account", title: "Settings")
                        .padding(.top, 12)

                    settingsCard {
                        row(icon: "person.crop.circle", title: "Aditya Singh", subtitle: "adisin650@gmail.com")
                        Divider().background(Maroon.m800)
                        row(icon: "phone.fill", title: "Homeowner", subtitle: "+1 510 458 1848")
                        Divider().background(Maroon.m800)
                        row(icon: "person.2.fill", title: "Davishacks neighbors", subtitle: "3 numbers · all verified")
                    }

                    SectionHead(eyebrow: "Mesh", title: "Cameras")

                    settingsCard {
                        ForEach(CameraNode.mockMesh) { node in
                            HStack {
                                Circle()
                                    .fill(node.online ? Maroon.m200 : Maroon.m700)
                                    .frame(width: 8, height: 8)
                                Text(node.name)
                                    .font(.teH3)
                                    .foregroundStyle(Cream.c50)
                                Spacer()
                                Text(node.online ? "ONLINE" : "OFFLINE")
                                    .font(.teCaps).tracking(1.4)
                                    .foregroundStyle(node.online ? Maroon.m100 : Maroon.m200)
                            }
                            .padding(.vertical, 6)
                            if node.id != CameraNode.mockMesh.last?.id {
                                Divider().background(Maroon.m800)
                            }
                        }
                    }

                    SectionHead(eyebrow: "Privacy", title: "Local-first")

                    settingsCard {
                        privacyRow(icon: "shield.fill",   text: "Frames analyzed on-device. Never uploaded.")
                        Divider().background(Maroon.m800)
                        privacyRow(icon: "icloud.slash",  text: "0 frames sent to the cloud.")
                        Divider().background(Maroon.m800)
                        privacyRow(icon: "lock.shield",   text: "Recordings encrypted at rest.")
                    }

                    Button {
                        resetOnboarding = true
                    } label: {
                        Text("Reset onboarding (demo)")
                            .font(.teBody)
                            .foregroundStyle(Maroon.m200)
                            .frame(maxWidth: .infinity)
                            .padding(.vertical, 14)
                    }

                    Spacer(minLength: 80)
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
                    .fill(Color.black.opacity(0.30))
            )
            .overlay(
                RoundedRectangle(cornerRadius: 16, style: .continuous)
                    .strokeBorder(Maroon.m800, lineWidth: 1)
            )
    }

    private func row(icon: String, title: String, subtitle: String) -> some View {
        HStack(spacing: 12) {
            Image(systemName: icon)
                .foregroundStyle(Maroon.m100)
                .frame(width: 22)
            VStack(alignment: .leading, spacing: 2) {
                Text(title).font(.teH3).foregroundStyle(Cream.c50)
                Text(subtitle).font(.teBodySm).foregroundStyle(Maroon.m200)
            }
            Spacer()
        }
        .padding(.vertical, 6)
    }

    private func privacyRow(icon: String, text: String) -> some View {
        HStack(spacing: 12) {
            Image(systemName: icon).foregroundStyle(Maroon.m100).frame(width: 22)
            Text(text).font(.teBody).foregroundStyle(Cream.c50.opacity(0.9))
            Spacer()
        }
        .padding(.vertical, 6)
    }
}
