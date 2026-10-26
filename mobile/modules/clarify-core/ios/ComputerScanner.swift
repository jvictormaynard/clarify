import AVFoundation
import UIKit

final class ComputerScanner: UIViewController, AVCaptureMetadataOutputObjectsDelegate, UIAdaptivePresentationControllerDelegate {
  private let capture = AVCaptureSession()
  private let queue = DispatchQueue(label: "clarify.computer.scanner")
  private var completion: ((Result<String, Error>) -> Void)?
  private var preview: AVCaptureVideoPreviewLayer?
  init(completion: @escaping (Result<String, Error>) -> Void) { self.completion = completion; super.init(nibName: nil, bundle: nil) }
  required init?(coder: NSCoder) { fatalError("init(coder:) is not used") }
  @MainActor static func scan(from presenter: UIViewController) async throws -> String {
    let allowed = await withCheckedContinuation { continuation in
      AVCaptureDevice.requestAccess(for: .video) { continuation.resume(returning: $0) }
    }
    guard allowed else { throw ComputerFailure.cameraDenied }
    guard UIApplication.shared.applicationState == .active, presenter.presentedViewController == nil else { throw ComputerFailure.cameraUnavailable }
    return try await withCheckedThrowingContinuation { continuation in
      let scanner = ComputerScanner { continuation.resume(with: $0) }
      let navigation = UINavigationController(rootViewController: scanner)
      navigation.presentationController?.delegate = scanner
      presenter.present(navigation, animated: true)
    }
  }
  override func viewDidLoad() {
    super.viewDidLoad(); view.backgroundColor = .black
    title = L("Leia o QR do computador")
    navigationItem.leftBarButtonItem = UIBarButtonItem(title: L("Cancelar"), style: .plain, target: self, action: #selector(cancel))
    let preview = AVCaptureVideoPreviewLayer(session: capture); preview.videoGravity = .resizeAspectFill
    view.layer.addSublayer(preview); self.preview = preview
    queue.async { [weak self] in
      guard let self else { return }
      do {
        guard let camera = AVCaptureDevice.default(for: .video) else { throw ComputerFailure.cameraUnavailable }
        let input = try AVCaptureDeviceInput(device: camera), output = AVCaptureMetadataOutput()
        self.capture.beginConfiguration()
        guard self.capture.canAddInput(input), self.capture.canAddOutput(output) else { self.capture.commitConfiguration(); throw ComputerFailure.cameraUnavailable }
        self.capture.addInput(input); self.capture.addOutput(output)
        output.setMetadataObjectsDelegate(self, queue: .main); output.metadataObjectTypes = [.qr]
        self.capture.commitConfiguration(); self.capture.startRunning()
      } catch { DispatchQueue.main.async { self.finish(.failure(ComputerFailure.cameraUnavailable)) } }
    }
  }
  override func viewDidLayoutSubviews() { super.viewDidLayoutSubviews(); preview?.frame = view.bounds }
  override func viewDidDisappear(_ animated: Bool) { super.viewDidDisappear(animated); finish(.failure(ComputerFailure.cancelled)) }
  func presentationControllerDidDismiss(_ presentationController: UIPresentationController) { finish(.failure(ComputerFailure.cancelled)) }
  @objc private func cancel() { finish(.failure(ComputerFailure.cancelled)) }
  private func finish(_ result: Result<String, Error>) {
    guard let completion else { return }; self.completion = nil
    queue.async { [capture] in capture.stopRunning() }
    let container = navigationController ?? self
    if container.presentingViewController != nil { container.dismiss(animated: true) { completion(result) } }
    else { completion(result) }
  }
  func metadataOutput(_ output: AVCaptureMetadataOutput, didOutput metadataObjects: [AVMetadataObject], from connection: AVCaptureConnection) {
    guard let value = (metadataObjects.first as? AVMetadataMachineReadableCodeObject)?.stringValue else { return }
    // Parsing and pairing stay in Swift. The bootstrap URL never crosses JS.
    do { _ = try ComputerInvitation.parse(value); finish(.success(value)) }
    catch { finish(.failure(error)) }
  }
}
