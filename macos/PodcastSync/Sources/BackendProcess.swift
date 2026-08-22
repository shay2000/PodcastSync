import Foundation
import SwiftUI

@MainActor
class BackendProcess: ObservableObject {
    @Published var isRunning = false
    @Published var statusText = "Starting..."
    @Published var statusIcon = "antenna.radiowaves.left.and.right"
    @Published var cookieStatusOk: Bool? = nil   // nil = unknown, true = ok, false = not configured / failing

    let port: Int

    private var process: Process?
    private var healthCheckTimer: Timer?
    private var stdoutPipe: Pipe?
    private var stderrPipe: Pipe?
    private var healthCheckCount = 0

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
        var env = ProcessInfo.processInfo.environment

        // Look for the bundled backend in the app's Resources
        let bundlePath = Bundle.main.resourcePath ?? ""
        let backendPath = "\(bundlePath)/backend/podcastsync-backend"
        let bundledToolsPath = "\(bundlePath)/tools/bin"
        let bundledFFmpegPath = "\(bundledToolsPath)/ffmpeg"
        let uvicornPath = findUvicorn()

        // Clear macOS quarantine from bundled binaries so Gatekeeper allows them to run.
        // This is needed when the app is installed from a downloaded DMG.
        let quarantineTargets = [backendPath, bundledFFmpegPath, "\(bundledToolsPath)/ffprobe"]
        for target in quarantineTargets {
            let xattr = Process()
            xattr.executableURL = URL(fileURLWithPath: "/usr/bin/xattr")
            xattr.arguments = ["-d", "com.apple.quarantine", target]
            try? xattr.run()
            xattr.waitUntilExit()
        }

        if FileManager.default.isExecutableFile(atPath: bundledFFmpegPath) {
            env["PODCASTSYNC_FFMPEG"] = bundledFFmpegPath
            env["PATH"] = "\(bundledToolsPath):\(env["PATH"] ?? "/usr/bin:/bin:/usr/sbin:/sbin")"
        }

        if FileManager.default.fileExists(atPath: backendPath) {
            // Bundled PyInstaller binary
            proc.executableURL = URL(fileURLWithPath: backendPath)
        } else if let uvicorn = uvicornPath, let projectRoot = findProjectRoot() {
            // Development mode: run uvicorn directly
            proc.executableURL = URL(fileURLWithPath: uvicorn)
            proc.arguments = [
                "backend.main:app",
                "--host", "0.0.0.0",
                "--port", String(port),
            ]
            proc.currentDirectoryURL = projectRoot
            env["PYTHONPATH"] = projectRoot.path
        } else {
            statusText = "Backend not found"
            statusIcon = "exclamationmark.triangle"
            return
        }

        proc.environment = env

        stdoutPipe = Pipe()
        stderrPipe = Pipe()
        proc.standardOutput = stdoutPipe
        proc.standardError = stderrPipe

        let backend = self
        proc.terminationHandler = { [weak backend] _ in
            guard let backend else { return }
            Task { @MainActor in
                backend.isRunning = false
                backend.statusText = "Stopped"
                backend.statusIcon = "antenna.radiowaves.left.and.right"
                backend.healthCheckTimer?.invalidate()
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
        let backend = self
        DispatchQueue.global().async { [weak backend] in
            let deadline = Date().addingTimeInterval(5)
            while proc.isRunning && Date() < deadline {
                Thread.sleep(forTimeInterval: 0.1)
            }
            if proc.isRunning {
                proc.interrupt()
            }
            guard let backend else { return }
            Task { @MainActor in
                backend.process = nil
                backend.isRunning = false
                backend.statusText = "Stopped"
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
        let backend = self
        healthCheckTimer = Timer.scheduledTimer(withTimeInterval: 3.0, repeats: true) { [weak backend] _ in
            guard let backend else { return }
            Task { @MainActor in
                await backend.checkHealth()
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
                // Check cookie status once on first healthy response, then every ~60s
                healthCheckCount += 1
                if healthCheckCount == 1 || healthCheckCount % 20 == 0 {
                    await checkCookieStatus()
                }
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

    private func checkCookieStatus() async {
        guard let url = URL(string: "http://127.0.0.1:\(port)/api/cookies/test") else { return }
        var request = URLRequest(url: url, timeoutInterval: 20)
        request.httpMethod = "POST"
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        request.httpBody = Data("{}".utf8)
        do {
            let (data, _) = try await URLSession.shared.data(for: request)
            if let json = try? JSONSerialization.jsonObject(with: data) as? [String: Any],
               let status = json["status"] as? String {
                cookieStatusOk = (status == "ok")
            }
        } catch {
            // Non-fatal: leave cookieStatusOk as-is
        }
    }

    // MARK: - Helpers

    private func findProjectRoot() -> URL? {
        // 1. Explicit env var
        if let envRoot = ProcessInfo.processInfo.environment["PODCASTSYNC_PROJECT_ROOT"] {
            let url = URL(fileURLWithPath: envRoot)
            if FileManager.default.fileExists(atPath: url.appendingPathComponent("backend/main.py").path) {
                return url
            }
        }
        // 2. Walk up from the running executable looking for backend/main.py
        var dir = URL(fileURLWithPath: ProcessInfo.processInfo.arguments[0])
            .deletingLastPathComponent()
        for _ in 0..<8 {
            if FileManager.default.fileExists(atPath: dir.appendingPathComponent("backend/main.py").path) {
                return dir
            }
            dir = dir.deletingLastPathComponent()
        }
        return nil
    }

    private func findUvicorn() -> String? {
        // Check virtual env relative to project root first, then system locations
        if let root = findProjectRoot() {
            let venvPath = root.appendingPathComponent("venv/bin/uvicorn").path
            if FileManager.default.isExecutableFile(atPath: venvPath) {
                return venvPath
            }
        }
        let systemPaths = ["/usr/local/bin/uvicorn", "/opt/homebrew/bin/uvicorn"]
        for path in systemPaths {
            if FileManager.default.isExecutableFile(atPath: path) {
                return path
            }
        }
        return nil
    }
}
