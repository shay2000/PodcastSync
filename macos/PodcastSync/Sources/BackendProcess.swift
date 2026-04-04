import Foundation
import SwiftUI

@MainActor
class BackendProcess: ObservableObject {
    @Published var isRunning = false
    @Published var statusText = "Starting..."
    @Published var statusIcon = "antenna.radiowaves.left.and.right"

    let port: Int

    private var process: Process?
    private var healthCheckTimer: Timer?
    private var stdoutPipe: Pipe?
    private var stderrPipe: Pipe?

    var statusColor: Color {
        isRunning ? .green : .red
    }

    init() {
        self.port = Int(ProcessInfo.processInfo.environment["PODCASTSYNC_PORT"] ?? "8642") ?? 8642
        start()
    }

    // MARK: - Process Lifecycle

    func start() {
        guard process == nil || !(process?.isRunning ?? false) else { return }

        statusText = "Starting..."
        statusIcon = "antenna.radiowaves.left.and.right"

        let proc = Process()

        // Look for the bundled backend in the app's Resources
        let bundlePath = Bundle.main.resourcePath ?? ""
        let backendPath = "\(bundlePath)/backend/podcastsync-backend"
        let uvicornPath = findUvicorn()

        if FileManager.default.fileExists(atPath: backendPath) {
            // Bundled PyInstaller binary
            proc.executableURL = URL(fileURLWithPath: backendPath)
        } else if let uvicorn = uvicornPath {
            // Development mode: run uvicorn directly
            proc.executableURL = URL(fileURLWithPath: uvicorn)
            proc.arguments = [
                "backend.main:app",
                "--host", "0.0.0.0",
                "--port", String(port),
            ]
            // Set working directory to project root (two levels up from macos/PodcastSync/)
            let projectRoot = URL(fileURLWithPath: #filePath)
                .deletingLastPathComponent()  // Sources/
                .deletingLastPathComponent()  // PodcastSync/
                .deletingLastPathComponent()  // macos/
                .deletingLastPathComponent()  // project root
            proc.currentDirectoryURL = projectRoot
            var env = ProcessInfo.processInfo.environment
            env["PYTHONPATH"] = projectRoot.path
            proc.environment = env
        } else {
            statusText = "Backend not found"
            statusIcon = "exclamationmark.triangle"
            return
        }

        stdoutPipe = Pipe()
        stderrPipe = Pipe()
        proc.standardOutput = stdoutPipe
        proc.standardError = stderrPipe

        proc.terminationHandler = { [weak self] _ in
            Task { @MainActor in
                self?.isRunning = false
                self?.statusText = "Stopped"
                self?.statusIcon = "antenna.radiowaves.left.and.right"
                self?.healthCheckTimer?.invalidate()
            }
        }

        do {
            try proc.run()
            process = proc
            startHealthCheck()
        } catch {
            statusText = "Failed to start: \(error.localizedDescription)"
            statusIcon = "exclamationmark.triangle"
        }
    }

    func stop() {
        healthCheckTimer?.invalidate()
        healthCheckTimer = nil

        guard let proc = process, proc.isRunning else {
            isRunning = false
            statusText = "Stopped"
            return
        }

        proc.terminate()

        // Wait briefly, then force kill if needed
        DispatchQueue.global().async { [weak self] in
            let deadline = Date().addingTimeInterval(5)
            while proc.isRunning && Date() < deadline {
                Thread.sleep(forTimeInterval: 0.1)
            }
            if proc.isRunning {
                proc.interrupt()
            }
            Task { @MainActor in
                self?.process = nil
                self?.isRunning = false
                self?.statusText = "Stopped"
            }
        }
    }

    func triggerSyncAll() {
        guard isRunning else { return }
        let url = URL(string: "http://127.0.0.1:\(port)/api/sync-all")!
        var request = URLRequest(url: url)
        request.httpMethod = "POST"
        URLSession.shared.dataTask(with: request).resume()
    }

    // MARK: - Health Check

    private func startHealthCheck() {
        healthCheckTimer = Timer.scheduledTimer(withTimeInterval: 3.0, repeats: true) { [weak self] _ in
            Task { @MainActor in
                await self?.checkHealth()
            }
        }
    }

    private func checkHealth() async {
        let url = URL(string: "http://127.0.0.1:\(port)/api/status")!
        do {
            let (_, response) = try await URLSession.shared.data(from: url)
            if let http = response as? HTTPURLResponse, http.statusCode == 200 {
                isRunning = true
                statusText = "Running on port \(port)"
                statusIcon = "antenna.radiowaves.left.and.right"
            } else {
                isRunning = false
                statusText = "Not responding"
                statusIcon = "exclamationmark.triangle"
            }
        } catch {
            // Server might still be starting up
            if process?.isRunning == true {
                statusText = "Starting..."
            } else {
                isRunning = false
                statusText = "Stopped"
            }
        }
    }

    // MARK: - Helpers

    private func findUvicorn() -> String? {
        // Check common locations
        let candidates = [
            // Virtual env relative to project root
            URL(fileURLWithPath: #filePath)
                .deletingLastPathComponent()
                .deletingLastPathComponent()
                .deletingLastPathComponent()
                .deletingLastPathComponent()
                .appendingPathComponent("venv/bin/uvicorn").path,
            "/usr/local/bin/uvicorn",
            "/opt/homebrew/bin/uvicorn",
        ]
        for path in candidates {
            if FileManager.default.isExecutableFile(atPath: path) {
                return path
            }
        }
        return nil
    }
}
