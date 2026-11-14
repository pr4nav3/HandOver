// UNTESTED: written on Windows, never compiled.

import Foundation
import AVFoundation
import CoreImage
import UIKit

/// Back camera at 1280x720, rotated to portrait, throttled to 1 JPEG per second.
final class PhoneCameraSource: NSObject, FrameSource, AVCaptureVideoDataOutputSampleBufferDelegate {
    var onFrame: ((Data) -> Void)?
    /// Called on any queue with a human-readable problem (permission denied, no camera, ...).
    var onError: ((String) -> Void)?

    private let session = AVCaptureSession()
    private let sessionQueue = DispatchQueue(label: "handover.phone.session")
    private let videoQueue = DispatchQueue(label: "handover.phone.video")
    private let throttle = FrameThrottle(interval: 1.0)
    private let ciContext = CIContext(options: nil)

    // sessionQueue only
    private var configured = false
    private var wantsRunning = false

    func start() {
        throttle.reset()
        sessionQueue.async { [weak self] in
            guard let self = self else { return }
            self.wantsRunning = true
            switch AVCaptureDevice.authorizationStatus(for: .video) {
            case .authorized:
                self.configureAndRun()
            case .notDetermined:
                // Hold the queue until the user answers the prompt.
                self.sessionQueue.suspend()
                AVCaptureDevice.requestAccess(for: .video) { granted in
                    if !granted {
                        self.report("Camera access denied. Allow it in Settings > HandOver.")
                    }
                    self.sessionQueue.resume()
                }
                self.sessionQueue.async {
                    if AVCaptureDevice.authorizationStatus(for: .video) == .authorized {
                        self.configureAndRun()
                    }
                }
            case .denied, .restricted:
                self.report("Camera access denied. Allow it in Settings > HandOver.")
            @unknown default:
                self.report("Camera access unavailable.")
            }
        }
    }

    func stop() {
        sessionQueue.async { [weak self] in
            guard let self = self else { return }
            self.wantsRunning = false
            if self.session.isRunning {
                self.session.stopRunning()
            }
        }
    }

    // MARK: - Session setup (sessionQueue)

    private func configureAndRun() {
        guard wantsRunning else { return }
        if !configured {
            guard configure() else { return }
        }
        if !session.isRunning {
            session.startRunning() // blocking; never call on main
        }
    }

    private func configure() -> Bool {
        session.beginConfiguration()
        defer { session.commitConfiguration() }

        if session.canSetSessionPreset(.hd1280x720) {
            session.sessionPreset = .hd1280x720
        }

        guard let device = AVCaptureDevice.default(.builtInWideAngleCamera, for: .video, position: .back) else {
            report("No back camera on this device.")
            return false
        }

        let input: AVCaptureDeviceInput
        do {
            input = try AVCaptureDeviceInput(device: device)
        } catch {
            report("Camera input failed: \(error.localizedDescription)")
            return false
        }
        guard session.canAddInput(input) else {
            report("Cannot use the back camera.")
            return false
        }
        session.addInput(input)

        // We only keep 1 frame/s, so ask the sensor for 15 fps to save power and heat.
        do {
            try device.lockForConfiguration()
            let supports15 = device.activeFormat.videoSupportedFrameRateRanges.contains { range in
                range.minFrameRate <= 15 && range.maxFrameRate >= 15
            }
            if supports15 {
                let duration = CMTime(value: 1, timescale: 15)
                device.activeVideoMinFrameDuration = duration
                device.activeVideoMaxFrameDuration = duration
            }
            device.unlockForConfiguration()
        } catch {
            // Not fatal; keep the default frame rate.
        }

        let output = AVCaptureVideoDataOutput()
        output.alwaysDiscardsLateVideoFrames = true
        output.videoSettings = [kCVPixelBufferPixelFormatTypeKey as String: Int(kCVPixelFormatType_32BGRA)]
        output.setSampleBufferDelegate(self, queue: videoQueue)
        guard session.canAddOutput(output) else {
            report("Cannot read camera frames.")
            return false
        }
        session.addOutput(output)

        // Sensor buffers are landscape; rotate so frames are upright with the phone in portrait.
        if let connection = output.connection(with: .video),
           connection.isVideoRotationAngleSupported(90) {
            connection.videoRotationAngle = 90
        }

        configured = true
        return true
    }

    private func report(_ message: String) {
        onError?(message)
    }

    // MARK: - AVCaptureVideoDataOutputSampleBufferDelegate (videoQueue)

    func captureOutput(_ output: AVCaptureOutput,
                       didOutput sampleBuffer: CMSampleBuffer,
                       from connection: AVCaptureConnection) {
        guard throttle.shouldEmit() else { return }
        guard let pixelBuffer = CMSampleBufferGetImageBuffer(sampleBuffer) else { return }
        let ciImage = CIImage(cvPixelBuffer: pixelBuffer)
        guard let cgImage = ciContext.createCGImage(ciImage, from: ciImage.extent) else { return }
        let image = UIImage(cgImage: cgImage)
        guard let jpeg = JPEGEncoder.encode(image) else { return }
        onFrame?(jpeg)
    }
}
