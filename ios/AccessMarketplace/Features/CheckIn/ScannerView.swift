// ScannerView.swift — check-in scanner (sections 29, 49).
// Result is always decided by the backend; GPS is optional auxiliary input.
import SwiftUI
import AVFoundation

@MainActor
final class ScannerViewModel: ObservableObject {
    @Published var result: String?
    @Published var resultColor: Color = .green
    @Published var includeGPS = false

    func submit(code: String, gps: [String: Double?]?) async {
        var body: [String: AnyEncodable?] = [
            "token": AnyEncodable(code),
            "method": AnyEncodable("QR"),
        ]
        if includeGPS, let gps {
            body["gps"] = AnyEncodable(gps.compactMapValues { $0 })
        }
        do {
            let dto: CheckInResultDTO = try await APIClient.shared.request(
                "POST", "/checkins", body: body.compactMapValues { $0 },
                as: CheckInResultDTO.self)
            result = dto.result
            resultColor = dto.result == "VALID" ? .green : .orange
        } catch {
            // offline / backend error — critical ops stay impossible (43)
            result = (error as? LocalizedError)?.errorDescription ?? "Check-in failed"
            resultColor = .red
        }
    }
}

struct ScannerView: View {
    @StateObject private var model = ScannerViewModel()
    @StateObject private var camera = CameraScanner()
    @State private var manualCode = ""

    var body: some View {
        VStack(spacing: 16) {
            camera.view
                .frame(maxHeight: 320)
                .cornerRadius(12)
                .overlay(RoundedRectangle(cornerRadius: 12).stroke(.quaternary))
            if let result = model.result {
                Label(result, systemImage: model.resultColor == .green
                      ? "checkmark.circle.fill" : "exclamationmark.triangle.fill")
                    .font(.title3.bold())
                    .foregroundStyle(model.resultColor)
            }
            Toggle("Attach GPS (auxiliary only)", isOn: $model.includeGPS)
                .font(.footnote)
            HStack {
                TextField("Or enter code manually", text: $manualCode)
                    .textFieldStyle(.roundedBorder)
                    .autocorrectionDisabled()
                Button("Submit") {
                    Task { await model.submit(code: manualCode, gps: nil) }
                }
                .disabled(manualCode.isEmpty)
            }
            .padding(.horizontal)
            Text("GPS is never required and never proves queue position.")
                .font(.caption2).foregroundStyle(.secondary)
        }
        .padding()
        .navigationTitle("Check-in")
        .onAppear {
            camera.onCode = { [weak model] code in
                guard let model else { return }
                Task { await model.submit(code: code, gps: nil) }
            }
            camera.start()
        }
        .onDisappear {
            camera.onCode = nil
            camera.stop()
        }
    }
}

/// Thin AVCaptureSession wrapper. All session work is confined to a private
/// serial queue to avoid data races on `configured` / session state.
final class CameraScanner: NSObject, ObservableObject, AVCaptureMetadataOutputObjectsDelegate {
    let session = AVCaptureSession()
    private let output = AVCaptureMetadataOutput()
    private let sessionQueue = DispatchQueue(label: "am.scanner.session")
    private var configured = false

    var onCode: ((String) -> Void)?

    lazy var view: some View = {
        ScannerPreviewView(session: session)
    }()

    func start() {
        sessionQueue.async { [self] in
            // request camera permission first — without it the preview stays black
            if AVCaptureDevice.authorizationStatus(for: .video) == .notDetermined {
                // Semaphore wait is safe here: this runs off the main thread.
                let semaphore = DispatchSemaphore(value: 0)
                AVCaptureDevice.requestAccess(for: .video) { _ in semaphore.signal() }
                semaphore.wait()
            }
            guard AVCaptureDevice.authorizationStatus(for: .video) == .authorized else { return }
            if !configured { configure() }
            if !session.isRunning { session.startRunning() }
        }
    }

    func stop() {
        sessionQueue.async { [self] in
            if session.isRunning { session.stopRunning() }
        }
    }

    private func configure() {
        configured = true
        guard let device = AVCaptureDevice.default(for: .video),
              let input = try? AVCaptureDeviceInput(device: device),
              session.canAddInput(input) else { return }
        session.addInput(input)
        session.addOutput(output)
        output.setMetadataObjectsDelegate(self, queue: .main)
        output.metadataObjectTypes = [.qr, .code128]
    }

    func metadataOutput(_ output: AVCaptureMetadataOutput,
                        didOutput metadataObjects: [AVMetadataObject],
                        from connection: AVCaptureConnection) {
        guard let object = metadataObjects.first as? AVMetadataMachineReadableCodeObject,
              let value = object.stringValue else { return }
        onCode?(value)
    }
}

struct ScannerPreviewView: UIViewRepresentable {
    let session: AVCaptureSession

    final class PreviewUIView: UIView {
        override class var layerClass: AnyClass { AVCaptureVideoPreviewLayer.self }
        var previewLayer: AVCaptureVideoPreviewLayer { layer as! AVCaptureVideoPreviewLayer }
    }

    func makeUIView(context: Context) -> PreviewUIView {
        let view = PreviewUIView()
        view.previewLayer.session = session
        view.previewLayer.videoGravity = .resizeAspectFill
        return view
    }

    func updateUIView(_ uiView: PreviewUIView, context: Context) {}
}
