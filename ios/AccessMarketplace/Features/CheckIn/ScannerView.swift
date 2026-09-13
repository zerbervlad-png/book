// ScannerView.swift — сканер чек-ина (разделы 29, 49 ТЗ).
// Результат всегда определяет бэкенд; GPS — лишь вспомогательный сигнал.
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
            result = resultTitle(dto.result)
            resultColor = dto.result == "VALID" ? .green : .orange
        } catch {
            // оффлайн / ошибка бэкенда — критичные операции невозможны (43)
            result = (error as? LocalizedError)?.errorDescription ?? "Ошибка чек-ина"
            resultColor = .red
        }
    }

    private func resultTitle(_ result: String) -> String {
        switch result {
        case "VALID": return "Проход разрешён"
        case "USED": return "Уже использован"
        case "EXPIRED": return "Срок истёк"
        case "TRANSFERRED": return "Уже передан"
        case "NOT_YET_VALID": return "Ещё не действует"
        case "CANCELLED": return "Отменён"
        default: return "Недействителен"
        }
    }
}

struct ScannerView: View {
    @StateObject private var model = ScannerViewModel()
    @StateObject private var camera = CameraScanner()
    @State private var manualCode = ""

    var body: some View {
        VStack(spacing: 16) {
            // зона камеры с рамкой прицеливания
            ZStack {
                camera.view
                    .frame(maxHeight: 320)
                    .clipShape(RoundedRectangle(cornerRadius: 16))
                RoundedRectangle(cornerRadius: 16)
                    .stroke(.white.opacity(0.4), lineWidth: 2)
                    .frame(width: 220, height: 220)
                Label("Наведите на QR-код", systemImage: "viewfinder")
                    .font(.caption)
                    .padding(8)
                    .background(.ultraThinMaterial, in: Capsule())
                    .offset(y: 140)
            }
            .overlay(RoundedRectangle(cornerRadius: 16).stroke(.quaternary))

            if let result = model.result {
                Label(result, systemImage: model.resultColor == .green
                      ? "checkmark.circle.fill" : "exclamationmark.triangle.fill")
                    .font(.title3.bold())
                    .foregroundStyle(model.resultColor)
                    .padding(.horizontal, 16).padding(.vertical, 10)
                    .background(RoundedRectangle(cornerRadius: 14)
                        .fill(model.resultColor.opacity(0.1)))
            }

            Toggle(isOn: $model.includeGPS) {
                Label("Приложить GPS (необязательно)", systemImage: "location")
                    .font(.footnote)
            }
            .padding(.horizontal)

            HStack(spacing: 8) {
                TextField("Или введите код вручную", text: $manualCode)
                    .textFieldStyle(.roundedBorder)
                    .autocorrectionDisabled()
                    .textInputAutocapitalization(.characters)
                Button {
                    Task { await model.submit(code: manualCode, gps: nil) }
                } label: {
                    Text("Проверить").bold()
                }
                .buttonStyle(.borderedProminent)
                .disabled(manualCode.isEmpty)
            }
            .padding(.horizontal)

            Text("GPS никогда не требуется и не доказывает позицию в очереди.")
                .font(.caption2)
                .foregroundStyle(.secondary)
                .multilineTextAlignment(.center)
        }
        .padding()
        .navigationTitle("Чек-ин")
        .navigationBarTitleDisplayMode(.inline)
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

/// Обёртка над AVCaptureSession. Вся работа с сессией — на приватной
/// последовательной очереди, чтобы избежать гонок на `configured`.
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
            // сначала запрашиваем разрешение на камеру — иначе превью чёрное
            if AVCaptureDevice.authorizationStatus(for: .video) == .notDetermined {
                // ожидание семафором безопасно: мы не в главном потоке
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
