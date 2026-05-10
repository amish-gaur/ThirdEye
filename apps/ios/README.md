# ThirdEye iOS

Native SwiftUI iOS app — dark wine + cream design, tier-based incident UI.

## Prerequisites

- **Xcode 15+** (already installed: `xcodebuild` is on your `$PATH`)
- **xcodegen**: `brew install xcodegen` (already installed)
- **Apple ID signed in to Xcode**: Xcode → Settings → Accounts → "+" → sign in
- **iPhone 14 cable (USB-C / Lightning)** + a working USB cable
- The phone has been **trusted on this Mac** (plug in, unlock, tap "Trust")

## One-time setup (signing)

Personal Apple IDs need a unique bundle ID and a team ID in `signing.local.xcconfig`:

```sh
cd apps/ios
cp signing.local.xcconfig.example signing.local.xcconfig
```

Then edit `signing.local.xcconfig` and replace `ABCDEFGHIJ` with your 10-character team ID. To find it:

- **Easy way**: Xcode → Settings → Accounts → click your Apple ID → look for "Team ID" in the right pane.
- **CLI way**: `security find-identity -v -p codesigning` — the 10 chars in parentheses.

Pick a bundle ID nobody else has registered, e.g. `com.aditya.thirdeye`.

`signing.local.xcconfig` is gitignored, so your team ID stays local.

## Generate the project

```sh
xcodegen generate
```

This creates `ThirdEye.xcodeproj` from `project.yml`. Re-run any time you add/move source files.

## Run on the simulator (no signing needed)

```sh
xcodebuild -project ThirdEye.xcodeproj -scheme ThirdEye \
  -destination "platform=iOS Simulator,name=iPhone 16" \
  -configuration Debug CODE_SIGNING_ALLOWED=NO build
```

Or just open `ThirdEye.xcodeproj` in Xcode, pick a simulator from the device menu (top of window), and hit **Cmd+R**.

## Run on your iPhone 14 (USB-tethered)

1. Plug iPhone 14 into the Mac. Unlock the phone, tap **Trust** if prompted.
2. Open `ThirdEye.xcodeproj` in Xcode.
3. In the device menu at the top of the window, pick **your iPhone 14** (not a simulator).
4. Press **Cmd+R**.

First-run gotchas:

- *"Could not launch — Untrusted Developer"* on the phone: open **Settings → General → VPN & Device Management → Developer App** → tap your Apple ID → **Trust**. Then tap the icon on the home screen again.
- *Signing error in Xcode*: with `signing.local.xcconfig` filled in, automatic signing should Just Work. If Xcode complains, click **"Try Again"** or click the project in the navigator → **Signing & Capabilities** → make sure your **Team** is selected and **Bundle Identifier** is unique.
- *Build fails with `LOCAL_DEVELOPMENT_TEAM` undefined*: you didn't copy `signing.local.xcconfig.example` → `signing.local.xcconfig` yet.

## Demo flow

Launch the app → "Davishacks mesh" dashboard with 4 camera tiles (front porch, driveway, backyard, garage) and an "All clear" banner. Tap **"Simulate Tier 3 alert"** at the bottom — the banner morphs into an active-incident hero, then fullscreen-presents the IncidentView with:

- Pulsing severity badge
- Suspect description + behavior + camera location
- "4 calls active" status (homeowner + 3 neighbors ringing)
- Action buttons: **Dispatch 911 · I'm watching it · Stand down**

Stand down resets the dashboard. Acknowledge / Dispatch dismisses the sheet.

## Project layout

```
apps/ios/
├── project.yml              # XcodeGen spec — source of truth
├── signing.local.xcconfig   # gitignored — your team ID + bundle ID
├── Sources/
│   ├── App/                 # @main entry
│   ├── Theme/               # Palette (full maroon scale + cream) + typography
│   ├── Models/              # Tier, Incident, CameraNode + mock data
│   └── Views/
│       ├── RootView.swift
│       ├── Dashboard/       # DashboardView + CameraTile
│       ├── Incident/        # IncidentView (active alert)
│       └── Components/      # SeverityBadge, etc.
└── Supporting/
    └── Info.plist
```

Hex values in `Sources/Theme/Palette.swift` mirror `packages/ui/src/tokens.ts` exactly.
