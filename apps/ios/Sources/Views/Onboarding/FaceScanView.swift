import SwiftUI
@preconcurrency import AVFoundation

/// Live front-camera face-scan theater. Cycles through four head poses
/// (right, bottom-right, bottom-left, top-left) with on-screen arrows.
/// Frames are NEVER captured or persisted — the AVCaptureSession is
/// session-scoped and torn down on completion. This is purely visual to
/// give onboarding the rhythm of a real Face ID enrollment.
struct FaceScanView: View {
    /// Seconds spent on each of the four poses. ~2.5s each → ~10s total
    /// after the brief "hold still" preamble.
    var perPose: Double = 2.4
    var onSuccess: () -> Void

    @State private var poseIndex: Int = 0
    @State private var totalProgress: CGFloat = 0
    @State private var pulse = false
    @State private var done = false
    @State private var permissionDenied = false

    private static let poses: [Pose] = [
        Pose(label: "Look right",        arrow: "arrow.right",       angle: 0),
        Pose(label: "Tilt down-right",   arrow: "arrow.down.right",  angle: 45),
        Pose(label: "Tilt down-left",    arrow: "arrow.down.left",   angle: 135),
        Pose(label: "Tilt up-left",      arrow: "arrow.up.left",     angle: 225),
    ]

    var body: some View {
        VStack(spacing: 16) {
            scannerStack

            Text(prompt)
                .font(.mono(11)).tracking(2)
                .foregroundStyle(Hue.deep)
                .frame(height: 18)

            poseDots
        }
        .onAppear { begin() }
    }

    // ----- main scanner stack -------------------------------------------

    private var scannerStack: some View {
        ZStack {
            // Live front-camera preview, masked to a circle.
            CameraPreviewView(permissionDenied: $permissionDenied)
                .frame(width: 240, height: 240)
                .clipShape(Circle())
                .overlay(
                    Circle().strokeBorder(Hue.cream, lineWidth: 4)
                )

            // Outer dotted Face-ID-style ring.
            DottedRing(count: 60, lineWidth: 3, length: 8, radius: 130)
                .foregroundStyle(Hue.ink.opacity(0.30))

            // Sweeping progress arc — driven by totalProgress 0…1 across
            // the whole scan so the ring fills smoothly.
            Circle()
                .trim(from: 0, to: totalProgress)
                .stroke(Hue.red, style: StrokeStyle(lineWidth: 5, lineCap: .round))
                .frame(width: 268, height: 268)
                .rotationEffect(.degrees(-90))

            // Direction arrow + pulsing ring around the active pose
            // direction. Sits at the edge of the preview circle.
            if !done && !permissionDenied {
                directionArrow
            }

            if done {
                Image(systemName: "checkmark")
                    .font(.system(size: 80, weight: .bold))
                    .foregroundStyle(Hue.red)
                    .transition(.scale.combined(with: .opacity))
            }

            if permissionDenied {
                VStack(spacing: 6) {
                    Image(systemName: "camera.fill.badge.ellipsis")
                        .font(.system(size: 36, weight: .bold))
                        .foregroundStyle(Hue.red)
                    Text("CAMERA OFF")
                        .font(.mono(10)).tracking(2)
                        .foregroundStyle(Hue.deep)
                    Text("Allow camera in Settings")
                        .font(.system(size: 11))
                        .foregroundStyle(Hue.deep.opacity(0.8))
                }
                .padding()
                .background(Capsule().fill(Hue.cream))
            }
        }
        .frame(width: 320, height: 320)
    }

    private var directionArrow: some View {
        let pose = Self.poses[min(poseIndex, Self.poses.count - 1)]
        let radians = pose.angle * .pi / 180
        return Image(systemName: pose.arrow)
            .font(.system(size: 28, weight: .heavy))
            .foregroundStyle(Hue.cream)
            .padding(12)
            .background(Circle().fill(Hue.red))
            .overlay(Circle().strokeBorder(Hue.ink, lineWidth: 2.5))
            .scaleEffect(pulse ? 1.08 : 0.96)
            .offset(x: cos(radians) * 150, y: sin(radians) * 150)
            .animation(.easeInOut(duration: 0.6).repeatForever(autoreverses: true), value: pulse)
            .transition(.opacity)
    }

    private var prompt: String {
        if permissionDenied { return "ALLOW CAMERA TO CONTINUE" }
        if done { return "DONE · ENROLLED" }
        return Self.poses[min(poseIndex, Self.poses.count - 1)].label.uppercased()
    }

    private var poseDots: some View {
        HStack(spacing: 8) {
            ForEach(0..<Self.poses.count, id: \.self) { i in
                Circle()
                    .fill(i < poseIndex ? Hue.red : (i == poseIndex ? Hue.gold : Hue.cream))
                    .frame(width: 10, height: 10)
                    .overlay(Circle().strokeBorder(Hue.ink, lineWidth: 1.5))
            }
        }
    }

    // ----- driver -------------------------------------------------------

    private func begin() {
        pulse = true
        let total = perPose * Double(Self.poses.count)
        withAnimation(.linear(duration: total)) { totalProgress = 1 }
        advancePose(after: 0)
    }

    private func advancePose(after delay: Double) {
        DispatchQueue.main.asyncAfter(deadline: .now() + delay) {
            if poseIndex >= Self.poses.count - 1 {
                // last pose reached; finish after one more interval
                DispatchQueue.main.asyncAfter(deadline: .now() + perPose) {
                    withAnimation(.spring(response: 0.4, dampingFraction: 0.7)) { done = true }
                    DispatchQueue.main.asyncAfter(deadline: .now() + 0.7) { onSuccess() }
                }
            } else {
                withAnimation(.easeInOut(duration: 0.25)) { poseIndex += 1 }
                advancePose(after: perPose)
            }
        }
    }
}

private struct Pose {
    let label: String
    let arrow: String
    /// Angle in degrees clockwise from screen-right (3-o'clock).
    let angle: Double
}

// ----- AVFoundation preview ---------------------------------------------

private struct CameraPreviewView: UIViewRepresentable {
    @Binding var permissionDenied: Bool

    func makeUIView(context: Context) -> _PreviewUIView {
        let v = _PreviewUIView()
        Task { await v.start { granted in
            DispatchQueue.main.async { self.permissionDenied = !granted }
        } }
        return v
    }

    func updateUIView(_ uiView: _PreviewUIView, context: Context) {}

    static func dismantleUIView(_ uiView: _PreviewUIView, coordinator: ()) {
        uiView.stop()
    }
}

/// UIView that owns an AVCaptureSession + an AVCaptureVideoPreviewLayer.
/// The session itself is non-Sendable / accessed off-main, so we keep it
/// inside a small `nonisolated(unsafe)` slot and synchronize via a private
/// serial queue. The preview layer (UI-side) stays main-isolated.
private final class _PreviewUIView: UIView {
    nonisolated(unsafe) private let session = AVCaptureSession()
    private let queue = DispatchQueue(label: "thirdeye.facescan.session")
    nonisolated(unsafe) private var configured = false

    override class var layerClass: AnyClass { AVCaptureVideoPreviewLayer.self }
    private var previewLayer: AVCaptureVideoPreviewLayer { layer as! AVCaptureVideoPreviewLayer }

    override init(frame: CGRect) {
        super.init(frame: frame)
        previewLayer.session = session
        previewLayer.videoGravity = .resizeAspectFill
        backgroundColor = .black
    }

    required init?(coder: NSCoder) { fatalError("not implemented") }

    /// Request camera permission, configure the front camera, start the session.
    /// Calls `permission(true)` on grant, `permission(false)` on denial.
    func start(permission: @escaping (Bool) -> Void) async {
        let granted: Bool
        switch AVCaptureDevice.authorizationStatus(for: .video) {
        case .authorized:
            granted = true
        case .notDetermined:
            granted = await AVCaptureDevice.requestAccess(for: .video)
        default:
            granted = false
        }
        permission(granted)
        guard granted else { return }

        let session = self.session
        let configure = { [weak self] in self?.configureIfNeeded() }
        queue.async {
            configure()
            if !session.isRunning { session.startRunning() }
        }
    }

    func stop() {
        let session = self.session
        queue.async {
            if session.isRunning { session.stopRunning() }
        }
    }

    private func configureIfNeeded() {
        guard !configured else { return }
        session.beginConfiguration()
        session.sessionPreset = .high
        if let dev = AVCaptureDevice.default(.builtInWideAngleCamera, for: .video, position: .front),
           let input = try? AVCaptureDeviceInput(device: dev),
           session.canAddInput(input) {
            session.addInput(input)
        }
        session.commitConfiguration()
        configured = true
    }
}

// ----- decorative ring (kept from prior visual) -------------------------

private struct DottedRing: View {
    let count: Int
    let lineWidth: CGFloat
    let length: CGFloat
    let radius: CGFloat

    var body: some View {
        ZStack {
            ForEach(0..<count, id: \.self) { i in
                let a = Double(i) / Double(count) * .pi * 2
                Capsule()
                    .frame(width: lineWidth, height: length)
                    .offset(y: -radius)
                    .rotationEffect(.radians(a))
            }
        }
        .frame(width: radius * 2, height: radius * 2)
    }
}
