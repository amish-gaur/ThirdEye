import SwiftUI

// 4-tab phone-friendly subset of the web NAV array. Edge + Ask were dropped
// because they were placeholder-only on web (random progress bars / canned
// answer) and only added clutter on a small screen.
enum AppTab: String, CaseIterable, Identifiable {
    case dashboard, live, timeline, settings
    var id: String { rawValue }

    var label: String {
        switch self {
        case .dashboard: return "Home"
        case .live:      return "Live"
        case .timeline:  return "Events"
        case .settings:  return "Settings"
        }
    }

    var icon: String {
        switch self {
        case .dashboard: return "waveform.path.ecg"
        case .live:      return "dot.radiowaves.left.and.right"
        case .timeline:  return "bell"
        case .settings:  return "gearshape"
        }
    }
}

struct RootView: View {
    @State private var tab: AppTab = .dashboard
    @State private var loading = true
    @StateObject private var incidents = IncidentStream()
    @StateObject private var cameras = CamerasStore()
    @StateObject private var auth = AuthStore()
    @StateObject private var backend = BackendStatus()
    @StateObject private var identity = IdentityStore()

    var body: some View {
        Group {
            if !auth.onboarded {
                OnboardingView()
            } else if !auth.unlocked {
                LockView()
            } else {
                main
            }
        }
        .environmentObject(auth)
        .environmentObject(backend)
        .environmentObject(identity)
        .onAppear {
            backend.start()
            // If onboarding was completed before but the web never claimed,
            // resume polling so the badge can flip to "linked" silently.
            if identity.identity != nil && !(identity.identity?.isClaimed ?? false) {
                identity.startPolling()
            }
        }
        .onDisappear {
            backend.stop()
            identity.stopPolling()
            identity.stopWarmup()
        }
    }

    private var main: some View {
        ZStack {
            Hue.cream.ignoresSafeArea()
            AmbientBg().opacity(0.6)

            // Decorative retro circles — pulled mostly off-screen and dimmed
            // so they read as background tint, not foreground objects.
            Circle()
                .fill(Hue.gold.opacity(0.35))
                .overlay(Circle().strokeBorder(Hue.ink.opacity(0.25), lineWidth: 2))
                .frame(width: 260, height: 260)
                .offset(x: 200, y: -260)
            Circle()
                .fill(Hue.orange.opacity(0.18))
                .overlay(Circle().strokeBorder(Hue.ink.opacity(0.20), lineWidth: 2))
                .frame(width: 300, height: 300)
                .offset(x: -210, y: 380)

            VStack(spacing: 0) {
                TopBar(tab: $tab)
                    .padding(.horizontal, 14)
                    .padding(.top, 6)

                ScrollView(showsIndicators: false) {
                    VStack(alignment: .leading, spacing: 24) {
                        content
                        AppFooter()
                    }
                    .padding(.horizontal, 14)
                    .padding(.top, 18)
                    .padding(.bottom, 32)
                }
            }

            if loading {
                RobberLoader { withAnimation(.easeOut(duration: 0.35)) { loading = false } }
                    .transition(.opacity)
                    .zIndex(50)
            }
        }
        .environmentObject(incidents)
        .environmentObject(cameras)
        .onAppear {
            incidents.start()
            cameras.start()
        }
        .onDisappear {
            incidents.stop()
            cameras.stop()
        }
    }

    @ViewBuilder
    private var content: some View {
        switch tab {
        case .dashboard: Dashboard()
        case .live:      LiveView()
        case .timeline:  TimelineView()
        case .settings:  SettingsView()
        }
    }
}
