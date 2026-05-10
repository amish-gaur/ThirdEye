import SwiftUI

struct RootView: View {
    @AppStorage("onboarded") private var onboarded: Bool = false

    var body: some View {
        if onboarded {
            HomeShell(onReset: { onboarded = false })
        } else {
            OnboardingView(done: Binding(
                get: { onboarded },
                set: { onboarded = $0 }
            ))
        }
    }
}

private struct HomeShell: View {
    let onReset: () -> Void
    @State private var activeIncident: Incident? = nil
    @State private var showingIncident = false
    @State private var resetOnboarding = false
    @State private var tab: Tab = .dashboard

    enum Tab: Hashable { case dashboard, timeline, settings }

    var body: some View {
        ZStack(alignment: .top) {
            ZStack {
                switch tab {
                case .dashboard:
                    ZStack {
                        DashboardView(activeIncident: $activeIncident, cameras: CameraNode.mockMesh)
                        VStack {
                            Spacer()
                            DemoFireButton {
                                withAnimation(.spring(response: 0.45, dampingFraction: 0.85)) {
                                    activeIncident = Incident.mockActive
                                }
                                DispatchQueue.main.asyncAfter(deadline: .now() + 0.6) {
                                    showingIncident = true
                                }
                            }
                            .padding(.bottom, 92)
                            .padding(.horizontal, 20)
                        }
                    }
                case .timeline:
                    TimelineView()
                case .settings:
                    SettingsView(resetOnboarding: $resetOnboarding)
                }
            }
            .padding(.top, 56) // leave room for top bar

            SafeWatchTopBar()

            VStack { Spacer(); TabBar(tab: $tab) }
        }
        .fullScreenCover(isPresented: $showingIncident) {
            if let incident = activeIncident {
                IncidentView(
                    incident: incident,
                    onDispatch:    { showingIncident = false },
                    onAcknowledge: { showingIncident = false },
                    onStandDown: {
                        showingIncident = false
                        withAnimation { activeIncident = nil }
                    }
                )
            }
        }
        .onChange(of: resetOnboarding) { _, newValue in
            if newValue { onReset() }
        }
    }
}

private struct TabBar: View {
    @Binding var tab: HomeShell.Tab

    var body: some View {
        HStack(spacing: 0) {
            tabButton(.dashboard, label: "Home", icon: "house.fill")
            tabButton(.timeline,  label: "Timeline", icon: "clock.arrow.circlepath")
            tabButton(.settings,  label: "Settings", icon: "gearshape.fill")
        }
        .padding(.horizontal, 14)
        .padding(.vertical, 10)
        .background(
            RoundedRectangle(cornerRadius: 22, style: .continuous)
                .fill(Maroon.m900.opacity(0.92))
        )
        .overlay(
            RoundedRectangle(cornerRadius: 22, style: .continuous)
                .strokeBorder(Maroon.m700, lineWidth: 1)
        )
        .shadow(color: Maroon.m950.opacity(0.6), radius: 30, y: 12)
        .padding(.horizontal, 22)
        .padding(.bottom, 14)
    }

    private func tabButton(_ t: HomeShell.Tab, label: String, icon: String) -> some View {
        Button {
            withAnimation(.easeInOut(duration: 0.2)) { tab = t }
        } label: {
            VStack(spacing: 3) {
                Image(systemName: icon)
                    .font(.system(size: 18, weight: .semibold))
                Text(label)
                    .font(.system(size: 10, weight: .bold))
            }
            .foregroundStyle(tab == t ? Cream.c50 : Maroon.m200)
            .frame(maxWidth: .infinity)
            .padding(.vertical, 6)
        }
    }
}

private struct DemoFireButton: View {
    let action: () -> Void
    var body: some View {
        Button(action: action) {
            HStack(spacing: 10) {
                Image(systemName: "bolt.fill")
                Text("Simulate Tier 3 alert")
                    .font(.teButton)
            }
            .foregroundStyle(Ink)
            .frame(maxWidth: .infinity)
            .padding(.vertical, 14)
            .background(
                RoundedRectangle(cornerRadius: 14, style: .continuous)
                    .fill(Cream.c50)
            )
            .shadow(color: Maroon.m900.opacity(0.5), radius: 18, x: 0, y: 8)
        }
    }
}
